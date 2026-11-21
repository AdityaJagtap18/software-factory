import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.api.deps import get_current_user, require_org_admin, require_org_member
from app.core.crypto import decrypt_value, encrypt_value
from app.core.database import get_db
from app.models.agent import Agent, AgentStatus
from app.models.agent_runtime import CodingAgentConnection, ConnectionStatus, Credential
from app.models.organization import OrganizationMember
from app.models.user import User
from app.schemas.agent_runtime import (
    AgentResponse,
    CapabilitySchema,
    ConnectionCreate,
    ConnectionResponse,
    ModelCatalogResponse,
    RuntimeCatalogEntry,
)
from app.services import audit
from app.services.agent_registry import sync_agent_registry
from app.services.agent_runtime.registry import all_adapters, get_adapter

router = APIRouter(tags=["coding-agent-runtimes"])


def _capability_schemas(adapter) -> list[CapabilitySchema]:
    return [CapabilitySchema(name=c.name, state=c.state.value) for c in adapter.capabilities()]


@router.get("/coding-agent-runtimes", response_model=list[RuntimeCatalogEntry])
def list_runtime_catalog() -> list[RuntimeCatalogEntry]:
    """Static adapter metadata — the set of runtimes this backend can integrate with."""
    return [
        RuntimeCatalogEntry(
            slug=a.slug,
            name=a.display_name,
            description=a.description,
            icon=a.icon,
            supported_connection_modes=list(a.supported_connection_modes),
            auth_method=a.auth_method,
            capabilities=_capability_schemas(a),
        )
        for a in all_adapters()
    ]


@router.get("/agents", response_model=list[AgentResponse])
def list_agents(
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[Agent]:
    """Phase 2 (P2-4) Agent Registry: a platform-wide, read-only catalog of
    known coding-agent runtimes, backed by a real `agents` table kept in
    sync with the adapter registry (never a hand-maintained duplicate of
    `/coding-agent-runtimes`). Any authenticated user may list it -- it is
    non-sensitive platform metadata, the same trust level as
    `/coding-agent-runtimes` itself."""
    sync_agent_registry(db)
    return db.query(Agent).order_by(Agent.slug).all()


@router.get(
    "/organizations/{organization_id}/coding-agent-runtimes/model-catalog",
    response_model=ModelCatalogResponse,
)
def get_organization_model_catalog(
    organization_id: uuid.UUID,
    membership: OrganizationMember = Depends(require_org_member),
    db: DBSession = Depends(get_db),
) -> ModelCatalogResponse:
    """Returns the dynamic ChatGPT-style model catalog for this organization."""
    from app.services.model_catalog_service import get_model_catalog
    return get_model_catalog(db, organization_id)


def _connection_response(
    organization_id: uuid.UUID, adapter, connection: CodingAgentConnection | None
) -> ConnectionResponse:
    if connection is None:
        return ConnectionResponse(
            id=None,
            is_configured=False,
            organization_id=organization_id,
            runtime_slug=adapter.slug,
            runtime_name=adapter.display_name,
            icon=adapter.icon,
            description=adapter.description,
            connection_mode=None,
            auth_method=adapter.auth_method,
            status=ConnectionStatus.NOT_CONFIGURED,
            detected_version="",
            last_error="",
            last_health_check_at=None,
            has_credential=False,
            capabilities=_capability_schemas(adapter),
        )
    return ConnectionResponse(
        id=connection.id,
        is_configured=True,
        organization_id=organization_id,
        runtime_slug=adapter.slug,
        runtime_name=adapter.display_name,
        icon=adapter.icon,
        description=adapter.description,
        connection_mode=connection.connection_mode,
        auth_method=adapter.auth_method,
        status=connection.status,
        detected_version=connection.detected_version,
        last_error=connection.last_error,
        last_health_check_at=connection.last_health_check_at,
        has_credential=connection.credential_id is not None,
        capabilities=_capability_schemas(adapter),
    )


@router.get(
    "/organizations/{organization_id}/coding-agent-connections",
    response_model=list[ConnectionResponse],
)
def list_connections(
    organization_id: uuid.UUID,
    membership: OrganizationMember = Depends(require_org_member),
    db: DBSession = Depends(get_db),
) -> list[ConnectionResponse]:
    existing = {
        c.runtime_slug: c
        for c in db.query(CodingAgentConnection).filter_by(organization_id=organization_id).all()
    }
    return [
        _connection_response(organization_id, adapter, existing.get(adapter.slug))
        for adapter in all_adapters()
    ]


def _run_health_check(
    db: DBSession, connection: CodingAgentConnection, adapter
) -> CodingAgentConnection:
    credential_value = None
    if connection.credential_id is not None:
        credential = db.get(Credential, connection.credential_id)
        if credential is not None:
            credential_value = decrypt_value(credential.encrypted_value)

    result = adapter.health_check(credential_value)
    connection.status = ConnectionStatus.CONNECTED if result.connected else ConnectionStatus.NOT_CONNECTED
    connection.detected_version = result.version
    connection.last_error = "" if result.connected else result.detail
    connection.last_health_check_at = datetime.now(timezone.utc)
    return connection


@router.post(
    "/organizations/{organization_id}/coding-agent-connections",
    response_model=ConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_connection(
    organization_id: uuid.UUID,
    payload: ConnectionCreate,
    admin_membership: OrganizationMember = Depends(require_org_admin),
    db: DBSession = Depends(get_db),
) -> ConnectionResponse:
    adapter = get_adapter(payload.runtime_slug)
    if adapter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown runtime")
    if payload.connection_mode.value not in adapter.supported_connection_modes:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{payload.connection_mode.value}' is not supported by {adapter.display_name}",
        )

    existing = (
        db.query(CodingAgentConnection)
        .filter_by(organization_id=organization_id, runtime_slug=payload.runtime_slug)
        .first()
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This runtime is already configured")

    credential = None
    if payload.credential_value:
        credential = Credential(
            organization_id=organization_id,
            name=payload.credential_name or f"{adapter.display_name} credential",
            provider=payload.credential_provider or adapter.slug,
            encrypted_value=encrypt_value(payload.credential_value),
            created_by_user_id=admin_membership.user_id,
        )
        db.add(credential)
        db.flush()

    connection = CodingAgentConnection(
        organization_id=organization_id,
        runtime_slug=payload.runtime_slug,
        connection_mode=payload.connection_mode,
        credential_id=credential.id if credential is not None else None,
        created_by_user_id=admin_membership.user_id,
    )
    db.add(connection)
    db.flush()

    _run_health_check(db, connection, adapter)

    audit.record(
        db,
        action="coding_agent_connection.create",
        target_type="coding_agent_connection",
        target_id=str(connection.id),
        actor_user_id=admin_membership.user_id,
        organization_id=organization_id,
        extra={"runtime_slug": adapter.slug, "status": connection.status.value},
    )
    db.commit()
    db.refresh(connection)
    return _connection_response(organization_id, adapter, connection)


@router.post(
    "/organizations/{organization_id}/coding-agent-connections/{connection_id}/health-check",
    response_model=ConnectionResponse,
)
def recheck_connection(
    organization_id: uuid.UUID,
    connection_id: uuid.UUID,
    membership: OrganizationMember = Depends(require_org_member),
    db: DBSession = Depends(get_db),
) -> ConnectionResponse:
    connection = db.get(CodingAgentConnection, connection_id)
    if connection is None or connection.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    adapter = get_adapter(connection.runtime_slug)
    if adapter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown runtime")

    _run_health_check(db, connection, adapter)
    audit.record(
        db,
        action="coding_agent_connection.health_check",
        target_type="coding_agent_connection",
        target_id=str(connection.id),
        actor_user_id=membership.user_id,
        organization_id=organization_id,
        extra={"status": connection.status.value},
    )
    db.commit()
    db.refresh(connection)
    return _connection_response(organization_id, adapter, connection)


@router.delete(
    "/organizations/{organization_id}/coding-agent-connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_connection(
    organization_id: uuid.UUID,
    connection_id: uuid.UUID,
    admin_membership: OrganizationMember = Depends(require_org_admin),
    db: DBSession = Depends(get_db),
) -> None:
    connection = db.get(CodingAgentConnection, connection_id)
    if connection is None or connection.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")

    credential_id = connection.credential_id
    audit.record(
        db,
        action="coding_agent_connection.delete",
        target_type="coding_agent_connection",
        target_id=str(connection.id),
        actor_user_id=admin_membership.user_id,
        organization_id=organization_id,
        extra={"runtime_slug": connection.runtime_slug},
    )
    db.delete(connection)
    if credential_id is not None:
        credential = db.get(Credential, credential_id)
        if credential is not None:
            db.delete(credential)
    db.commit()
