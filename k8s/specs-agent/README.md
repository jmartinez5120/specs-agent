# specs-agent on K3s — enterprise deployment

The specs-agent platform runs as four workloads in a dedicated namespace.
Designed to read like an enterprise rollout: dedicated namespace, RBAC-ready,
horizontal autoscaling, network isolation, secret hygiene.

## Topology

```
                 ┌────────────────┐
                 │ Traefik Ingress│  specs-agent.m2cl.local
                 └────────┬───────┘
                          │
                  ┌───────▼──────┐
                  │  web (nginx) │  Deployment × 2 + ConfigMap (proxy rules)
                  └───────┬──────┘
                          │ /api, /ws proxy
                  ┌───────▼──────┐
                  │     api      │  Deployment × 2 (HPA: 2..6)
                  └──┬────────┬──┘
                     │        │
              ┌──────▼──┐  ┌──▼──────────┐
              │ mongo   │  │ elasticsearch│  StatefulSet (PVC)
              │ rs0     │  │ single-node  │
              └─────────┘  └──────────────┘
```

All cluster-internal DNS — only the Web is reachable through Ingress.

## What's in this folder

```
00-namespace.yaml          dedicated namespace + tenancy labels
10-mongodb.yaml            StatefulSet (rs0) + headless Service + init Job
11-elasticsearch.yaml      StatefulSet + Service
20-secret.example.yaml     template only — copy to 20-secret.yaml (gitignored)
30-configmap.yaml          non-sensitive runtime config
40-api.yaml                API Deployment × 2 + Service + HPA + ServiceAccount
41-web.yaml                Web Deployment × 2 + Service + nginx ConfigMap
50-ingress.yaml            Traefik Ingress (specs-agent.m2cl.local)
60-network-policy.yaml     east-west isolation (DB pods accept only API traffic)
.gitignore                 keeps real *-secret.yaml out of the repo
```

## First-time setup

### 1. Build & push images (arm64 — the cluster is Raspberry Pi)

The cluster registry is at `192.168.0.100:30500` (insecure HTTP). Add it to
your local Docker daemon first:

```jsonc
// ~/.docker/daemon.json
{
  "insecure-registries": ["192.168.0.100:30500"]
}
```

then `docker buildx`:

```bash
# API
docker buildx build --platform linux/arm64 \
  -t 192.168.0.100:30500/specs-agent-api:latest \
  -f Dockerfile --push .

# Web
docker buildx build --platform linux/arm64 \
  -t 192.168.0.100:30500/specs-agent-web:latest \
  -f web/Dockerfile --push web
```

### 2. Create the AI keys Secret (NEVER commit)

```bash
kubectl -n specs-agent create secret generic specs-agent-ai-keys \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=OPENAI_API_KEY=sk-... \
  --from-literal=HTTP_API_KEY=
```

(Keys can be empty — the secret entry is optional in the API Deployment
env mapping.)

### 3. Apply the rest

```bash
kubectl apply -f k8s/specs-agent/
```

Watch the rollout:

```bash
kubectl -n specs-agent get pods -w
```

The init Job (`mongo-init`) runs once and exits. The API pods wait for
Mongo + ES to be reachable before booting (init container).

### 4. Reach the UI

```bash
# Find the Traefik LB IP
kubectl -n kube-system get svc traefik

# Add to /etc/hosts on your laptop, then visit:
#   http://specs-agent.m2cl.local
```

Or, if you'd rather skip DNS, the Ingress also serves the bare cluster IP
on `/`.

## Rolling updates

```bash
# Rebuild + push
docker buildx build --platform linux/arm64 \
  -t 192.168.0.100:30500/specs-agent-api:latest --push .

# Force a rollout (image tag is :latest, so we restart to re-pull)
kubectl -n specs-agent rollout restart deploy/specs-agent-api
kubectl -n specs-agent rollout status deploy/specs-agent-api
```

## Multi-tenancy posture

Today's deploy is "shared mode": one namespace, one set of server defaults,
all users hit the same Mongo. The plumbing for per-user overrides is in the
codebase (X-User-Id header support, user_configs collection schema), but
auth and per-user UI flows ship in MVP-9. To move to true multi-tenant:

1. Stand up per-tenant namespaces with this same manifest set, parameterised
   via Kustomize/Helm.
2. Front the Ingress with an OIDC proxy (e.g. oauth2-proxy → Keycloak) that
   sets `X-User-Id` from the verified identity.
3. Enable `/admin/config` route auth and split server defaults from user
   overrides via the existing `user_configs` collection.

## Removing the deployment

```bash
kubectl delete -f k8s/specs-agent/   # removes everything including data PVCs
# Or, keep the data PVCs and only remove the workloads:
kubectl -n specs-agent delete deploy,sts,svc,ingress,cm --all
```
