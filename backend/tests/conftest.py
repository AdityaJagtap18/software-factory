import os

os.environ.setdefault(
    "SF_DATABASE_URL", "postgresql+psycopg2://sf:sf@localhost:5433/software_factory"
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, engine, get_db
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def _setup_database():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    try:
        from app.services.knowledge_graph import _driver

        with _driver().session() as session:
            session.run("MATCH (n) DETACH DELETE n")
    except Exception:
        # Neo4j isn't reachable in every environment this suite runs in;
        # the knowledge-graph tests that need it skip honestly instead.
        pass


TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def client():
    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
