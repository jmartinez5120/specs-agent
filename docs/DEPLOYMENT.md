# Deployment

Three deployment surfaces, smallest to largest:

1. **Local TUI** — `pip install -e .`, runs against `~/.specs-agent/`
2. **Single host (`docker compose`)** — for a dev workstation
3. **Kubernetes (`k8s/specs-agent/`)** — the enterprise rollout

This doc covers (3). For (1) and (2) see [README.md](../README.md) and
[INSTALL_LOCAL.md](../INSTALL_LOCAL.md).

## Pre-flight

Confirm your laptop can reach the cluster + registry:

```bash
kubectl get nodes                               # kubeconfig works
curl -s http://192.168.0.100:30500/v2/_catalog  # registry reachable
```

If `kubectl` errors, you don't have a kubeconfig pointed at the cluster.
If `curl` errors, mark the registry insecure in `~/.docker/daemon.json`
(see [INFRASTRUCTURE.md](INFRASTRUCTURE.md#container-registry)).

## 1 — Build & push images

The cluster is `arm64` so cross-build with buildx:

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

Verify:

```bash
curl -s http://192.168.0.100:30500/v2/_catalog
# Expect "specs-agent-api" and "specs-agent-web" in the list.
```

## 2 — Create the secrets (NEVER commit)

The Deployment expects a `specs-agent-ai-keys` Secret. Create it
imperatively — the example file is committed but the real one is
gitignored:

```bash
kubectl -n specs-agent create secret generic specs-agent-ai-keys \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-...your-real-key... \
  --from-literal=OPENAI_API_KEY=sk-...your-real-key...      \
  --from-literal=HTTP_API_KEY=
```

To rotate a key later:

```bash
kubectl -n specs-agent create secret generic specs-agent-ai-keys \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-NEW \
  --from-literal=OPENAI_API_KEY=sk-NEW \
  --from-literal=HTTP_API_KEY= \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n specs-agent rollout restart deploy/specs-agent-api
```

Empty values are fine — the env mapping in the Deployment marks each
secret key as `optional: true`.

## 3 — Apply manifests

Whole namespace in one go:

```bash
kubectl apply -f k8s/specs-agent/
```

Apply order doesn't matter (kubectl is idempotent), but for readability
the files are numbered:

```
00-namespace.yaml          namespace + tenancy labels
10-mongodb.yaml            StatefulSet + headless Service + init Job
11-elasticsearch.yaml      StatefulSet + Service
20-secret.example.yaml     template (real Secret created in step 2)
30-configmap.yaml          non-sensitive runtime config
40-api.yaml                Deployment x2 + Service + HPA + ServiceAccount
41-web.yaml                Deployment x2 + Service (NodePort) + nginx ConfigMap
50-ingress.yaml            Traefik Ingress on :80
60-network-policy.yaml     east-west isolation
```

## 4 — Watch the rollout

```bash
kubectl -n specs-agent get pods -w
```

Expected sequence on a cold start (~5–10 min on Pi):

1. `mongo-0` ContainerCreating → Running (1/1) — image pull is slow.
2. `mongo-init-*` Running → Completed — calls `rs.initiate()` once.
3. `elasticsearch-0` Init → Running (1/1) — chown initContainer first.
4. `specs-agent-api-*` Init → Running → 1/1 Ready — init container
   waits for Mongo + ES TCP, then lifespan connects.
5. `specs-agent-web-*` Running (1/1).

If anything CrashLoops, `kubectl logs <pod> --previous` is your friend.
Common gotchas are documented in [INFRASTRUCTURE.md](INFRASTRUCTURE.md)
and the commit history of `k8s/specs-agent/10-mongodb.yaml`.

## 5 — Verify

```bash
# Internal: from any cluster pod
kubectl -n specs-agent exec deploy/specs-agent-web -- \
  curl -sS http://specs-agent-api.specs-agent.svc.cluster.local:8765/health

# External: via Ingress
curl -s --resolve specs-agent.m2cl.local:80:192.168.0.100 \
  http://specs-agent.m2cl.local/api/health

# External: via NodePort
curl -s http://192.168.0.100:30765/api/health
```

All three should return `{"status":"ok","service":"specs-agent-api"}`.

Then open the UI:
- `http://specs-agent.m2cl.local` (with `/etc/hosts` entry), OR
- `http://192.168.0.100:30765` (or any node IP)

## Updating

Image tags use `:latest` with `imagePullPolicy: Always`. To roll out
new code:

```bash
# Rebuild + push
docker buildx build --platform linux/arm64 \
  -t 192.168.0.100:30500/specs-agent-api:latest --push .

# Force a fresh pull on every pod
kubectl -n specs-agent rollout restart deploy/specs-agent-api
kubectl -n specs-agent rollout status  deploy/specs-agent-api
```

For the Web:

```bash
docker buildx build --platform linux/arm64 \
  -t 192.168.0.100:30500/specs-agent-web:latest --push web

kubectl -n specs-agent rollout restart deploy/specs-agent-web
```

## Scaling

The API has an HPA (2..6 replicas, CPU-based at 70%). To change limits:

```bash
kubectl -n specs-agent edit hpa specs-agent-api
```

Web is fixed at 2. Bump replicas in `41-web.yaml` if needed.

## Removing

```bash
# Wipe everything in the namespace, including PVCs (data loss)
kubectl delete namespace specs-agent

# Or — keep data, only remove workloads
kubectl -n specs-agent delete deploy,sts,svc,ingress,cm --all
```

## Troubleshooting

| Symptom                                     | Likely cause + fix                                                |
|---------------------------------------------|-------------------------------------------------------------------|
| `mongo-0` SIGILL on boot                    | Used `mongo:7` or `4.4.19+`; pin `mongo:4.4.18`                   |
| Init Job loops "waiting for mongod"         | `mongosh` not in 4.4 image; use `mongo` (the legacy shell)        |
| API "set named 'None'"                      | rs.initiate() never ran. Check `kubectl exec mongo-0 -- mongo --quiet --eval "rs.status().ok"` — must be 1 |
| Init Job can't reach Mongo                  | Pod missing `app.kubernetes.io/name: mongodb-init` label; the NetworkPolicy denies it |
| Traefik logs "service port not found"       | Service port number doesn't match Ingress backend port            |
| `ImagePullBackOff` on `192.168.0.100:30500` | Registry not in Docker daemon's `insecure-registries`             |

## See also

- [INFRASTRUCTURE.md](INFRASTRUCTURE.md) — cluster, network, registry
- [SECURITY.md](SECURITY.md) — secret hygiene
- [../k8s/specs-agent/README.md](../k8s/specs-agent/README.md) — manifest reference
