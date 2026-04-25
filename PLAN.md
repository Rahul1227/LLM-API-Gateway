# LLM API Gateway — Project Plan

## Overview

This project builds a locally hosted API gateway that sits in front of multiple LLM providers
(OpenAI, Anthropic, local Ollama). It enforces per-user rate limits using a token-bucket algorithm
backed by Redis, routes requests to the right provider based on the model name, and tracks token
usage and estimated costs per team in PostgreSQL. A Streamlit dashboard surfaces per-team usage,
cost breakdowns, and rate-limit violations.

Everything runs locally on Kubernetes (Minikube). No cloud. No paid services. Docker Compose is
NOT used — Kubernetes is the only orchestration layer.

---

## Problem Statement Coverage

| Requirement | How it's covered |
|---|---|
| Gateway receives requests and applies routing logic | FastAPI `main.py` + `router.py` |
| Rate Limiter enforces per-user/per-team quotas | Token bucket in `rate_limiter.py` backed by Redis |
| Router selects provider based on model and availability | `router.py` maps model name to provider URL |
| Cost Ledger records token usage and estimated cost | `middleware.py` + `db.py` writing to PostgreSQL |
| FastAPI | Gateway service |
| Redis | Rate limiter backend |
| PostgreSQL | Cost ledger |
| Docker | Container image for each service |
| Kubernetes | Local orchestration via Minikube |
| Nginx | K8s Ingress controller routing traffic |
| Streamlit | Admin dashboard |

---

## Tech Stack

| Layer | Tool | Version |
|---|---|---|
| Gateway | FastAPI | latest stable |
| Rate Limiter | Redis | 7-alpine |
| Cost Ledger | PostgreSQL | 15 |
| Dashboard | Streamlit | latest stable |
| Reverse Proxy | Nginx (Minikube Ingress addon) | built-in |
| Orchestration | Kubernetes via Minikube | latest stable |
| Containerization | Docker | latest stable |
| Async HTTP client | httpx | latest stable |
| Async PG driver | asyncpg | latest stable |
| Sync PG driver (dashboard) | psycopg2-binary | latest stable |

---

## Project Structure

```
llm-gateway/
├── gateway/
│   ├── main.py              # FastAPI app entry point
│   ├── router.py            # Provider selection logic
│   ├── rate_limiter.py      # Token-bucket logic using Redis
│   ├── cost_tracker.py      # Token counting and cost estimation
│   ├── middleware.py        # Request/response middleware
│   ├── models.py            # Pydantic request/response schemas
│   ├── config.py            # Environment variables and constants
│   ├── db.py                # PostgreSQL connection and queries
│   ├── requirements.txt
│   └── Dockerfile
│
├── dashboard/
│   ├── app.py               # Streamlit dashboard
│   ├── queries.py           # PostgreSQL queries for dashboard
│   ├── requirements.txt
│   └── Dockerfile
│
├── k8s/
│   ├── namespace.yaml
│   ├── configmap.yaml       # Non-secret config values
│   ├── secrets.yaml         # API keys — gitignored, never committed
│   ├── redis/
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   ├── postgres/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   └── pvc.yaml         # Persistent volume so data survives pod restarts
│   ├── gateway/
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   ├── dashboard/
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   └── ingress.yaml         # Nginx ingress routing rules
│
├── sql/
│   └── init.sql             # Table creation scripts
│
├── tests/
│   ├── test_rate_limiter.py
│   ├── test_router.py
│   └── test_cost_tracker.py
│
├── .env.example
├── .gitignore               # Must include: secrets.yaml, .env, __pycache__
├── PLAN.md
└── README.md
```

**There is no `docker-compose.yaml` in this project.** If one exists, delete it. Kubernetes is
the only way to run this project.

---

## Architecture

```
Client Request
     │
     ▼
Nginx Ingress (port 80)  ← Minikube ingress addon
     │
     ├──► /v1/*       ──► gateway-service:8000 (FastAPI)
     │                          │
     │               ┌──────────┼───────────────┐
     │               ▼          ▼               ▼
     │            Redis       Router        PostgreSQL
     │          (rate limit)  (picks        (logs usage
     │                         backend)      and cost)
     │               │
     │               ▼
     │    LLM Backend
     │    ├── Ollama     (http://host.minikube.internal:11434)
     │    ├── OpenAI     (https://api.openai.com)
     │    └── Anthropic  (https://api.anthropic.com)
     │
     └──► /dashboard  ──► dashboard-service:8501 (Streamlit)
```

---

## Services

### 1. Gateway (FastAPI)

**`gateway/config.py`**
- Reads all values from environment variables using `os.getenv`.
- Exports typed constants:
  - `REDIS_URL: str`
  - `POSTGRES_DSN: str`
  - `OLLAMA_BASE_URL: str`
  - `OPENAI_API_KEY: str`
  - `ANTHROPIC_API_KEY: str`
  - `RATE_LIMIT_REQUESTS: int`
  - `RATE_LIMIT_WINDOW_SECONDS: int`
- Exports `TOKEN_COSTS` dict:
  ```python
  TOKEN_COSTS = {
      "gpt-4o":            (0.005,  0.015),
      "gpt-3.5-turbo":     (0.0005, 0.0015),
      "claude-3-5-sonnet": (0.003,  0.015),
  }
  # Ollama models default to (0.0, 0.0)
  ```

**`gateway/models.py`**
- `ChatMessage`: fields `role: str`, `content: str`.
- `ChatRequest`: fields `model: str`, `messages: list[ChatMessage]`, optional `stream: bool`.
- `ChatResponse`: wraps upstream JSON as-is using `dict`.
- All fields use snake_case.

**`gateway/router.py`**
- `pick_provider(model_name: str) -> str`
- Routing rules:
  - `gpt-*` → `https://api.openai.com/v1/chat/completions`
  - `claude-*` → `https://api.anthropic.com/v1/messages`
  - anything else → `{OLLAMA_BASE_URL}/api/chat`
- Raises `HTTPException(400, "Unknown model")` for no match.

**`gateway/rate_limiter.py`**
- `check_rate_limit(api_key: str, redis_client) -> None`
- Token bucket stored as a Redis hash at key `rate_limit:{api_key}`.
- Hash fields: `tokens` (float as string), `last_refill` (Unix timestamp float as string).
- On each call:
  1. Get current time.
  2. Read `tokens` and `last_refill` from Redis (create bucket with full capacity if missing).
  3. Calculate `elapsed = now - last_refill`.
  4. Calculate `refill = elapsed * (RATE_LIMIT_REQUESTS / RATE_LIMIT_WINDOW_SECONDS)`.
  5. Add refill to tokens, cap at `RATE_LIMIT_REQUESTS`.
  6. If `tokens < 1`: log violation to PostgreSQL, raise `HTTPException(429, "Rate limit exceeded")`.
  7. Deduct 1 token, write updated `tokens` and `last_refill` back using a Redis pipeline.

**`gateway/cost_tracker.py`**
- `estimate_cost(model_name: str, prompt_tokens: int, completion_tokens: int) -> float`
- Looks up `TOKEN_COSTS.get(model_name, (0.0, 0.0))`.
- Returns `round((prompt_cost * prompt_tokens + completion_cost * completion_tokens) / 1000, 6)`.

**`gateway/db.py`**
- `init_db_pool() -> asyncpg.Pool` — creates connection pool from `POSTGRES_DSN`.
- `log_request(pool, api_key, team_id, model_name, prompt_tokens, completion_tokens, cost_usd, latency_ms, status_code) -> None`
  — inserts one row into `request_logs`.
- `log_violation(pool, api_key, team_id) -> None`
  — inserts one row into `rate_limit_violations`.
- All functions are async.

**`gateway/middleware.py`**
- `CostTrackingMiddleware(BaseHTTPMiddleware)`
- `async def dispatch(request, call_next)`:
  1. Record `start_time = time.monotonic()`.
  2. Await `call_next(request)` to get `response`.
  3. Read response body, parse JSON.
  4. Extract `usage.prompt_tokens`, `usage.completion_tokens` from response.
  5. Extract `model` from response.
  6. Call `estimate_cost(...)`.
  7. Call `log_request(...)`.
  8. Calculate `latency_ms = int((time.monotonic() - start_time) * 1000)`.
  9. Re-stream body so the client still receives it intact.

**`gateway/main.py`**
- Creates FastAPI app.
- Adds `CostTrackingMiddleware`.
- On startup: initializes Redis client and asyncpg pool, stores on `app.state`.
- On shutdown: closes pool.
- `POST /v1/chat/completions`:
  1. Extract `api_key` from `Authorization: Bearer <key>` header. Return `401` if missing.
  2. Extract `team_id` from `X-Team-ID` header. Default to `"default"` if missing.
  3. Call `check_rate_limit(api_key, app.state.redis)`.
  4. Call `pick_provider(request.model)` to get `provider_url`.
  5. Forward full request body to `provider_url` using `httpx.AsyncClient`.
  6. Return upstream response.
- `GET /health`: returns `{"status": "ok", "redis": "ok", "db": "ok"}` after pinging both.

---

### 2. Cost Ledger (PostgreSQL)

**`sql/init.sql`**

```sql
-- Creating the teams table
CREATE TABLE IF NOT EXISTS teams (
    team_id    VARCHAR(64)  PRIMARY KEY,
    team_name  VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ  DEFAULT NOW()
);

-- Creating the API keys table
CREATE TABLE IF NOT EXISTS api_keys (
    api_key    VARCHAR(128) PRIMARY KEY,
    team_id    VARCHAR(64)  REFERENCES teams(team_id),
    created_at TIMESTAMPTZ  DEFAULT NOW()
);

-- Creating the request logs table
CREATE TABLE IF NOT EXISTS request_logs (
    id                BIGSERIAL    PRIMARY KEY,
    api_key           VARCHAR(128),
    team_id           VARCHAR(64),
    model_name        VARCHAR(64),
    prompt_tokens     INT,
    completion_tokens INT,
    total_tokens      INT GENERATED ALWAYS AS (prompt_tokens + completion_tokens) STORED,
    cost_usd          NUMERIC(12, 6),
    latency_ms        INT,
    status_code       INT,
    created_at        TIMESTAMPTZ  DEFAULT NOW()
);

-- Creating the rate limit violations table
CREATE TABLE IF NOT EXISTS rate_limit_violations (
    id         BIGSERIAL    PRIMARY KEY,
    api_key    VARCHAR(128),
    team_id    VARCHAR(64),
    created_at TIMESTAMPTZ  DEFAULT NOW()
);

-- Creating indexes for common dashboard query patterns
CREATE INDEX IF NOT EXISTS idx_logs_team_id    ON request_logs(team_id);
CREATE INDEX IF NOT EXISTS idx_logs_created_at ON request_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_logs_api_key    ON request_logs(api_key);
CREATE INDEX IF NOT EXISTS idx_violations_team ON rate_limit_violations(team_id);
```

---

### 3. Admin Dashboard (Streamlit)

**`dashboard/queries.py`**
- All functions take a `psycopg2` connection and return a `pandas.DataFrame`.
- `get_team_usage(conn, start_date, end_date)` — total tokens and cost per team.
- `get_cost_by_model(conn, team_id, start_date, end_date)` — cost per model for a team.
- `get_request_volume(conn, interval)` — request count bucketed by hour or day.
- `get_violations(conn, limit)` — most recent rate-limit violations with team and timestamp.

**`dashboard/app.py`**
- Connects to PostgreSQL using `psycopg2` via `POSTGRES_DSN` env var.
- `st.sidebar`: date range picker, team selector.
- Section 1 — **Team Usage**: total tokens and cost per team as a table + bar chart.
- Section 2 — **Cost Breakdown**: cost per model per team as a stacked bar chart.
- Section 3 — **Request Volume**: requests over time as a line chart.
- Section 4 — **Rate Limit Violations**: paginated table of recent violations.
- Auto-refreshes every 30 seconds using `st.rerun()`.

---

### 4. Kubernetes Manifests

#### namespace.yaml
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: llm-gateway
```

#### configmap.yaml
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: gateway-config
  namespace: llm-gateway
data:
  RATE_LIMIT_REQUESTS: "100"
  RATE_LIMIT_WINDOW_SECONDS: "60"
  OLLAMA_BASE_URL: "http://host.minikube.internal:11434"
  REDIS_URL: "redis://redis-service:6379"
  POSTGRES_DSN: "postgresql://gateway:gateway@postgres-service:5432/gatewaydb"
```

> **Linux users:** `host.minikube.internal` does not resolve on Linux with the Docker driver.
> Replace with `172.17.0.1` (default Docker bridge IP) or find the real IP by running:
> `minikube ssh 'grep host.minikube.internal /etc/hosts'`

#### secrets.yaml (gitignored — never commit this)
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: gateway-secrets
  namespace: llm-gateway
type: Opaque
stringData:
  OPENAI_API_KEY: "your-key-here"
  ANTHROPIC_API_KEY: "your-key-here"
```

#### k8s/redis/deployment.yaml
- Image: `redis:7-alpine`
- `imagePullPolicy: IfNotPresent`
- Replicas: 1
- No persistence needed — rate limit state is ephemeral, a restart just resets buckets.
- Port: 6379

#### k8s/redis/service.yaml
- Type: `ClusterIP`
- Name: `redis-service`
- Port: 6379

#### k8s/postgres/pvc.yaml
- `storageClassName: standard` (Minikube default)
- `storage: 1Gi`
- AccessMode: `ReadWriteOnce`

#### k8s/postgres/deployment.yaml
- Image: `postgres:15`
- `imagePullPolicy: IfNotPresent`
- Env: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` from ConfigMap.
- Volume mounts:
  - PVC → `/var/lib/postgresql/data`
  - `init-sql` ConfigMap → `/docker-entrypoint-initdb.d/init.sql` (runs once on first start)
- Port: 5432

#### k8s/postgres/service.yaml
- Type: `ClusterIP`
- Name: `postgres-service`
- Port: 5432

#### k8s/gateway/deployment.yaml
- Image: `llm-gateway:latest`
- **`imagePullPolicy: Never`** — required for Minikube to use the locally loaded image instead of pulling from Docker Hub.
- Replicas: 2
- EnvFrom: `gateway-config` ConfigMap + `gateway-secrets` Secret
- Liveness probe: `GET /health` every 15s
- Resource limits: `cpu: 500m`, `memory: 256Mi`
- Port: 8000

#### k8s/gateway/service.yaml
- Type: `ClusterIP`
- Name: `gateway-service`
- Port: 8000

#### k8s/dashboard/deployment.yaml
- Image: `llm-dashboard:latest`
- **`imagePullPolicy: Never`** — same reason as gateway.
- Replicas: 1
- EnvFrom: `gateway-config` ConfigMap + `gateway-secrets` Secret
- Port: 8501

#### k8s/dashboard/service.yaml
- Type: `ClusterIP`
- Name: `dashboard-service`
- Port: 8501

#### k8s/ingress.yaml
- Ingress class: `nginx`
- Host: `llm-gateway.local`
- Rules:
  - `/v1/` → `gateway-service:8000`
  - `/dashboard` → `dashboard-service:8501`
- Annotation: `nginx.ingress.kubernetes.io/rewrite-target: /`

---

## Coding Conventions

### Comments
- Every inline comment starts with an -ing verb.
- Comments describe intent, not what the line does mechanically.
- No obvious comments.

```python
# Checking if the bucket has enough tokens before proceeding
if bucket_tokens < 1:
    raise HTTPException(status_code=429, detail="Rate limit exceeded")

# Calculating elapsed time to determine how many tokens to refill
elapsed = current_time - last_refill

# Capping refilled tokens at bucket capacity
new_tokens = min(bucket_tokens + refill_amount, RATE_LIMIT_REQUESTS)
```

### Variable Names
- Descriptive. No single-letter names, no `tmp`, `data`, `res`, `d`, `r`.
- Good: `prompt_tokens`, `completion_tokens`, `rate_limit_window`, `provider_url`,
  `cost_usd`, `api_key`, `team_id`, `bucket_tokens`, `elapsed_seconds`, `refill_rate`.

### Functions
- One responsibility per function.
- Full type hints on every signature.
- Async for all FastAPI routes and database calls.

### Error Handling
- Use `HTTPException` with specific status codes and human-readable detail strings.
- Use `logging.error(...)` not `print(...)`.
- Never catch and swallow exceptions silently.

### Secrets and Config
- No hardcoded URLs, keys, or credentials anywhere.
- Everything goes through `config.py` via `os.getenv`.

---

## .gitignore (required entries)

```
k8s/secrets.yaml
.env
*.pyc
__pycache__/
.pytest_cache/
```

---

## Local Setup (Minikube)

### Prerequisites
- Docker (running)
- Minikube
- kubectl
- Ollama running natively on host at port 11434

### Full Deployment Steps

```bash
# Starting Minikube with enough resources
minikube start --driver=docker --memory=4096 --cpus=2

# Enabling Nginx ingress addon
minikube addons enable ingress

# Creating namespace
kubectl apply -f k8s/namespace.yaml

# Applying config and secrets (copy .env.example, fill values, save as k8s/secrets.yaml)
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml

# Deploying Redis and Postgres
kubectl apply -f k8s/redis/
kubectl apply -f k8s/postgres/

# Waiting for Postgres to be ready before deploying gateway
kubectl wait --for=condition=ready pod -l app=postgres -n llm-gateway --timeout=60s

# Building gateway image and loading into Minikube
docker build -t llm-gateway:latest ./gateway
minikube image load llm-gateway:latest

# Building dashboard image and loading into Minikube
docker build -t llm-dashboard:latest ./dashboard
minikube image load llm-dashboard:latest

# Deploying gateway and dashboard
kubectl apply -f k8s/gateway/
kubectl apply -f k8s/dashboard/

# Applying ingress rules
kubectl apply -f k8s/ingress.yaml

# Adding local DNS entry (run once)
echo "$(minikube ip) llm-gateway.local" | sudo tee -a /etc/hosts
```

### Accessing Services
- Gateway: `http://llm-gateway.local/v1/chat/completions`
- Dashboard: `http://llm-gateway.local/dashboard`
- Health check: `http://llm-gateway.local/health`

### Rebuilding After Code Changes

```bash
docker build -t llm-gateway:latest ./gateway
minikube image load llm-gateway:latest
kubectl rollout restart deployment/gateway-deployment -n llm-gateway
```

---

## Token Cost Reference

| Model | Prompt per 1K tokens | Completion per 1K tokens |
|---|---|---|
| gpt-4o | $0.005 | $0.015 |
| gpt-3.5-turbo | $0.0005 | $0.0015 |
| claude-3-5-sonnet | $0.003 | $0.015 |
| ollama/* (any local model) | $0.000 | $0.000 |

---

## Testing

```bash
# Running all tests
python -m pytest tests/ -v

# Sending a test request via Ollama (free, no API key needed)
curl -X POST http://llm-gateway.local/v1/chat/completions \
  -H "Authorization: Bearer test-api-key-1" \
  -H "X-Team-ID: team-alpha" \
  -H "Content-Type: application/json" \
  -d '{"model": "llama3", "messages": [{"role": "user", "content": "Hello"}]}'

# Triggering rate limit (last 10 requests should return 429)
for i in $(seq 1 110); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST http://llm-gateway.local/v1/chat/completions \
    -H "Authorization: Bearer test-api-key-1" \
    -H "X-Team-ID: team-alpha" \
    -H "Content-Type: application/json" \
    -d '{"model": "llama3", "messages": [{"role": "user", "content": "ping"}]}'
done
```

---

## What the Agent Must Do

When analyzing and building this project:

1. **Delete `docker-compose.yaml` if it exists.** This project uses Kubernetes only.
2. Read every existing file and check it against this plan before making any changes.
3. Rename variables that do not follow the naming conventions above.
4. Fix all comments — every inline comment must start with an -ing verb.
5. Set `imagePullPolicy: Never` on gateway and dashboard K8s deployments. Without this, Minikube will try to pull from Docker Hub and fail.
6. Set `imagePullPolicy: IfNotPresent` on Redis and Postgres deployments (these pull from Docker Hub).
7. Make sure `init.sql` exactly matches the schema defined in this plan.
8. Create `.gitignore` if it does not exist. It must include `k8s/secrets.yaml` and `.env`.
9. Do not change the API contract. `POST /v1/chat/completions` must stay OpenAI-compatible.
10. Keep each file single-purpose. Do not merge logic across files.
11. The `X-Team-ID` header must be extracted in `main.py` and passed all the way through to `db.py`.
12. The Ollama URL must come from `config.py` only, never hardcoded anywhere.
13. Document the Linux `host.minikube.internal` → `172.17.0.1` fallback in README.