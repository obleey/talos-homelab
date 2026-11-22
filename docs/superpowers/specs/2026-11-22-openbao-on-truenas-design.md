# OpenBao on TrueNAS — design

## Why

Learning, and then running it for real. Miha wants hands-on experience with the Vault/OpenBao model (seal/unseal, policies, auth methods, External Secrets) in the shape companies actually run it: a dedicated secrets service outside the cluster that the cluster consumes. Once proven, it becomes the homelab's only secrets system. Every SealedSecret moves to OpenBao, and Sealed Secrets is removed.

## Goals

- OpenBao runs as a Dockge stack on TrueNAS (`10.0.0.104`), independent of the cluster.
- Manual Shamir unseal after a NAS reboot. A Slack alert says when it's sealed or down.
- External Secrets Operator (ESO) in the cluster, managed by ArgoCD, replaces Sealed Secrets for all 17 secrets.
- Per-namespace access: each namespace can read only `secret/<namespace>/*`.
- OpenBao's configuration (policies, auth roles, mounts) is reproducible by re-running `~/Documents/code/openbao/configure.sh`.
- OpenBao data is backed up off-site to the Storage Box, and a restore has been drilled.
- The existing lint keeps checking secret key names.

## Non-goals

- HA / multiple OpenBao nodes, auto-unseal.
- PKI engine, dynamic credentials, transit.
- Moving `backup.sh`'s plaintext secrets into OpenBao.
- Renovate for the NAS stack (it can't see the NAS; upgrades are manual).

## Anti-goals

- A restic password that exists only in OpenBao. The NAS restic password restores OpenBao, so it stays in the password manager. `forgejo-restic` moves to OpenBao, and its value also stays in the password manager.
- OpenBao reachable from the internet. LAN only, no ingress, no Cloudflare DNS.
- Unseal keys or root token stored on the NAS or in git.
- A stage that can't be rolled back from git (until the final cleanup stage).

## Constraints (found on the box and in the repo)

- TrueNAS 25.10, 8 cores, 62 GiB RAM (~51 GiB is ZFS ARC, reclaimable). OpenBao needs ~200 MB.
- Dockge stacks live in `/mnt/serve/stacks/<name>/` (ZFS dataset `serve/stacks`). Port 8200 is free.
- `backup.sh` (`/mnt/serve/stacks/restic_cron/`) backs up only `/mnt/serve/Miha` and `/mnt/serve/Nina` today.
- Kubernetes API: `https://10.0.0.160:6443`. The ArgoCD repo is public GitHub (no repo credentials secret).
- Existing blackbox alert: `probe_success{job="blackbox"} == 0` for 5m → Slack (`grafana-blackbox-rules.yaml`).
- `scripts/lint.py` reads secret key names from SealedSecrets (`repo.sealed_keys()`) to check every `secretKeyRef` and `HOMEPAGE_VAR_*`.
- The README promises "credentials included" live in the repo and documents rebuild via the sealing key.

## Approaches considered

- **OpenBao in-cluster (Helm, Raft on Longhorn).** GitOps-managed, but OpenBao then depends on the cluster it serves, and every Talos upgrade reseals pods.
- **OpenBao on TrueNAS (chosen).** Matches the real-world "external Vault" shape and doesn't depend on the cluster. The NAS rarely reboots, so manual unseal is cheap. Cost: not ArgoCD-managed.
- **Dev-mode sandbox.** Fast, but teaches none of the ops side, and can't carry real load.
- **Hybrid (bootstrap/monitoring secrets stay sealed).** Keeps the cluster rebuildable from git alone, but means running two secret systems forever. Rejected: OpenBao is outside the cluster, so the only cost of all-in is a rebuild-order step (NAS → unseal → cluster).

## Design

### OpenBao on TrueNAS

- Stack files (`compose.yaml`, `openbao.hcl`, `sync-cert.sh`), the config scripts (`configure.sh`, `import.sh`) and the ops README live in `~/Documents/code/openbao/`, outside this repo and not in git (Miha's call), copied to `/mnt/serve/stacks/openbao/` and deployed with Dockge.
- Image `openbao/openbao`, pinned to the current release.
- Storage: integrated Raft, single node (`node_id = "truenas"`), data in `/mnt/serve/stacks/openbao/data`.
- Listener `0.0.0.0:8200`, TLS on, using a Let's Encrypt cert for `openbao.local.obleey.com` issued and renewed by TrueNAS's ACME client (DNS-01 via Cloudflare). A root cron job (`sync-cert.sh`) copies it into the stack and SIGHUPs OpenBao. Clients use the hostname (Technitium A record), since LE can't certify a LAN IP. *(Changed from a self-signed CA: the cert is publicly trusted, so there's no CA bundle in git and no CA key to guard, and the existing blackbox SSL-expiry alert covers it.)*
- `api_addr = "https://openbao.local.obleey.com:8200"`, `cluster_addr = "https://127.0.0.1:8201"`, `ui = true`, `disable_mlock = true`.
- File audit device writing to `/openbao/audit/audit.log`. Alloy on the NAS ships it to VictoriaLogs.
- Optional DNS `openbao.local.obleey.com → 10.0.0.104` in Technitium. Clients use the IP so they don't depend on DNS.

### Init, unseal, and config-as-code

- `bao operator init -key-shares=3 -key-threshold=2`. Unseal keys and root token go into the password manager.
- After a NAS reboot: `bao operator unseal` twice. Secrets already in the cluster keep working while OpenBao is sealed; only refreshes stop.
- `~/Documents/code/openbao/configure.sh`: an idempotent script of `bao` commands that sets up the KV mount, Kubernetes auth, and one policy plus role per namespace. Run with an admin token whenever it changes. Namespaces are a list at the top of the script. *(My call over Terraform/OpenTofu: no state file, no provider.)*

### Secrets layout and policies

- KV v2 at `secret/`. Path `secret/<namespace>/<secret-name>`, keys identical to today's Secret keys (e.g. `secret/servarr/homepage-secrets`).
- Namespaces: `servarr`, `forgejo`, `netbird`, `argocd`, `cert-manager`, `monitoring`.
- Per namespace: policy `<ns>-read` (`read` on `secret/data/<ns>/*`), and Kubernetes-auth role `<ns>` bound to SA `openbao-reader` in that namespace, TTL 1h.
- Kubernetes auth: `kubernetes_host=https://10.0.0.160:6443`, `kubernetes_ca_cert` = the cluster CA, no `token_reviewer_jwt`. OpenBao reviews each client's own JWT, so each `openbao-reader` SA gets `system:auth-delegator`.

### Cluster side

- `deployments/infrastructure/external-secrets/app.yaml`: the `external-secrets` chart, pinned, same `Application` shape as `sealed-secrets/app.yaml`, sync-wave `-5` (ESO must exist before anything that reads secrets). ESO metrics are scraped by the existing stack.
- Per namespace: ServiceAccount `openbao-reader`, a ClusterRoleBinding to `system:auth-delegator`, and a `SecretStore` named `openbao` (provider `vault`, server `https://openbao.local.obleey.com:8200`, path `secret`, version `v2`, no `caBundle` (publicly trusted cert), kubernetes auth role `<ns>`). These sit next to the namespace's existing secrets.
- Each SealedSecret becomes an `ExternalSecret` with the same target Secret name, so no consumer changes. Settings:
  - explicit `data:` entries, one per key (not `dataFrom`), so key names stay in git for the lint;
  - `refreshInterval: 1h`;
  - `target.deletionPolicy: Retain`;
  - `target.template` copies any labels or annotations the SealedSecret's template had (e.g. ArgoCD's `app.kubernetes.io/part-of: argocd`).

### Alerts

- **Sealed or down:** a blackbox target `openbao` → `https://openbao.local.obleey.com:8200/v1/sys/health` in `alloy-blackbox/values.yaml`. This returns 200 only when unsealed (503 sealed, 501 uninitialised), so the existing blackbox alert fires after 5m. It needs a module with `valid_status_codes: [200]` and normal TLS verification, so the SSL-expiry alert also covers the cert. No new rule.
- **Secret not syncing:** a new Grafana rule on ESO's ExternalSecret Ready=False condition metric, for 15m → Slack. It goes in the existing alerts folder, following the existing rule files.

### Lint

- `scripts/repo.py`: replace `sealed_keys()` with `secret_keys()`, which reads `ExternalSecret.spec.data[].secretKey` (keyed by `spec.target.name`). During migration it reads both kinds.
- `scripts/lint.py` checks keep working unchanged against `secret_keys()`. `test_lint.py` gets one case for an ExternalSecret.
- `CRITICAL` set: swap `sealed-secrets` for `external-secrets`.

### Backup and restore drill

- `backup.sh` takes `bao operator raft snapshot save` into `/mnt/serve/stacks/openbao/snapshots/`, then restic-backs up that folder (`--tag openbao`).
- Snapshot auth: a periodic token with policy `snapshot` (`read` on `sys/storage/raft/snapshot`), root-only file `/mnt/serve/stacks/restic_cron/openbao-token`, renewed by the script each run.
- If the snapshot fails (e.g. sealed), report it through the existing Slack `report` path.
- Drill: restore the latest snapshot into a throwaway OpenBao container, unseal it, read a secret. Written down in the README.

## Stages

Each stage is its own commit/PR, rollbackable from git until stage 6.

1. **Foundation.** OpenBao stack on the NAS, init, unseal, configure script, sealed/down probe. Nothing in the cluster reads from it yet.
2. **ESO plus homepage.** ESO app, `servarr` namespace store, `homepage-secrets` as an ExternalSecret, lint support, the not-syncing alert.
3. **Backup and drill.** Snapshot in `backup.sh`, audit log shipping, restore drill done once.
4. **Apps.** `servarr-credentials`, `autopulse-secret`, `unpackerr-ui`, the 4 forgejo secrets, `netbird-mgmt-api-key`.
5. **Infra.** `argocd-google-oauth`, `argocd-notifications-secret`, `cloudflare-api-token`, the 5 monitoring secrets.
6. **Cleanup.** Remove the sealed-secrets app and `kubeseal-webgui` (plus its homepage entry and probe), lint's SealedSecret path. Rewrite the README: secrets section, the "credentials included" claim, the rebuild order (restore NAS → unseal → bootstrap cluster → ArgoCD syncs ESO → secrets appear), and manual OpenBao upgrades.

## Left to the builder

- Exact image and chart versions (latest stable at build time).
- ESO metric names for the not-syncing rule, and how its metrics get scraped (chart ServiceMonitor vs. VMServiceScrape).
- Where each namespace's SA/binding/SecretStore file lives, following the directory's existing layout and how its Application/ApplicationSet picks files up.
- Admin/userpass setup for day-to-day UI use instead of the root token.
