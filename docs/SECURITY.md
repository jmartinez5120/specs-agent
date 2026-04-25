# Security

What's protected, where secrets live, what's intentionally out of scope.
This doc is **descriptive of the current posture**, not aspirational.

## Threat model

| Concern                                | Status                                      |
|----------------------------------------|---------------------------------------------|
| Secret leakage to public git           | Defended (see "Secret hygiene" below)       |
| Secret leakage via API responses       | Defended — `mask_secret()` on every GET     |
| Cross-pod east-west attacks            | Defended on policy-aware CNI (NetworkPolicy)|
| Tenant isolation in shared mode        | **None** — single shared config + Mongo     |
| Auth on the Web UI / API               | **None** — open in shared/dev mode          |
| TLS at the cluster edge                | **None** — Ingress is HTTP-only             |
| TLS between pods                       | **None** — plain HTTP / Mongo / ES wire     |
| At-rest encryption (Mongo, ES, PVC)    | **None** — local-path PVCs are plain disk   |

The two "Defended" rows are work specs-agent owns. The "None" rows are
explicitly deferred — they belong to the K8s platform layer (TLS via
cert-manager, auth via OIDC proxy) and the multi-tenancy MVP (auth +
per-user config overrides).

## Secret hygiene

### What's a secret

| Field                         | Where it goes                            |
|-------------------------------|------------------------------------------|
| `ai_anthropic_api_key`        | K8s Secret → env → in-process AppConfig  |
| `ai_openai_api_key`           | K8s Secret → env → AppConfig             |
| `ai_http_api_key`             | K8s Secret → env → AppConfig             |
| `auth_value` (per-test bearer)| Mongo `plans` collection (in-cluster)    |
| User-supplied request bodies  | Mongo `history` collection               |

### Defenses in code

- **Masking on read** — `src/specs_agent/api/converters.py::mask_secret()`
  produces `sk-ant***1234`. Applied to every `*_api_key` field in
  `config_to_dto()`. Never returns the raw value.
- **Preserve-on-empty PUT** — `merge_config_preserving_secrets()` treats
  `""` for any `*_api_key` as "leave unchanged." Lets the UI re-save a
  masked-value form without echoing the mask back as a literal key.
- **No secrets in logs** — the AI backends log error messages (which
  may include API responses) but never log the API key itself.

### Defenses in repo

- `k8s/specs-agent/.gitignore` excludes `20-secret.yaml` and any
  `*-secret.yaml` (with one exception: `*-secret.example.yaml` is
  allowed for templates).
- `20-secret.example.yaml` ships with `REPLACE-ME` placeholder values.
  The string `REPLACE-ME` will fail any real provider call — there's no
  silent "test mode" that uses example credentials.
- The deploy pipeline never reads `20-secret.yaml`. Operators create the
  Secret via `kubectl create secret` directly:

  ```bash
  kubectl -n specs-agent create secret generic specs-agent-ai-keys \
    --from-literal=ANTHROPIC_API_KEY=... \
    --from-literal=OPENAI_API_KEY=...
  ```

### Defenses in K8s

- Secrets are mounted as env vars from the Secret object, not baked into
  the image, ConfigMap, or Deployment manifest.
- Each env var maps from a key on `specs-agent-ai-keys`; missing keys
  are tolerated via `optional: true` (the AI backend silently treats an
  empty key as "this provider is unavailable").

## NetworkPolicy

Two policies live in `k8s/specs-agent/60-network-policy.yaml`:

```
mongo-from-api-only         mongo:27017 accepts ingress only from
                              app.kubernetes.io/name=specs-agent-api
                              app.kubernetes.io/name=mongodb-init

elasticsearch-from-api-only es:9200 accepts ingress only from
                              app.kubernetes.io/name=specs-agent-api
```

Web pods cannot talk to Mongo or ES directly — everything goes through
the API. The init Job needs the matching label on its pod template
(`spec.template.metadata.labels`); without it the policy denies the
init traffic. This is documented in the manifest comments.

**Caveat:** policies are only enforced when the cluster's CNI supports
them (Calico, Cilium, Antrea, …). Stock K3s flannel does not enforce.
Audit before assuming protection.

## Auth & TLS — the gap

Today the API is open to anyone who can reach the cluster network. There
is no:
- bearer-token check on `/config`, `/admin/config`, or any other route
- session/cookie/CSRF mechanism on the Web
- TLS termination at the Ingress
- mTLS between Pods

For a production rollout this stack needs to sit behind:
1. An OIDC proxy (oauth2-proxy → Keycloak / Auth0 / Okta) that handles
   login + sets an `X-User-Id` header from the verified token.
2. cert-manager + Let's Encrypt for TLS at the Ingress.
3. Optionally, a service mesh (linkerd / istio) for in-cluster mTLS.

The codebase already supports the user-id header ingestion path; the
auth gate is what's missing.

## Multi-tenancy — the bigger gap

In shared mode every user sees every plan, every history record, every
spec. There is no row-level access control in the storage layer. The
multi-tenancy MVP plan (in [ARCHITECTURE.md](ARCHITECTURE.md#multi-tenancy-posture-current--target))
adds:
- Per-user overrides on a whitelisted set of fields (own AI keys, model)
- Per-tenant Mongo databases or per-tenant collection prefixes
- Per-tenant K8s namespaces, parameterised via Kustomize/Helm
- Admin gate on `/admin/config` for editing server defaults

Until that lands, treat this deploy as "single team, shared trust."

## What to audit on a fresh clone

Before pushing changes, run:

```bash
# Anything that looks like a real key in tracked content?
git grep -E 'sk-(ant|proj|live)-[A-Za-z0-9_-]{20,}'

# Anything in history?
git log --all -p | grep -E 'sk-(ant|proj|live)-[A-Za-z0-9_-]{20,}'

# Should be empty (or only the REPLACE-ME placeholder)
```

## See also

- [ARCHITECTURE.md](ARCHITECTURE.md) — provider abstraction + masking flow
- [DEPLOYMENT.md](DEPLOYMENT.md) — Secret creation steps
- [INFRASTRUCTURE.md](INFRASTRUCTURE.md) — NetworkPolicy CNI caveats
