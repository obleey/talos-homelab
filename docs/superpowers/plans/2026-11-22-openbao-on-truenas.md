# OpenBao on TrueNAS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Sealed Secrets with OpenBao (on TrueNAS) + External Secrets Operator for all 17 cluster secrets, with sealed/sync alerts, off-site backup and a drilled restore.

**Architecture:** OpenBao runs as a Dockge stack on the NAS (Raft, single node, self-signed TLS, manual Shamir unseal). ESO in the cluster authenticates per namespace with Kubernetes auth and materialises the same Secret names the SealedSecrets produced, so no consumer changes. Migration is staged; each stage merges to `main` (ArgoCD syncs `HEAD`) and is rollbackable from git until the final cleanup.

**Tech Stack:** OpenBao (`bao` CLI, `openbao/openbao` image), External Secrets Operator Helm chart, ArgoCD, Alloy blackbox, Grafana alerting, restic, Python lint (`scripts/lint.py`).

**Spec:** `docs/superpowers/specs/2026-11-22-openbao-on-truenas-design.md`

## Global Constraints

- OpenBao address `https://10.0.0.104:8200`. CA cert committed at `truenas/openbao/ca.crt`. Workstation env: `BAO_ADDR=https://10.0.0.104:8200`, `BAO_CACERT=truenas/openbao/ca.crt`.
- Server cert SANs: `IP:10.0.0.104`, `IP:127.0.0.1`, `DNS:openbao.local.obleey.com`. 5-year validity. The CA private key goes into the password manager, not onto the NAS or into git.
- KV v2 mounted at `secret/`. Path `secret/<namespace>/<secret-name>`. Keys identical to the current Secret's keys.
- Per namespace: policy `<ns>-read` (`read` on `secret/data/<ns>/*`), Kubernetes-auth role `<ns>` (bound SA `openbao-reader`, namespace `<ns>`, TTL `1h`), ServiceAccount `openbao-reader`, ClusterRoleBinding `openbao-reader-<ns>` → `system:auth-delegator`, SecretStore `openbao`.
- Namespaces: `servarr`, `forgejo`, `netbird`, `argocd`, `cert-manager`, `monitoring`.
- ExternalSecret: `apiVersion: external-secrets.io/v1`, `metadata.name` = the replaced Secret's name, `secretStoreRef: {kind: SecretStore, name: openbao}`, explicit `data:` (one entry per key, `remoteRef: {key: <ns>/<secret-name>, property: <key>}`), no `dataFrom`, `refreshInterval: 1h`, `target: {name: <secret-name>, creationPolicy: Owner, deletionPolicy: Retain}`. Copy the SealedSecret template's `type` and `labels` into `target.template`.
- Every SecretStore and ExternalSecret carries the annotation `argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true`. On a fresh bootstrap the CRDs don't exist yet.
- Secret values never appear in git, in commit messages, or in command output. Pipe them, never echo them. Unseal keys, root token, CA key and both restic passwords live in the password manager.
- `bao operator init` is run by Miha in their own terminal (not through the agent), because its output is the unseal keys.
- Commit messages follow the repo's `area: description` style. No Co-Authored-By/Claude lines.
- `scripts/lint.py` and `scripts/test_lint.py` pass after every task that touches `deployments/` or `scripts/`.

## Review Focus

1. **Swap gap / ownership.** Pruning a SealedSecret garbage-collects its Secret before ESO can own the name. A pod restarting in that window fails. Expected: the gap is seconds, and the Secret ends up owned by the ExternalSecret. Pinned by the "data hash unchanged + owner is ExternalSecret + consumer restarts" check in every migration task.
2. **Value fidelity.** Multi-line values (SSH keys, PEM) or trailing newlines get altered on the way through `jq`/`bao kv put`. Expected: byte-identical. Pinned by comparing `jq -S .data | sha256sum` of the Secret before and after the swap.
3. **Missing template metadata.** `argocd-google-oauth` loses its `app.kubernetes.io/part-of: argocd` label and ArgoCD SSO breaks. Pinned in Task 9 with a label selector check.
4. **OpenBao sealed after a NAS reboot.** Expected: existing Secrets stay, the probe alert fires within ~5m, and ESO recovers after unseal without intervention. Pinned in Task 7's drill.
5. **Snapshot token expiry or sealed OpenBao at backup time.** Expected: a Slack failure message, not a silent skip. Pinned in Task 7.

---

### Task 1: OpenBao stack on the NAS

**Files:**
- Create: `truenas/openbao/compose.yaml`, `truenas/openbao/openbao.hcl`, `truenas/openbao/ca.crt`, `truenas/openbao/README.md`

**Interfaces:**
- Produces: a running, initialised, unsealed OpenBao at `https://10.0.0.104:8200`, the container named `openbao`, and the CA at `truenas/openbao/ca.crt`.

- [ ] **Step 1: Create the branch.** `git switch -c openbao`. Commit the spec and this plan as the first commit (`docs: OpenBao on TrueNAS design and plan`).
- [ ] **Step 2: Write `openbao.hcl`.**
  - `storage "raft" { path = "/openbao/data", node_id = "truenas" }`
  - `listener "tcp" { address = "0.0.0.0:8200", tls_cert_file = "/openbao/tls/server.crt", tls_key_file = "/openbao/tls/server.key", telemetry { unauthenticated_metrics_access = false } }`
  - `api_addr = "https://10.0.0.104:8200"`, `cluster_addr = "https://127.0.0.1:8201"` (single node; 8201 is not published)
  - `ui = true`, `disable_mlock = true`
- [ ] **Step 3: Write `compose.yaml`.**
  - Service `openbao`, `container_name: openbao`, image `openbao/openbao:<latest stable, pinned>` with a `# pinned: no Renovate on the NAS` comment, `restart: unless-stopped`.
  - `command: server -config=/openbao/config/openbao.hcl`, ports `8200:8200`.
  - Bind mounts from `/mnt/serve/stacks/openbao/{config(ro),tls(ro),data,audit,snapshots}` to `/openbao/...`.
  - `environment: BAO_ADDR=https://127.0.0.1:8200, BAO_CACERT=/openbao/tls/ca.crt`, so `docker exec openbao bao …` works.
- [ ] **Step 4: Generate the TLS material on the workstation** with `openssl`: a CA (5y), and a server key + cert signed by it with the SANs from Global Constraints. Copy `ca.crt` into `truenas/openbao/`. Put `ca.key` in the password manager and delete it locally.
- [ ] **Step 5: Deploy on the NAS.** Create `/mnt/serve/stacks/openbao/{config,tls,data,audit,snapshots}`. Copy the hcl, compose, `ca.crt`, `server.crt` and `server.key` (mode 600). `chown` `data`, `audit` and `snapshots` to the image's runtime uid (`docker run --rm --entrypoint id openbao/openbao:<tag>`). Start the stack from Dockge.
- [ ] **Step 6: Verify it's up and uninitialised.** Run `bao status` from the workstation with the env from Global Constraints. Expected: `Initialized false`, `Sealed true`, exit code 2, no TLS error.
- [ ] **Step 7: Miha initialises it in their own terminal.** `bao operator init -key-shares=3 -key-threshold=2`. The keys and root token go into the password manager. Then `bao operator unseal` twice.
- [ ] **Step 8: Verify.** `bao status` → `Initialized true`, `Sealed false`, `Storage Type raft`.
- [ ] **Step 9: Write `truenas/openbao/README.md`.** About 15 lines: what lives where on the NAS, how to deploy changes (copy + Dockge redeploy), the unseal procedure, that upgrades are manual (bump the tag, redeploy, unseal), and where the CA key lives.
- [ ] **Step 10: Commit.** `openbao: Dockge stack for TrueNAS (raft, TLS, manual unseal)`

### Task 2: OpenBao configuration as code

**Files:**
- Create: `scripts/openbao-configure.sh`, `scripts/openbao-import.sh`

**Interfaces:**
- Consumes: the running OpenBao from Task 1, and an admin/root token in `BAO_TOKEN`.
- Produces:
  - `scripts/openbao-configure.sh`: idempotent, no args. Sets up the KV v2 mount `secret`, the `kubernetes` auth method, a file audit device, and `<ns>-read` + role `<ns>` for each namespace in `NAMESPACES=(servarr forgejo netbird argocd cert-manager monitoring)` at the top of the file.
  - `scripts/openbao-import.sh <namespace> <secret-name>`: copies a live k8s Secret into `secret/<ns>/<secret-name>` without printing any value.

- [ ] **Step 1: Write `openbao-configure.sh`.** `set -euo pipefail`. Each section checks before creating, so re-runs succeed:
  - `bao secrets list` → enable `kv-v2` at `secret` if missing.
  - `bao auth list` → enable `kubernetes` if missing. Then `bao write auth/kubernetes/config kubernetes_host=https://10.0.0.160:6443 kubernetes_ca_cert=@<(kubectl --context admin@talos-cluster config view --raw --minify -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d)`. No `token_reviewer_jwt`.
  - `bao audit list` → enable `file` with `file_path=/openbao/audit/audit.log` if missing.
  - Per namespace, `bao policy write <ns>-read -` with `path "secret/data/<ns>/*" { capabilities = ["read"] }`, then `bao write auth/kubernetes/role/<ns> bound_service_account_names=openbao-reader bound_service_account_namespaces=<ns> policies=<ns>-read ttl=1h`.
  - `bao policy write snapshot -` with `path "sys/storage/raft/snapshot" { capabilities = ["read"] }`.
- [ ] **Step 2: Write `openbao-import.sh`.** `kubectl --context admin@talos-cluster -n "$1" get secret "$2" -o json | jq '.data | map_values(@base64d)' | bao kv put -mount=secret "$1/$2" -`. Then print only the key names: `bao kv get -mount=secret -format=json "$1/$2" | jq -r '.data.data | keys[]'`.
- [ ] **Step 3: Run the configure script twice.** Expected: both runs exit 0, and the second changes nothing.
- [ ] **Step 4: Verify.** `bao read auth/kubernetes/role/servarr` shows `bound_service_account_names [openbao-reader]` and `policies [servarr-read]`. `bao audit list` shows `file/`.
- [ ] **Step 5: Commit.** `openbao: configure script (kv, kubernetes auth, per-namespace policies) and secret import`

### Task 3: Sealed/down probe

**Files:**
- Modify: `deployments/infrastructure/observability/alloy-blackbox/values.yaml` (modules block near line 16, targets near line 130)

**Interfaces:**
- Produces: `probe_success{job="blackbox", instance="openbao"}`, which the existing blackbox alert covers.

- [ ] **Step 1: Add a module `http_openbao`:** `prober: http`, `timeout: 10s`, `http.valid_status_codes: [200]`, `http.method: GET`, `http.tls_config.insecure_skip_verify: true`.
- [ ] **Step 2: Add the target** `name = "openbao"`, `address = "https://10.0.0.104:8200/v1/sys/health"`, `module = "http_openbao"`, under the "Home network appliances" comment.
- [ ] **Step 3: Run the checks.** `scripts/lint.py && scripts/test_lint.py && scripts/render-check.py`. Expected: exit 0.
- [ ] **Step 4: Merge to main and verify live.** In Grafana Explore, `probe_success{instance="openbao"}` = 1. Then `docker restart openbao` on the NAS (it comes back sealed) → the value drops to 0, and after 5m the blackbox alert reaches Slack with instance `openbao`. Unseal → it resolves.
- [ ] **Step 5: Commit** (before merge). `alloy-blackbox: probe OpenBao health (sealed or down alerts)`

### Task 4: External Secrets Operator

**Files:**
- Create: `deployments/infrastructure/external-secrets/app.yaml`, `deployments/infrastructure/external-secrets/external-secrets-values.yaml`
- Modify: `deployments/infrastructure/kustomization.yaml`, `scripts/lint.py:19` (`CRITICAL`)

**Interfaces:**
- Produces: ESO CRDs (`SecretStore`, `ExternalSecret`, `external-secrets.io/v1`) and controller in namespace `external-secrets`, and ESO metrics scraped through a ServiceMonitor.

- [ ] **Step 1: Write `app.yaml`.** Copy the shape of `sealed-secrets/app.yaml`: annotation `argocd.argoproj.io/sync-wave: "-5"`, chart `external-secrets` from `https://charts.external-secrets.io` pinned to the latest stable, valueFiles `$values/deployments/infrastructure/external-secrets/external-secrets-values.yaml`, destination namespace `external-secrets`, `syncOptions: [CreateNamespace=true, ServerSideApply=true]` (ESO CRDs exceed the client-side annotation limit). No finalizer.
- [ ] **Step 2: Write the values.** `serviceMonitor.enabled: true` (the VM stack's `selectAllByDefault` picks it up).
- [ ] **Step 3: Add `external-secrets/app.yaml`** to `deployments/infrastructure/kustomization.yaml` right after `sealed-secrets/app.yaml`. Add `"external-secrets"` to `CRITICAL` in `scripts/lint.py`.
- [ ] **Step 4: Run the checks.** `scripts/lint.py && scripts/test_lint.py && scripts/render-check.py`. Expected: exit 0.
- [ ] **Step 5: Commit, merge, verify.** `external-secrets: install ESO via ArgoCD`. After sync: `kubectl -n external-secrets get pods` shows all Running, and the `externalsecret_` metric names appear in Grafana Explore.

### Task 5: Lint understands ExternalSecrets, and homepage migrates

**Files:**
- Modify: `scripts/repo.py` (`sealed_keys` → `secret_keys`), `scripts/lint.py` (`secrets`, `homepage`, new `stores` check, docstring), `scripts/test_lint.py` (`CASES`)
- Create: `deployments/apps/openbao-store.yaml`, `deployments/apps/homepage/homepage-externalsecret.yaml`
- Modify: `deployments/apps/kustomization.yaml`
- Delete: `deployments/apps/homepage/homepage-sealedsecrets.yaml`

**Interfaces:**
- Consumes: `scripts/openbao-import.sh` (Task 2) and ESO (Task 4).
- Produces:
  - `Repo.secret_keys() -> dict[str, set[str]]`: `{secret name: keys}` from SealedSecret `encryptedData` plus ExternalSecret `spec.data[].secretKey`, keyed by `spec.target.name` (falling back to `metadata.name`).
  - `stores(repo) -> list[str]`, appended to `CHECKS`. Every later task's ExternalSecret must pass it.
  - The pattern file `openbao-store.yaml`: three docs (ServiceAccount `openbao-reader`, ClusterRoleBinding `openbao-reader-<ns>`, SecretStore `openbao`), reused verbatim per namespace with only `<ns>` changed.

- [ ] **Step 1: Write the store file and the ExternalSecret.**
  - `openbao-store.yaml`: namespace `servarr`. SecretStore `spec.provider.vault`: `server: https://10.0.0.104:8200`, `path: secret`, `version: v2`, `caBundle: <base64 of truenas/openbao/ca.crt>`, `auth.kubernetes: {mountPath: kubernetes, role: servarr, serviceAccountRef: {name: openbao-reader}}`.
  - `homepage-externalsecret.yaml`: name `homepage-secrets`, namespace `servarr`, with the 7 `HOMEPAGE_VAR_*` keys as `data:` entries (remote key `servarr/homepage-secrets`).
  - Add `openbao-store.yaml` to `deployments/apps/kustomization.yaml`. Don't delete the SealedSecret yet.
- [ ] **Step 2: Write the failing test cases** (append to `CASES` in `scripts/test_lint.py`):

```python
(f"{APPS}/homepage/homepage-externalsecret.yaml", "secretKey: HOMEPAGE_VAR_GRAFANA_PASSWORD", "secretKey: HOMEPAGE_VAR_GRAFANA_PASSWD",
 "HOMEPAGE_VAR_GRAFANA_PASSWORD is used"),
(f"{APPS}/homepage/homepage-externalsecret.yaml", "name: openbao", "name: openbaoo", "no SecretStore openbaoo in servarr"),
(f"{APPS}/homepage/homepage-externalsecret.yaml", "  data:", "  dataFrom:", "use data: so key names stay in git"),
```

- [ ] **Step 3: Delete `homepage-sealedsecrets.yaml`** and run `scripts/test_lint.py`. Expected: FAIL. The first case fails because `homepage()` still reads `sealed_keys()`; the second and third because `stores` doesn't exist yet.
- [ ] **Step 4: Implement.**
  - Rename `sealed_keys` → `secret_keys` in `repo.py` and widen it as in Interfaces. Use it in `secrets()` and `homepage()`, and change the error text from "is not in the SealedSecret" to "is not in the secret".
  - Add `stores(repo)`: build the `{(namespace, name)}` set of SecretStores. For each ExternalSecret, report `f"{path}: no SecretStore {name} in {ns}"` when its ref is missing, and `f"{path}: {name} uses dataFrom; use data: so key names stay in git"` when `spec.dataFrom` is set.
  - Add `stores` to `CHECKS` and to the module docstring.
- [ ] **Step 5: Run the tests.** `scripts/lint.py && scripts/test_lint.py && scripts/render-check.py`. Expected: exit 0, `lint self-test: 16 cases ok`.
- [ ] **Step 6: Import the values, then record the baseline.**
  - `scripts/openbao-import.sh servarr homepage-secrets`. Expected: prints the 7 key names.
  - Record the baseline: `kubectl -n servarr get secret homepage-secrets -o json | jq -S .data | sha256sum`.
- [ ] **Step 7: Commit, merge, verify.** `homepage: secrets from OpenBao via ESO; lint reads ExternalSecret keys`. After sync:
  - `kubectl -n servarr get externalsecret homepage-secrets` shows `SecretSynced`, Ready True.
  - The sha256 matches the baseline.
  - `kubectl -n servarr get secret homepage-secrets -o jsonpath='{.metadata.ownerReferences[0].kind}'` = `ExternalSecret`.
  - `kubectl -n servarr rollout restart deploy/homepage` → the pod becomes Ready, and the hub widgets show data.

### Task 6: Not-syncing alert

**Files:**
- Create: `deployments/infrastructure/observability/victoria-metrics-k8s-stack/alerts/grafana-external-secrets-rules.yaml`

**Interfaces:**
- Consumes: ESO metrics (Task 4).
- Produces: a Grafana rule with uid `external-secret-not-ready`.

- [ ] **Step 1: Write the rule.** Copy the structure of `grafana-alloy-rules.yaml`: ConfigMap `grafana-external-secrets-rules`, label `grafana_alert: "1"`, group `external-secrets`, folder = the one `grafana-certmanager-rules.yaml` uses.
  - Query `max by (namespace, name) (externalsecret_status_condition{condition="Ready", status="False"})`, threshold `gt 0`, `for: 15m`, `noDataState: OK`, `severity: warning`.
  - summary `"ExternalSecret {{ $labels.namespace }}/{{ $labels.name }} not syncing"`.
  - description: OpenBao sealed/unreachable or a key is missing in `secret/{{ $labels.namespace }}`; the existing Secret is kept (deletionPolicy Retain).
  - No dashboard annotations.
- [ ] **Step 2: Run the checks.** `scripts/lint.py && scripts/test_lint.py`. Expected: exit 0.
- [ ] **Step 3: Commit, merge, verify.** `alerts: ExternalSecret not syncing`. In Grafana → Alerting, the rule exists and is Normal. The firing path is exercised in Task 7.

### Task 7: Backup, audit shipping, and restore drill

**Files (on the NAS, not in git):** `/mnt/serve/stacks/restic_cron/backup.sh`, `/mnt/serve/stacks/restic_cron/openbao-token`, `/mnt/serve/stacks/alloy-truenas/alloy.conf`
**Files (git):** Modify `truenas/openbao/README.md` (backup and drill sections)

**Interfaces:**
- Consumes: the `snapshot` policy (Task 2).
- Produces: a nightly restic snapshot tagged `openbao` on the Storage Box, and OpenBao audit logs in VictoriaLogs with `job="openbao-audit"`.

- [ ] **Step 1: Create the snapshot token.**
  - `bao token create -orphan -policy=snapshot -period=768h -field=token` piped straight into `/mnt/serve/stacks/restic_cron/openbao-token` (root:root, 600). Don't echo it.
  - Back up `backup.sh` to `backup.sh.bak-2026-11-22` first, then edit it.
- [ ] **Step 2: Add an `openbao` step before the Miha run.**
  - `T=$(cat …/openbao-token)`, then `docker exec -e BAO_TOKEN="$T" openbao bao token renew >/dev/null && docker exec -e BAO_TOKEN="$T" openbao bao operator raft snapshot save /openbao/snapshots/openbao.snap`.
  - On non-zero, `report openbao 1` and skip the restic call. Otherwise run `restic … backup /mnt/serve/stacks/openbao/snapshots --tag openbao` and `report openbao "${PIPESTATUS[0]}"`.
- [ ] **Step 3: Verify both paths.** Run `backup.sh` → Slack shows `Restic backup OK — truenas openbao`. Then seal OpenBao (`bao operator seal`) and run only the openbao step → Slack shows `FAILED — truenas openbao`. Unseal again.
- [ ] **Step 4: Ship the audit log.** In `alloy.conf`, add `local.file_match` for `/rootfs/mnt/serve/stacks/openbao/audit/audit.log` with label `job="openbao-audit"`, then `loki.source.file` → the existing `loki.write` receiver. Redeploy alloy-truenas. Verify in Grafana Explore that `{job="openbao-audit"}` returns entries. *(ponytail: no log rotation, a few KB/day at 17 secrets × hourly refresh; add logrotate + SIGHUP if it grows.)*
- [ ] **Step 5: Restore drill.**
  - Start a throwaway container on the NAS: `openbao/openbao:<same tag>`, its own empty raft dir, TLS off, a different port.
  - `init -key-shares=1 -key-threshold=1`, unseal, then `bao operator raft snapshot restore -force` with the latest `openbao.snap`.
  - It's now sealed with the original keyring → unseal with 2 of the real keys.
  - Expected: `bao kv get -mount=secret -field=HOMEPAGE_VAR_GRAFANA_USERNAME servarr/homepage-secrets` exits 0 (pipe it to `wc -c`; don't print the value).
  - Remove the container and its dir.
- [ ] **Step 6: Reboot-resilience drill.**
  - `docker restart openbao` (sealed) and wait 20m.
  - Expected: `kubectl -n servarr get secret homepage-secrets` still exists, and both the blackbox alert and `external-secret-not-ready` reach Slack.
  - Unseal. Expected: both resolve without touching the cluster.
- [ ] **Step 7: Document and commit.** Write the backup, restore and reboot procedures (Steps 2, 5, 6) into `truenas/openbao/README.md`. Commit `openbao: backup, audit shipping and restore drill docs`.

### Task 8: Migrate app secrets

**Files:**
- Create: `deployments/apps/forgejo/openbao-store.yaml`, `deployments/infrastructure/netbird/openbao-store.yaml`. One ExternalSecret file next to each SealedSecret, named by replacing `-sealed.yaml` with `-externalsecret.yaml`. `autopulse/sealedsecret.yaml` → `autopulse/externalsecret.yaml`.
- Delete: `deployments/apps/servarr-credentials-sealed.yaml` (replace it in `deployments/apps/kustomization.yaml` with `servarr-credentials-externalsecret.yaml`), `autopulse/sealedsecret.yaml`, `unpackerr/unpackerr-ui-sealed.yaml`, `forgejo/forgejo-{admin,smtp,runner,restic}-sealed.yaml`, `netbird/netbird-mgmt-api-key-sealed.yaml`.

**Interfaces:**
- Consumes: the `openbao-store.yaml` pattern and the ExternalSecret shape (Task 5), and `scripts/openbao-import.sh` (Task 2).

Do the procedure below once per namespace group, as separate commits in this order: `servarr` (servarr-credentials, autopulse-secret, unpackerr-ui), `forgejo` (4 secrets), `netbird` (1).

- [ ] **Step 1: Check the password manager.** Confirm `forgejo-restic`'s values are in it (anti-goal: no restic password only in OpenBao). If they aren't, `kubectl get secret` them into the password manager first.
- [ ] **Step 2: Import and record baselines.** Run `scripts/openbao-import.sh <ns> <secret>` for each secret in the group. Record each Secret's `jq -S .data | sha256sum` baseline.
- [ ] **Step 3: Write the files.** Write the store file (if the namespace has none) and the ExternalSecrets with every key listed (copy the key names from `encryptedData`, plus `type` from the template). Delete the SealedSecrets.
- [ ] **Step 4: Run the checks.** `scripts/lint.py && scripts/test_lint.py && scripts/render-check.py`. Expected: exit 0. `secrets()` still validates the `secretKeyRef`s into `servarr-credentials`, since its keys now come from the ExternalSecret.
- [ ] **Step 5: Commit, merge, verify.** `<ns>: secrets from OpenBao via ESO`. For each secret:
  - the ExternalSecret is Ready;
  - the sha256 matches its baseline;
  - the owner is `ExternalSecret`;
  - one consumer is restarted: `rollout restart` of sonarr (servarr-credentials), autopulse, unpackerr, forgejo and its runner, and the netbird routing peer. Each becomes Ready.

### Task 9: Migrate infra secrets

**Files:**
- Create: `openbao-store.yaml` in `deployments/infrastructure/argocd/`, `deployments/infrastructure/cert-manager/` and `deployments/infrastructure/observability/victoria-metrics-k8s-stack/`. This last one also serves `victoria-logs/`, which is in the same `monitoring` namespace.
- Create/Delete: an ExternalSecret replacing each of `argocd-google-oauth`, `argocd-notifications-secret`, `cloudflare-api-token`, `prometheus-basic-auth`, `grafana-google-oauth`, `kps-grafana`, `grafana-slack-token`, `loki-basic-auth`. Same file naming as Task 8.

**Interfaces:**
- Consumes: same as Task 8.

Same procedure as Task 8, in the order `cert-manager`, `monitoring`, `argocd`. ArgoCD goes last, so a mistake there is fixed with everything else already proven.

- [ ] **Step 1: Import, record baselines, write the files, delete the SealedSecrets** (Task 8 Steps 2–3). `argocd-google-oauth`'s `target.template.metadata.labels` carries `app.kubernetes.io/part-of: argocd`. `argocd-notifications-secret` keeps `type: Opaque`.
- [ ] **Step 2: Run the checks.** `scripts/lint.py && scripts/test_lint.py && scripts/render-check.py`. Expected: exit 0.
- [ ] **Step 3: Commit, merge, verify per namespace.** Ready, sha256 equal, and owner ExternalSecret as before, plus:
  - cert-manager: `kubectl -n cert-manager rollout restart deploy/cert-manager`, then `kubectl get certificate -A` all Ready.
  - monitoring: restart Grafana → log in via Google works. A test alert from Grafana's contact point reaches Slack. Helion's pushes are still accepted (`up{instance="helion"}` or its push metric still updating).
  - argocd: `kubectl -n argocd get secret -l app.kubernetes.io/part-of=argocd -o name` includes `argocd-google-oauth`. Google SSO login to ArgoCD works. An ArgoCD notification reaches Slack (e.g. a manual sync of a small app).

### Task 10: Remove Sealed Secrets, rewrite the README

**Files:**
- Delete: `deployments/infrastructure/sealed-secrets/`, `deployments/apps/kubeseal-webgui/`
- Modify:
  - `deployments/infrastructure/kustomization.yaml` and `deployments/apps/kustomization.yaml` (drop their entries);
  - `alloy-blackbox/values.yaml` (drop the `kubeseal` target);
  - `deployments/infrastructure/observability/victoria-metrics-k8s-stack/dashboards/grafana-dashboard-blackbox.yaml` (drop the `kubeseal` option in the instance variable);
  - `deployments/apps/homepage/homepage-values.yaml` (drop the kubeseal entry if present);
  - `scripts/repo.py` (`secret_keys` drops the SealedSecret half), `scripts/lint.py` (`CRITICAL` drops `sealed-secrets`, docstring wording);
  - `README.md`.

**Interfaces:**
- Consumes: every secret has migrated. `rtk grep -rl "kind: SealedSecret" deployments` returns nothing.

- [ ] **Step 1: Verify nothing is left.** `grep -rl "kind: SealedSecret" deployments` returns nothing, and `kubectl get sealedsecrets -A` returns nothing.
- [ ] **Step 2: Back up the sealing key one last time.** `kubectl -n kube-system get secret -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml` piped into the password manager as an attachment. This is the only way back to old git history's secrets.
- [ ] **Step 3: Delete and edit the files listed above.**
- [ ] **Step 4: Rewrite the README.**
  - Replace the Sealed Secrets bullets ("Secrets in Git", the platform table, tools on your workstation: `kubeseal` → `bao`).
  - Rewrite "4. Seal your secrets" into "Put your secrets in OpenBao" (`scripts/openbao-configure.sh`, `scripts/openbao-import.sh` or `bao kv put`), and the secrets table header.
  - Rewrite the rebuild path: restore the NAS stack and data → unseal → bootstrap the cluster → ArgoCD installs ESO → secrets appear.
  - Link `truenas/openbao/README.md` for unseal, backups and manual upgrades.
  - Drop kubeseal-webgui mentions (lines ~35, 51, 183, 216: the "copy kubeseal-webgui/" example becomes "copy forgejo/").
- [ ] **Step 5: Run the checks.** `scripts/lint.py && scripts/test_lint.py && scripts/render-check.py`. Expected: exit 0. The `test_lint.py` case count is unchanged.
- [ ] **Step 6: Commit, merge, verify.** `sealed-secrets: remove; OpenBao + ESO is the only secrets path`. After sync: the `sealed-secrets` and `kubeseal-webgui` Applications are gone, and all ExternalSecrets are Ready (`kubectl get externalsecret -A`). No blackbox alert for `kubeseal`.
