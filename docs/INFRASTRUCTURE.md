# Infrastructure

specs-agent's reference deployment runs on a 5-node K3s cluster of
Raspberry Pi nodes. This doc captures the topology, conventions, and
gotchas so the deploy is reproducible.

## Cluster

| Property        | Value                                          |
|-----------------|------------------------------------------------|
| Distribution    | K3s `v1.34.3+k3s1`                             |
| Nodes           | 5 (1 control-plane, 4 workers)                 |
| Node OS         | Ubuntu 24.04.3 LTS, kernel `6.8.0-*-raspi`     |
| Architecture    | `arm64` (ARMv8-A — **not** ARMv8.2-A)          |
| Control plane   | `knode1.m2cl.com` → `192.168.0.100`            |
| Worker IPs      | `192.168.0.{102,103,104,106}`                  |
| Container rt    | `containerd 2.1.5-k3s1`                        |
| Default SC      | `local-path` (Rancher local-path-provisioner)  |
| Ingress         | Traefik v3 (`traefik.io/ingress-controller`)   |
| CNI             | Enforces NetworkPolicy (verified — see note)   |

**Important:** the Pi CPUs do not implement ARMv8.2-A. Many modern
container images (notably MongoDB ≥5.0 and ≥4.4.19) require it and
crash with SIGILL on boot. Pin to versions that pre-date the requirement
or use community ARMv8-A builds. specs-agent uses `mongo:4.4.18`.

**NetworkPolicy:** stock K3s ships with flannel which does *not* enforce
NetworkPolicy. This cluster has been provisioned with a policy-aware CNI
(verified empirically — the policy in `60-network-policy.yaml` blocked
the init Job until its labels matched). Audit your CNI before assuming
policies are advisory.

## Internal DNS

In-cluster DNS follows the standard K8s scheme:

```
<service>.<namespace>.svc.cluster.local
```

Per-pod stable DNS (StatefulSet only):

```
<pod>.<headless-service>.<namespace>.svc.cluster.local
```

specs-agent service names:
- `mongo.specs-agent.svc.cluster.local` (headless; resolves to pod IPs)
- `mongo-0.mongo.specs-agent.svc.cluster.local` (stable per-pod)
- `elasticsearch.specs-agent.svc.cluster.local`
- `specs-agent-api.specs-agent.svc.cluster.local`
- `specs-agent-web.specs-agent.svc.cluster.local`

## Container registry

| Property        | Value                                          |
|-----------------|------------------------------------------------|
| Endpoint        | `192.168.0.100:30500` (NodePort, plain HTTP)   |
| Cluster Service | `registry.registry.svc.cluster.local:5000`     |
| Auth            | None (LAN-only, dev cluster)                   |
| TLS             | Off                                            |

To push images from your laptop, mark the registry insecure in
`~/.docker/daemon.json`:

```json
{ "insecure-registries": ["192.168.0.100:30500"] }
```

Restart Docker for the change to take effect.

## Storage

`local-path` is the only StorageClass available. It binds PVs to one
node's local disk and uses `WaitForFirstConsumer` binding mode — a PVC
isn't bound until the consuming pod is scheduled, then it's pinned to
that node forever.

specs-agent PVCs:
- `data-mongo-0` — 10Gi, lives wherever mongo-0 was first scheduled.
- `data-elasticsearch-0` — 10Gi, same story.

If a node dies, the PV is unrecoverable. For a production rollout,
swap in longhorn or rook-ceph for distributed storage.

## Ports & exposure

```
External  ────── Traefik :80 (Ingress)        → web Service :80
                 NodePort :30765              → web Service :80

In-cluster only  web :80 (proxies /api,/ws)   → api :8765
                 api :8765                    → mongo :27017, es :9200
                 mongo :27017                 (headless, per-pod)
                 elasticsearch :9200/9300
```

The cluster API server is on `192.168.0.100:6443` (TLS, mTLS via
kubeconfig). NOT on the public internet.

## Multi-namespace conventions

This deploy uses a single `specs-agent` namespace. The cluster also runs
unrelated workloads in other namespaces (visible to anyone with kubectl
access):

```
default · home-assistant · kube-system · portainer · postgres
quartermaster · registry
```

For an enterprise rollout, each tenant gets its own namespace
(`specs-agent-<tenant>`) parameterised through Kustomize or Helm. The
manifests in `k8s/specs-agent/` are the base; Kustomize overlays are
the next milestone.

## CI/CD posture

Today: manual `docker buildx build --push` from a developer laptop, then
`kubectl apply -f k8s/specs-agent/`. No GitHub Actions runner inside the
cluster yet. Tags use `:latest` with `imagePullPolicy: Always` and
`kubectl rollout restart` to force a re-pull.

Target (next milestone):
1. Tag images by git SHA (`specs-agent-api:abc123`).
2. GitHub Actions builds + pushes to a registry the cluster can reach.
3. ArgoCD or Flux watches `k8s/` for changes and reconciles.
4. Promotion via per-environment overlays.

## See also

- [DEPLOYMENT.md](DEPLOYMENT.md) — build, push, apply, verify
- [SECURITY.md](SECURITY.md) — secret handling
- [../k8s/specs-agent/README.md](../k8s/specs-agent/README.md) — manifest details
