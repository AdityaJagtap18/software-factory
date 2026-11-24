import os

# Deliberately a DIFFERENT database than the dev default
# (postgresql+psycopg2://sf:sf@localhost:5433/software_factory) -- this
# suite truncates every table after every test, so running it against the
# same database a developer is using in the app would silently wipe their
# real accounts/projects/connections. Set SF_TEST_DATABASE_URL to override.
os.environ.setdefault(
    "SF_DATABASE_URL",
    os.environ.get(
        "SF_TEST_DATABASE_URL", "postgresql+psycopg2://sf:sf@localhost:5433/software_factory_test"
    ),
)

import psycopg2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, engine, get_db
from app.main import app


def _ensure_database_exists() -> None:
    url = os.environ["SF_DATABASE_URL"]
    # postgresql+psycopg2://user:pass@host:port/dbname
    without_scheme = url.split("://", 1)[1]
    creds_host, dbname = without_scheme.rsplit("/", 1)
    creds, host = creds_host.split("@", 1)
    user, password = creds.split(":", 1)
    hostname, port = host.split(":", 1)

    conn = psycopg2.connect(dbname="postgres", user=user, password=password, host=hostname, port=port)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        conn.close()

    # P4-3: this suite builds its schema via Base.metadata.create_all(),
    # not Alembic, so the `vector` extension (normally created by the
    # documents migration) needs to be enabled here too.
    conn = psycopg2.connect(dbname=dbname, user=user, password=password, host=hostname, port=port)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    finally:
        conn.close()


@pytest.fixture(scope="session", autouse=True)
def _setup_database():
    _ensure_database_exists()
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    from app.core.rate_limit import reset as reset_rate_limit

    reset_rate_limit()
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
