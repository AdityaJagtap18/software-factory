"""Phase 5 (P5-1/P5-3): capability-based agent assignment and
policy-controlled provider routing/fallback.

Deliberately built on top of the real entities that already exist rather
than inventing parallel ones: eligibility comes from the real `Agent`
registry (`app/models/agent.py`, kept in sync with the real adapter
registry by `app/services/agent_registry.py`) crossed with the
organization's real, currently-`CONNECTED` `CodingAgentConnection` rows --
never a fabricated "available agents" list. `ProviderRoutingPolicy`
(`app/models/orchestration.py`) only ever narrows or orders that real set;
it can never make an unconnected/ineligible connection selectable.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session as DBSession

from app.models.agent import Agent, AgentStatus
from app.models.agent_runtime import CodingAgentConnection, ConnectionStatus
from app.models.orchestration import ProviderRoutingPolicy


def _agents_with_capability(db: DBSession, capability: str) -> set[str]:
    """Real `Agent.slug`s (ACTIVE only) whose capability list names
    `capability` -- matched case-insensitively against each capability's
    `name`, since these are free-form adapter-declared labels
    (`app/services/agent_runtime/base.py::Capability`), not an enum."""
    if not capability:
        return set()
    needle = capability.strip().lower()
    slugs: set[str] = set()
    for agent in db.query(Agent).filter(Agent.status == AgentStatus.ACTIVE).all():
        for cap in agent.capabilities or []:
            name = (cap or {}).get("name", "") if isinstance(cap, dict) else ""
            if needle in name.strip().lower():
                slugs.add(agent.slug)
                break
    return slugs


def eligible_connections_for_capability(
    db: DBSession, organization_id: uuid.UUID, capability: str
) -> list[CodingAgentConnection]:
    """Real, currently-connected connections belonging to this
    organization whose runtime has the given capability. An empty
    `capability` means "any connected connection" (no capability filter),
    since not every task/step declares one. Ordered by `runtime_slug` for
    a deterministic default when no routing policy applies."""
    query = db.query(CodingAgentConnection).filter(
        CodingAgentConnection.organization_id == organization_id,
        CodingAgentConnection.status == ConnectionStatus.CONNECTED,
    )
    connections = query.order_by(CodingAgentConnection.runtime_slug).all()
    if not capability:
        return connections
    eligible_slugs = _agents_with_capability(db, capability)
    return [c for c in connections if c.runtime_slug in eligible_slugs]


def _routing_policy(
    db: DBSession, organization_id: uuid.UUID, capability: str
) -> ProviderRoutingPolicy | None:
    """The capability-specific policy if one exists, else the
    organization-wide default (`capability IS NULL`), else None (meaning
    "no policy; use the default deterministic order")."""
    if capability:
        specific = (
            db.query(ProviderRoutingPolicy)
            .filter(
                ProviderRoutingPolicy.organization_id == organization_id,
                ProviderRoutingPolicy.capability == capability,
            )
            .first()
        )
        if specific is not None:
            return specific
    return (
        db.query(ProviderRoutingPolicy)
        .filter(
            ProviderRoutingPolicy.organization_id == organization_id,
            ProviderRoutingPolicy.capability.is_(None),
        )
        .first()
    )


def select_connection(
    db: DBSession,
    organization_id: uuid.UUID,
    capability: str,
    exclude_connection_ids: set[uuid.UUID] | None = None,
) -> CodingAgentConnection | None:
    """Picks the single best real, connected candidate for `capability`
    (B1's auto-assignment and B3's "next provider to try" are the same
    operation: this one function serves both). Returns None -- never a
    fabricated connection -- when nothing eligible exists, so the caller
    can escalate/fail honestly instead of starting a doomed execution."""
    exclude = exclude_connection_ids or set()
    candidates = [
        c for c in eligible_connections_for_capability(db, organization_id, capability)
        if c.id not in exclude
    ]
    if not candidates:
        return None

    policy = _routing_policy(db, organization_id, capability)
    if policy and policy.fallback_chain:
        by_slug = {c.runtime_slug: c for c in candidates}
        for slug in policy.fallback_chain:
            if slug in by_slug:
                return by_slug[slug]
        # The policy's chain named no currently-eligible candidate -- fall
        # through to the deterministic default rather than returning None
        # outright, since the policy narrowing to "nothing" shouldn't make
        # an otherwise-eligible connection unselectable by accident.
    return candidates[0]
