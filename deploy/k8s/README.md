# Kubernetes Deployment

## Image Registry

Images are published to Docker Hub under **`radicalgeek`**:

| Image | Docker Hub |
|-------|-----------|
| Backend (API + migrations) | `radicalgeek/mission-control-backend` |
| Frontend (Next.js) | `radicalgeek/mission-control-frontend` |

Both images are **public** — no pull secret is required.

## Applying Manifests

The manifests use `${BACKEND_IMAGE}` and `${FRONTEND_IMAGE}` placeholders that must be substituted before applying.

```bash
export BACKEND_IMAGE=radicalgeek/mission-control-backend:latest
export FRONTEND_IMAGE=radicalgeek/mission-control-frontend:latest

# Optional: pin to a specific SHA for immutable deploys
# export BACKEND_IMAGE=radicalgeek/mission-control-backend:a75ce10
# export FRONTEND_IMAGE=radicalgeek/mission-control-frontend:a75ce10

envsubst < deploy/k8s/05-backend.yaml | kubectl apply -f -
envsubst < deploy/k8s/06-worker.yaml  | kubectl apply -f -
envsubst < deploy/k8s/07-frontend.yaml | kubectl apply -f -
```

Or apply all at once (after setting env vars):

```bash
for f in deploy/k8s/0{1,2,3,4,5,6,7,8}-*.yaml; do
  envsubst < "$f" | kubectl apply -f -
done
```

## Manifest Order

| File | Purpose |
|------|---------|
| `01-namespace.yaml` | `mission-control` namespace |
| `02-secrets.yaml` | Secret template (fill before applying) |
| `03-postgres.yaml` | PostgreSQL StatefulSet |
| `04-redis.yaml` | Redis Deployment |
| `05-backend.yaml` | FastAPI backend (includes Alembic migrate initContainer) |
| `06-worker.yaml` | RQ background worker |
| `07-frontend.yaml` | Next.js frontend |
| `08-ingress.yaml` | Ingress / TLS |

## Secrets

`02-secrets.yaml` must be populated with real values before first deploy. Required keys:

- `DATABASE_URL`
- `LOCAL_AUTH_TOKEN`
- `GITLAB_SKILLS_TOKEN`
- `GITLAB_SKILLS_PROJECT_ID`

## Building New Images

```bash
# From repo root:
GIT_SHA=$(git rev-parse --short HEAD)

docker build -f backend/Dockerfile \
  -t radicalgeek/mission-control-backend:latest \
  -t radicalgeek/mission-control-backend:${GIT_SHA} \
  .

docker build -f frontend/Dockerfile \
  --build-arg NEXT_PUBLIC_API_URL=auto \
  --build-arg NEXT_PUBLIC_AUTH_MODE=local \
  -t radicalgeek/mission-control-frontend:latest \
  -t radicalgeek/mission-control-frontend:${GIT_SHA} \
  frontend/

docker push radicalgeek/mission-control-backend:latest
docker push radicalgeek/mission-control-backend:${GIT_SHA}
docker push radicalgeek/mission-control-frontend:latest
docker push radicalgeek/mission-control-frontend:${GIT_SHA}
```
