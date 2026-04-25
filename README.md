# LLM API Gateway

A local API gateway for LLM providers. It sits in front of Ollama, OpenAI, and Anthropic,
enforces per-user rate limits with Redis, logs token usage and cost to PostgreSQL, and shows
everything in a Streamlit dashboard.

This setup is written for Windows with Docker Desktop, Minikube, Kubernetes, and Ollama.

---

## What's Inside

```text
gateway/      FastAPI gateway service
dashboard/    Streamlit dashboard
k8s/          Kubernetes manifests
sql/          PostgreSQL schema
tests/        Unit tests
```

---

## Before You Start

Install these first:

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Minikube](https://minikube.sigs.k8s.io/docs/start/)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)
- [Python 3.10+](https://www.python.org/downloads/)
- [Ollama](https://ollama.com/)

Make sure Docker Desktop is running before starting Minikube.

---

## Step 0 - Set Up Python

Open PowerShell in the project folder:

```powershell
python -m venv venv; .\venv\Scripts\Activate.ps1; pip install -r gateway/requirements.txt; pip install -r dashboard/requirements.txt; pip install pytest
```

If you close the terminal later, reactivate the environment with:

```powershell
.\venv\Scripts\Activate.ps1
```

---

## Step 1 - Start Ollama

Start Ollama if it is not already running:

```powershell
ollama serve
```

If you see a port `11434` already-in-use message, Ollama is already running. Open another terminal
and pull the lightweight model:

```powershell
ollama pull llama3.2:1b
```

Verify Ollama:

```powershell
curl.exe http://localhost:11434/api/tags
```

You should see `llama3.2:1b` in the response.

---

## Step 2 - Start Minikube

```powershell
minikube start --driver=docker --memory=4096 --cpus=2; minikube addons enable ingress; kubectl wait --namespace ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=120s
```

---

## Step 3 - Create Secrets

```powershell
Copy-Item k8s/secrets.example.yaml k8s/secrets.yaml
```

For Ollama-only testing, you can leave the API keys as placeholders. If you want to test OpenAI
or Anthropic, edit `k8s/secrets.yaml` and add real keys.

`k8s/secrets.yaml` is gitignored. Do not commit it.

---

## Step 4 - Apply Config

```powershell
kubectl apply -f k8s/namespace.yaml; kubectl apply -f k8s/configmap.yaml; kubectl apply -f k8s/secrets.yaml
```

Verify:

```powershell
kubectl get configmap -n llm-gateway; kubectl get secret -n llm-gateway
```

---

## Step 5 - Start Redis and PostgreSQL

```powershell
kubectl apply -f k8s/redis/; kubectl apply -f k8s/postgres/; kubectl wait --for=condition=ready pod -l app=postgres -n llm-gateway --timeout=90s; kubectl get pods -n llm-gateway
```

Redis and PostgreSQL should show `Running`.

---

## Step 6 - Build and Load Images

Minikube uses its own internal image store, so build the images locally and load them into
Minikube:

```powershell
docker build -t llm-gateway:latest ./gateway; minikube image load llm-gateway:latest; docker build -t llm-dashboard:latest ./dashboard; minikube image load llm-dashboard:latest
```

Verify:

```powershell
minikube image ls | findstr llm
```

You should see `llm-gateway:latest` and `llm-dashboard:latest`.

---

## Step 7 - Deploy the App

```powershell
kubectl apply -f k8s/gateway/; kubectl apply -f k8s/dashboard/; kubectl apply -f k8s/ingress.yaml; kubectl wait --for=condition=ready pod -l app=gateway -n llm-gateway --timeout=60s; kubectl wait --for=condition=ready pod -l app=dashboard -n llm-gateway --timeout=60s; kubectl get pods -n llm-gateway
```

All pods should show `Running`.

---

## Step 8 - Expose the App on Windows

On Windows with Docker Desktop, use port forwarding instead of `llm-gateway.local`.

Open one terminal and keep this running:

```powershell
kubectl -n llm-gateway port-forward svc/gateway-service 8000:8000
```

Your gateway URL is:

```text
http://127.0.0.1:8000
```

For the dashboard, open a second terminal and keep this running:

```powershell
kubectl -n llm-gateway port-forward svc/dashboard-service 8501:8501
```

Your dashboard URL is:

```text
http://127.0.0.1:8501
```

If port `8000` is already in use, a port-forward may already be running. You can test it directly
or use another local port:

```powershell
kubectl -n llm-gateway port-forward svc/gateway-service 8080:8000
```

Then use `http://127.0.0.1:8080` for gateway requests.

---

## Verify Everything

### Health Check

Run this from a separate terminal while the gateway port-forward is running:

```powershell
curl.exe http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"ok","redis":"ok","db":"ok"}
```

---

### Send a Chat Request

```powershell
curl.exe -X POST http://127.0.0.1:8000/v1/chat/completions -H "Authorization: Bearer test-api-key-1" -H "X-Team-ID: team-alpha" -H "Content-Type: application/json" -d '{\"model\":\"llama3.2:1b\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}]}'
```

You should get a JSON response with a `choices` array.

---

### Confirm Usage Was Logged

```powershell
kubectl exec -n llm-gateway deployment/postgres -- psql -U gateway -d gatewaydb -c "SELECT team_id, model_name, prompt_tokens, completion_tokens, cost_usd, status_code, created_at FROM request_logs ORDER BY created_at DESC LIMIT 5;"
```

You should see a row with `team-alpha` and `llama3.2:1b`.

---

### Test Rate Limiting

The default limit in `k8s/configmap.yaml` is now `3` requests per 60 seconds. Send 5 requests:

```powershell
1..5 | ForEach-Object { curl.exe -s -o NUL -w "%{http_code}`n" -X POST http://127.0.0.1:8000/v1/chat/completions -H "Authorization: Bearer test-api-key-1" -H "X-Team-ID: team-alpha" -H "Content-Type: application/json" -d '{\"model\":\"llama3.2:1b\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}]}' }
```

You should see `200` for the first few requests, then `429` after the limit is reached.

Verify violations were recorded:

```powershell
kubectl exec -n llm-gateway deployment/postgres -- psql -U gateway -d gatewaydb -c "SELECT team_id, api_key, created_at FROM rate_limit_violations ORDER BY created_at DESC LIMIT 5;"
```

---

### Open the Dashboard

Keep the dashboard port-forward running, then open:

```text
http://127.0.0.1:8501/dashboard/
```

The dashboard shows Team Usage, Cost Breakdown, Request Volume, and Rate Limit Violations.

---

## Change the Rate Limit

The rate limit is controlled here:

```yaml
RATE_LIMIT_REQUESTS: "3"
RATE_LIMIT_WINDOW_SECONDS: "60"
```

After editing `k8s/configmap.yaml`, you do not need to redeploy everything. Run only:

```powershell
kubectl apply -f k8s/configmap.yaml; kubectl rollout restart deployment/gateway -n llm-gateway; kubectl rollout status deployment/gateway -n llm-gateway
```

Then retry the health check:

```powershell
curl.exe http://127.0.0.1:8000/health
```

---

## Run Unit Tests

Make sure your virtual environment is active:

```powershell
.\venv\Scripts\Activate.ps1; python -m pytest tests/ -v
```

---

## Rebuild After Code Changes

If you edit gateway code:

```powershell
docker build -t llm-gateway:latest ./gateway; minikube image load llm-gateway:latest; kubectl rollout restart deployment/gateway -n llm-gateway; kubectl rollout status deployment/gateway -n llm-gateway
```

If you edit dashboard code:

```powershell
docker build -t llm-dashboard:latest ./dashboard; minikube image load llm-dashboard:latest; kubectl rollout restart deployment/dashboard -n llm-gateway; kubectl rollout status deployment/dashboard -n llm-gateway
```

---

## Troubleshooting

**Port `8000` is already in use**

The gateway port-forward may already be running. Try:

```powershell
curl.exe http://127.0.0.1:8000/health
```

Or use a different local port:

```powershell
kubectl -n llm-gateway port-forward svc/gateway-service 8080:8000
```

Then test from another terminal:

```powershell
curl.exe http://127.0.0.1:8080/health
```

**Pods stuck in `ImagePullBackOff`**

Reload the image into Minikube and restart the deployment:

```powershell
minikube image load llm-gateway:latest; kubectl rollout restart deployment/gateway -n llm-gateway
```

**Ollama is unreachable**

Check Ollama on Windows:

```powershell
curl.exe http://localhost:11434/api/tags
```

Then restart the gateway:

```powershell
kubectl rollout restart deployment/gateway -n llm-gateway
```

**Postgres is not ready**

```powershell
kubectl logs -n llm-gateway deployment/postgres; kubectl delete pod -n llm-gateway -l app=postgres
```

**General debugging**

```powershell
kubectl get pods -n llm-gateway; kubectl describe pod <pod-name> -n llm-gateway; kubectl logs -n llm-gateway deployment/gateway; kubectl logs -n llm-gateway deployment/dashboard; kubectl logs -n llm-gateway deployment/redis
```

---

## Useful Commands

```powershell
kubectl get all -n llm-gateway; kubectl get ingress -n llm-gateway; kubectl get pods -n llm-gateway -w; kubectl exec -it -n llm-gateway deployment/gateway -- /bin/bash
```

---

## Stop Everything

Remove project resources but keep Minikube:

```powershell
kubectl delete namespace llm-gateway
```

Stop Minikube:

```powershell
minikube stop
```

Delete Minikube and free disk space:

```powershell
minikube delete
```

## Stop Ollama

Find the process using port 11434 and kill it:

```powershell
taskkill /IM ollama.exe /F
```


Verify it stopped:

```powershell
curl.exe http://localhost:11434/api/tags
```

You should get a connection refused error, which means Ollama is no longer running.
