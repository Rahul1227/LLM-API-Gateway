# LLM API Gateway

A local API gateway for LLM providers. Sits in front of Ollama, OpenAI, and Anthropic. Enforces
per-user rate limits via Redis, logs token usage and cost to PostgreSQL, and shows everything on
a Streamlit dashboard.

Runs entirely on Kubernetes (Minikube). No Docker Compose. No cloud.

---

## What's Inside

```
gateway/      FastAPI gateway service
dashboard/    Streamlit dashboard
k8s/          Kubernetes manifests
sql/          PostgreSQL schema
tests/        Unit tests
```

---

## Before You Start

You need these installed:

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Minikube](https://minikube.sigs.k8s.io/docs/start/)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)
- [Python 3.10+](https://www.python.org/downloads/)
- [Ollama](https://ollama.com/) — for free local LLM testing

Verify Docker is running before anything else. Minikube won't start without it.

---

## Step 0 — Set Up Python Virtual Environment

Do this once before running tests or any local Python tooling.

**macOS / Linux:**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r gateway/requirements.txt
pip install -r dashboard/requirements.txt
pip install pytest
```

**Windows (PowerShell):**

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r gateway/requirements.txt
pip install -r dashboard/requirements.txt
pip install pytest
```

You should see `(venv)` in your terminal prompt. All `python` and `pytest` commands below assume
the venv is active. If you close the terminal, re-activate with `source venv/bin/activate`
(macOS/Linux) or `.\venv\Scripts\Activate.ps1` (Windows).

---

## Step 1 — Pull the Ollama Model

Ollama runs natively on your machine (not inside Kubernetes). Start it and pull the model:

```bash
ollama serve
```

Open a second terminal and pull the model:

```bash
ollama pull llama3.2:1b
```

Verify it works:

```bash
curl http://localhost:11434/api/tags
```

You should see `llama3.2:1b` in the list. Keep `ollama serve` running in the background for the
rest of setup.

---

## Step 2 — Start Minikube

```bash
minikube start --driver=docker --memory=4096 --cpus=2
minikube addons enable ingress
```

Wait for the ingress addon to be ready:

```bash
kubectl wait --namespace ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=120s
```

---

## Step 3 — Create the Secrets File

```bash
cp k8s/secrets.example.yaml k8s/secrets.yaml
```

**Windows (PowerShell):**

```powershell
Copy-Item k8s/secrets.example.yaml k8s/secrets.yaml
```

Open `k8s/secrets.yaml`. For Ollama-only testing you can leave the API keys as placeholders.
If you want to test OpenAI or Anthropic, add real keys here.

> `k8s/secrets.yaml` is gitignored. Never commit it.

---

## Step 4 — Apply Namespace, Config, and Secrets

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml
```

Verify they applied:

```bash
kubectl get configmap -n llm-gateway
kubectl get secret -n llm-gateway
```

---

## Step 5 — Start Redis and PostgreSQL

```bash
kubectl apply -f k8s/redis/
kubectl apply -f k8s/postgres/
```

Wait for Postgres to be fully ready before moving on — the gateway will fail to start if Postgres
isn't up:

```bash
kubectl wait --for=condition=ready pod -l app=postgres -n llm-gateway --timeout=90s
```

Check both are running:

```bash
kubectl get pods -n llm-gateway
```

Both pods should show `Running` and `1/1` under READY.

---

## Step 6 — Build and Load Images

Minikube has its own internal Docker registry. You need to build images locally and load them
into Minikube — they won't be pulled from Docker Hub.

```bash
docker build -t llm-gateway:latest ./gateway
minikube image load llm-gateway:latest

docker build -t llm-dashboard:latest ./dashboard
minikube image load llm-dashboard:latest
```

Verify the images are available inside Minikube:

for cmd
```bash
minikube image ls | findstr llm
```
for linux
```bash
minikube image ls | grep llm
```

You should see `llm-gateway:latest` and `llm-dashboard:latest`.

---

## Step 7 — Deploy Gateway, Dashboard, and Ingress

```bash
kubectl apply -f k8s/gateway/
kubectl apply -f k8s/dashboard/
kubectl apply -f k8s/ingress.yaml
```

Wait for everything to come up:

```bash
kubectl wait --for=condition=ready pod -l app=gateway -n llm-gateway --timeout=60s
kubectl wait --for=condition=ready pod -l app=dashboard -n llm-gateway --timeout=60s
```

Check all pods one more time:

```bash
kubectl get pods -n llm-gateway
```

All pods — redis, postgres, gateway (x2), dashboard — should be `Running`.

---

## Step 8 — Expose the Gateway Locally

On macOS/Linux, use the Minikube ingress hostname.

Get your Minikube IP:

```bash
minikube ip
```

Add this line to your hosts file, replacing `<MINIKUBE_IP>` with the output above:

```
<MINIKUBE_IP>  llm-gateway.local
```

**macOS / Linux** — edit `/etc/hosts`:

```bash
echo "$(minikube ip) llm-gateway.local" | sudo tee -a /etc/hosts
```

Verify that the local DNS name resolves:

```bash
ping llm-gateway.local
```

The output should show `llm-gateway.local` resolving to your Minikube IP. It is okay if the
ping request times out; the important part is that the hostname resolves to the correct IP.

**Windows with Docker Desktop** — skip the hosts-file step and use port forwarding. This avoids
Minikube Docker-driver networking issues where `llm-gateway.local` resolves correctly but
`192.168.49.2:80` times out.

Open a terminal and keep this command running:

```powershell
kubectl -n llm-gateway port-forward svc/gateway-service 8000:8000
```

Use this gateway URL on Windows:

```text
http://127.0.0.1:8000
```

For the dashboard, open a second terminal and keep this command running:

```powershell
kubectl -n llm-gateway port-forward svc/dashboard-service 8501:8501
```

Use this dashboard URL on Windows:

```text
http://127.0.0.1:8501
```

---

## Verifying Everything Works

### Health Check

**macOS / Linux:**

```bash
curl http://llm-gateway.local/health
```

**Windows:**

```powershell
curl.exe http://127.0.0.1:8000/health
```

Expected:

```json
{"status": "ok", "redis": "ok", "db": "ok"}
```

If macOS/Linux gets a connection error, check that the ingress pod is running:

```bash
kubectl get pods -n ingress-nginx
```

If Windows says port `8000` is already in use, a port-forward is probably already running. Test
`curl.exe http://127.0.0.1:8000/health` directly, or use another local port:

```powershell
kubectl -n llm-gateway port-forward svc/gateway-service 8080:8000
```

Then test from another terminal:

```powershell
curl.exe http://127.0.0.1:8080/health
```

---

### Send a Chat Request (Ollama)

```bash
curl -X POST http://llm-gateway.local/v1/chat/completions \
  -H "Authorization: Bearer test-api-key-1" \
  -H "X-Team-ID: team-alpha" \
  -H "Content-Type: application/json" \
  -d '{"model": "llama3.2:1b", "messages": [{"role": "user", "content": "Hello"}]}'
```

**Windows (PowerShell):**

```powershell
curl.exe -X POST http://127.0.0.1:8000/v1/chat/completions `
  -H "Authorization: Bearer test-api-key-1" `
  -H "X-Team-ID: team-alpha" `
  -H "Content-Type: application/json" `
  -d '{\"model\":\"llama3.2:1b\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}]}'
```

You should get a JSON response from Ollama with a `choices` array.

---

### Confirm Usage Was Logged in PostgreSQL
Powershell
```bash
kubectl exec -n llm-gateway deployment/postgres -- psql -U gateway -d gatewaydb -c "SELECT team_id, model_name, prompt_tokens, completion_tokens, cost_usd, status_code, created_at FROM request_logs ORDER BY created_at DESC LIMIT 5;"
```

You should see a row with `team-alpha` and `llama3.2:1b`.

---

### Test Rate Limiting

The default limit is 100 requests per 60 seconds. Send 110 — the last batch should return `429`.

**macOS / Linux:**

```bash
for i in $(seq 1 110); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST http://llm-gateway.local/v1/chat/completions \
    -H "Authorization: Bearer test-api-key-1" \
    -H "X-Team-ID: team-alpha" \
    -H "Content-Type: application/json" \
    -d '{"model": "llama3.2:1b", "messages": [{"role": "user", "content": "ping"}]}'
done
```

**Windows (PowerShell):**

```powershell
1..110 | ForEach-Object { curl.exe -s -o NUL -w "%{http_code}`n" -X POST http://127.0.0.1:8000/v1/chat/completions -H "Authorization: Bearer test-api-key-1" -H "X-Team-ID: team-alpha" -H "Content-Type: application/json" -d '{\"model\":\"llama3.2:1b\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}]}' }
```

After ~100 requests you should start seeing `429` responses.

Verify violations were recorded:

```bash
kubectl exec -n llm-gateway deployment/postgres -- psql -U gateway -d gatewaydb -c "SELECT team_id, api_key, created_at FROM rate_limit_violations ORDER BY created_at DESC LIMIT 5;"
```

---

### Open the Dashboard

Go to:

**macOS / Linux:**

```
http://llm-gateway.local/dashboard
```

**Windows:**

```
http://127.0.0.1:8501
```

You should see four sections: Team Usage, Cost Breakdown, Request Volume, and Rate Limit
Violations. The dashboard auto-refreshes every 30 seconds.

---

## Run Unit Tests

Make sure your venv is active (you should see `(venv)` in your prompt), then:

```bash
python -m pytest tests/ -v
```

**Windows (PowerShell) if `python` isn't on PATH:**

```powershell
.\venv\Scripts\python.exe -m pytest tests/ -v
```

All 7 tests should pass.

---

## Rebuild After Code Changes

If you edit gateway or dashboard code, rebuild and reload:

**Gateway:**

```bash
docker build -t llm-gateway:latest ./gateway
minikube image load llm-gateway:latest
kubectl rollout restart deployment/gateway -n llm-gateway
```

**Dashboard:**

```bash
docker build -t llm-dashboard:latest ./dashboard
minikube image load llm-dashboard:latest
kubectl rollout restart deployment/dashboard -n llm-gateway
```

Watch the rollout:

```bash
kubectl rollout status deployment/gateway -n llm-gateway
```

---

## Troubleshooting

**Pods stuck in `ImagePullBackOff`**

The image wasn't loaded into Minikube. Run:

```bash
minikube image load llm-gateway:latest
kubectl rollout restart deployment/gateway -n llm-gateway
```

**`llm-gateway.local` not resolving on macOS/Linux**

Your hosts file entry is missing or wrong. Double-check the IP with `minikube ip` and that the
line in `/etc/hosts` matches exactly.

**Windows cannot connect to `llm-gateway.local`**

Use port forwarding instead of the Minikube ingress IP:

```powershell
kubectl -n llm-gateway port-forward svc/gateway-service 8000:8000
```

Then test from another terminal:

```powershell
curl.exe http://127.0.0.1:8000/health
```

If port `8000` is already in use, the port-forward may already be running. Use
`curl.exe http://127.0.0.1:8000/health`, or forward a different local port:

```powershell
kubectl -n llm-gateway port-forward svc/gateway-service 8080:8000
```

Then test from another terminal:

```powershell
curl.exe http://127.0.0.1:8080/health
```

**Ollama unreachable from inside Minikube (Linux)**

`host.minikube.internal` doesn't resolve on Linux with the Docker driver. Edit
`k8s/configmap.yaml` and change `OLLAMA_BASE_URL` to:

```
http://172.17.0.1:11434
```

Then reapply and restart:

```bash
kubectl apply -f k8s/configmap.yaml
kubectl rollout restart deployment/gateway -n llm-gateway
```

**Postgres not ready**

Check its logs:

```bash
kubectl logs -n llm-gateway deployment/postgres
```

If the init SQL failed, delete the postgres pod so it restarts and reruns the init script:

```bash
kubectl delete pod -n llm-gateway -l app=postgres
```

**General pod debugging:**

```bash
kubectl get pods -n llm-gateway
kubectl describe pod <pod-name> -n llm-gateway
kubectl logs -n llm-gateway deployment/gateway
kubectl logs -n llm-gateway deployment/dashboard
kubectl logs -n llm-gateway deployment/redis
```

---

## Useful Commands

```bash
# Checking all resources in the namespace
kubectl get all -n llm-gateway

# Checking ingress routing
kubectl get ingress -n llm-gateway

# Watching pods in real time
kubectl get pods -n llm-gateway -w

# Getting a shell inside the gateway pod
kubectl exec -it -n llm-gateway deployment/gateway -- /bin/bash
```

---

## Stop Everything

Remove all project resources but keep Minikube running:

```bash
kubectl delete namespace llm-gateway
```

Or stop Minikube entirely:

```bash
minikube stop
```

To also free up disk space from images:

```bash
minikube delete
```
