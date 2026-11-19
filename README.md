# Software Factory

An AI-powered software engineering platform: Angular frontend, FastAPI +
PostgreSQL backend. See [`docs/implementation/`](docs/implementation/) for
the implementation plan and decisions, and [`backend/README.md`](backend/README.md)
for backend-only local development.

## Running the full stack

```bash
docker compose up -d --build
```

Builds and starts all three services:

| Service    | Container port | Host port | Notes |
|------------|-----------------|-----------|-------|
| `postgres` | 5432            | 5433      | 5432 is often already taken by another local Postgres instance. |
| `backend`  | 8000            | 8020      | Runs `alembic upgrade head` then `uvicorn`; its healthcheck gates `frontend`'s startup. |
| `frontend` | 80              | 4300      | Nginx serving the production Angular build; proxies `/api/` to `backend:8000` inside the Docker network, so the browser only ever talks to one origin. |

Open `http://localhost:4300` — register an account, create an organization,
create a project.

The production build uses `frontend/src/environments/environment.prod.ts`
(`apiBaseUrl: '/api/v1'`, relative — proxied by Nginx) instead of
`environment.ts`'s absolute `http://localhost:8010` used by `ng serve`, via
an Angular `fileReplacements` config in `angular.json`.

```bash
docker compose logs -f backend    # or frontend / postgres
docker compose down               # stop (add -v to also drop the Postgres volume)
```

## Local (non-Docker) development

- Backend: see [`backend/README.md`](backend/README.md) (`uvicorn` on
  `:8010`, Postgres via `docker compose up -d postgres` on `:5433`).
- Frontend: `cd frontend && npm start` (`ng serve` on `:4200`, pointed at
  `http://localhost:8010/api/v1` by `environment.ts`).
