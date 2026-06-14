# Amazon Edge-Return — Backend

FastAPI (async ASGI) backend for the Amazon Edge-Return prototype.

## Stack

- FastAPI + Uvicorn
- SQLAlchemy (async) + asyncpg (PostgreSQL)
- redis-py (geospatial demand index)
- Pydantic / pydantic-settings
- Hypothesis + pytest (property-based + unit tests)

## Package layout

```
backend/
  app/
    api/        # FastAPI routers (transport layer)
    services/   # business logic + pure decision cores
    core/       # configuration and cross-cutting concerns
    models/     # SQLAlchemy ORM models
    db/         # engine/session + Redis gateway
    main.py     # FastAPI app factory + /health route
  tests/        # unit + property-based tests
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env          # then edit values
```

## Configuration

Settings are read from environment variables (or `.env`):

| Variable         | Purpose                                              |
| ---------------- | ---------------------------------------------------- |
| `DB_URL`         | Async SQLAlchemy/asyncpg PostgreSQL URL              |
| `REDIS_URL`      | Redis URL for the geospatial demand index            |
| `SESSION_SECRET` | Secret used to sign HTTP-only session cookies        |
| `CORS_ORIGINS`   | Comma-separated allowed origins (Next.js dev client) |

## Run

```bash
uvicorn app.main:app --reload
```

Health check: `GET http://localhost:8000/health` → `{"status": "ok"}`.

## Test

```bash
pytest
```
