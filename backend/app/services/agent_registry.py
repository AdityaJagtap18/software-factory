"""Phase 2 (P2-4): keeps the `Agent` table in sync with the real adapter
registry (`app/services/agent_runtime/registry.py::all_adapters()`).
Idempotent -- safe to call at every app startup. Never invents an agent
that has no real adapter, and never silently drops one: an adapter that
disappears from the registry is marked `deprecated` on its existing row
rather than deleted, so historical references (once something actually
references an `Agent` row, e.g. a future orchestration assignment) stay
valid."""

from sqlalchemy.orm import Session as DBSession

from app.models.agent import Agent, AgentStatus
from app.services.agent_runtime.registry import all_adapters


def sync_agent_registry(db: DBSession) -> list[Agent]:
    known_slugs = set()
    synced: list[Agent] = []

    for adapter in all_adapters():
        known_slugs.add(adapter.slug)
        capabilities = [{"name": c.name, "state": c.state.value} for c in adapter.capabilities()]
        agent = db.query(Agent).filter_by(slug=adapter.slug).first()
        if agent is None:
            agent = Agent(slug=adapter.slug, name=adapter.display_name)
            db.add(agent)
        agent.name = adapter.display_name
        agent.description = adapter.description
        agent.capabilities = capabilities
        agent.status = AgentStatus.ACTIVE
        synced.append(agent)

    # An adapter that no longer exists in the registry is deprecated, not
    # deleted -- never fabricate its continued existence, but never lose
    # the historical row either.
    stale = db.query(Agent).filter(~Agent.slug.in_(known_slugs)).all() if known_slugs else []
    for agent in stale:
        agent.status = AgentStatus.DEPRECATED

    db.commit()
    return synced
