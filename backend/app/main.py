from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    agent_runtimes,
    approvals,
    auth,
    dashboard,
    documents,
    git_integration,
    knowledge,
    organizations,
    presence,
    projects,
    repository_intelligence,
    tasks,
    workflows,
)
from app.core.config import get_settings

settings = get_settings()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Best-effort: if Neo4j isn't reachable at startup, ensure_schema()
    # itself no-ops honestly (see knowledge_graph.py) rather than blocking
    # the API from starting over an optional dependency.
    from app.services.knowledge_graph import ensure_schema

    ensure_schema()
    yield


app = FastAPI(title="Software Factory API", version="0.1.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(organizations.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(agent_runtimes.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")
app.include_router(workflows.router, prefix="/api/v1")
app.include_router(presence.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(repository_intelligence.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(git_integration.router, prefix="/api/v1")
app.include_router(approvals.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")


@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok"}
