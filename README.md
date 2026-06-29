# talos-homelab

A fully GitOps-driven Kubernetes homelab built on [Talos Linux](https://www.talos.dev/) — declarative, immutable, and self-healing from a single bootstrap command.

![GitOps](https://img.shields.io/badge/GitOps-ArgoCD-orange)
![Kubernetes](https://img.shields.io/badge/Kubernetes-Talos-blue)
![License](https://img.shields.io/badge/License-MIT-green)

---

## Highlights

- **100% GitOps** — every cluster resource is defined in git. No manual `kubectl apply` after bootstrap.
- **Immutable OS** — Talos Linux: no SSH, no shell, API-only node access.
- **Encrypted secrets** — all secrets sealed with [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets), safe to commit.
- **App of Apps pattern** — a single root ArgoCD application manages all others via Kustomize.
- **Sync waves** — infrastructure deployed in strict dependency order automatically.
- **Gateway API** — Traefik as the gateway controller with wildcard TLS.
- **Automatic TLS** — wildcard certificate via cert-manager + Cloudflare DNS-01.
- **Automated updates** — Renovate tracks all Helm charts, container images, and ArgoCD apps.
- **Slack notifications** — ArgoCD notifies on sync failures with rich block messages.

---

## Architecture

A single root application (`bootstrap/talos-cluster.yaml`) is applied once. After that, ArgoCD manages everything from git — including itself.

```
bootstrap/talos-cluster.yaml       ← applied once manually
└── deployments/
    ├── infrastructure/            ← sync waves -5 to -1
    └── apps/                      ← sync wave 0 (default)
```

ArgoCD reconciles every 30 seconds and heals any drift automatically.

---

## Repository Structure

```
.
├── bootstrap/
│   └── talos-cluster.yaml              ← Root ArgoCD app — applied ONCE
├── deployments/
│   ├── kustomization.yaml              ← Points to infrastructure/ and apps/
│   ├── infrastructure/
│   │   ├── kustomization.yaml
│   │   ├── argocd/                     ← ArgoCD (self-managed)
│   │   ├── cert-manager/               ← TLS via Cloudflare DNS-01
│   │   ├── cilium/                     ← CNI + L2 LoadBalancer
│   │   ├── kubelet-serving-cert-approver/
│   │   ├── longhorn/                   ← Distributed block storage
│   │   ├── metrics-server/             ← kubectl top
│   │   ├── sealed-secrets/             ← Secret encryption controller
│   │   └── traefik/                    ← Gateway API controller + TLS
│   └── apps/
│       ├── kustomization.yaml
│       ├── autopulse/                  ← Media scan automation
│       ├── bazarr/                     ← Subtitle manager
│       ├── byparr/                     ← FlareSolverr replacement
│       ├── clonarr/                    ← Trash Guides syncer
│       ├── homepage/                   ← Dashboard
│       ├── jellyfin/                   ← Media server
│       ├── kubeseal-webgui/            ← Sealed Secrets web UI
│       ├── plex/                       ← Media server
│       ├── prowlarr/                   ← Indexer manager
│       ├── qbittorrent/                ← Torrent client
│       ├── radarr/                     ← Movie manager
│       ├── seerr/                      ← Media request manager
│       ├── sonarr/                     ← TV show manager
│       └── unpackerr/                  ← Archive extractor
└── renovate.json                       ← Automated dependency updates
```

---

## Infrastructure

| Component | Version | Namespace | Description |
|---|---|---|---|
| [ArgoCD](https://argo-cd.readthedocs.io/) | 10.0.0 | argocd | GitOps controller |
| [Cilium](https://cilium.io/) | 1.19.5 | kube-system | CNI + L2 LoadBalancer |
| [cert-manager](https://cert-manager.io/) | v1.20.3 | cert-manager | Automatic TLS certificates |
| [Traefik](https://traefik.io/) | 41.0.1 | traefik | Gateway API ingress controller |
| [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) | 2.19.0 | kube-system | Secret encryption |
| [Longhorn](https://longhorn.io/) | 1.12.0 | longhorn-system | Distributed block storage |
| [Metrics Server](https://github.com/kubernetes-sigs/metrics-server) | v0.8.1 | kube-system | Resource metrics |
| [kubelet-serving-cert-approver](https://github.com/alex1989hu/kubelet-serving-cert-approver) | 0.6.1 | kubelet-serving-cert-approver | Auto-approve kubelet TLS CSRs |

### Sync Waves

| Wave | Component | Why |
|---|---|---|
| `-5` | sealed-secrets | Must exist before any SealedSecret is applied |
| `-4` | cilium | CNI must be ready before other networking |
| `-3` | cert-manager, metrics-server | Depends on CNI |
| `-2` | traefik, longhorn | Depends on cert-manager for TLS |
| `-1` | argocd | Self-manages after initial install |
| `0` | apps | Runs after all infrastructure |

---

## Apps

All apps use the [bjw-s/app-template](https://github.com/bjw-s-labs/helm-charts) Helm chart (v5.0.1) except where noted. Existing PVCs are referenced via `existingClaim` to preserve data across redeployments.

| App | Chart | Namespace | Description |
|---|---|---|---|
| [sonarr](https://sonarr.tv/) | app-template | servarr | TV show manager |
| [radarr](https://radarr.video/) | app-template | servarr | Movie manager |
| [bazarr](https://www.bazarr.media/) | app-template | servarr | Subtitle manager |
| [prowlarr](https://prowlarr.com/) | app-template | servarr | Indexer manager |
| [qbittorrent](https://www.qbittorrent.org/) | app-template | servarr | Torrent client |
| [sonarr](https://sonarr.tv/) | app-template | servarr | TV show manager |
| [seerr](https://github.com/seerr-team/seerr) | app-template | servarr | Media request manager |
| [clonarr](https://github.com/prophetse7en/clonarr) | app-template | servarr | Trash Guides syncer |
| [autopulse](https://github.com/dan-online/autopulse) | app-template | servarr | Targeted Plex/Jellyfin scans on import |
| [byparr](https://github.com/thephaseless/byparr) | app-template | servarr | FlareSolverr replacement |
| [unpackerr](https://github.com/davidnewhall/unpackerr) | app-template | servarr | Extracts downloaded archives |
| [jellyfin](https://jellyfin.org/) | jellyfin | media | Open source media server |
| [plex](https://www.plex.tv/) | plex-media-server | media | Media server |
| [homepage](https://gethomepage.dev/) | homepage | homepage | Cluster dashboard |
| [kubeseal-webgui](https://github.com/Mahsad/kubeseal-webgui) | kubeseal-webgui | kubeseal-webgui | Web UI for sealing secrets |

### Media Stack Flow

```
Sonarr/Radarr ──► autopulse ──► Plex  (targeted refresh)
                             └──► Jellyfin (targeted scan)
       │
       └──► prowlarr (indexers)
       └──► qbittorrent (downloads)
       └──► bazarr (subtitles)
       └──► unpackerr (extraction)
```

---

## Networking

### LoadBalancer

Cilium handles `LoadBalancer` services via L2 announcements — no BGP, no MetalLB required.

```yaml
# cilium/loadbalancer-pool.yaml
spec:
  blocks:
    - start: "10.0.0.153"
      stop:  "10.0.0.199"
```

### Gateway API

Traefik is the Gateway controller with two listeners:

| Listener | Port | Protocol |
|---|---|---|
| `web` | 80 | HTTP (redirects to HTTPS) |
| `websecure` | 443 | HTTPS with wildcard TLS |

All apps use `HTTPRoute` resources pointing at `traefik-gateway` in the `traefik` namespace:

```yaml
parentRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: traefik-gateway
    namespace: traefik
    sectionName: websecure
```

### TLS

cert-manager issues and auto-renews a wildcard certificate via Cloudflare DNS-01. The certificate covers `*.talos-cluster.local.obleey.com` and `*.local.obleey.com`.

### DNS Pattern

```
<service>.talos-cluster.local.obleey.com
```

---

## Storage

| StorageClass | Provisioner | Used For |
|---|---|---|
| `longhorn` | `driver.longhorn.io` | App config and state (replicated across nodes) |
| NFS (direct volume) | — | Shared media library, torrent downloads |

Apps with persistent config use a 1Gi Longhorn PVC. The NFS server (`10.0.0.104`) is mounted directly as a volume for the shared media path.

---

## Secrets Management

All secrets are encrypted with Sealed Secrets and committed to git. The private key never leaves the cluster.

```
Plain Secret → kubeseal → SealedSecret (safe to commit)
                                │
                    sealed-secrets controller decrypts
                                │
                         Plain Secret in cluster
```

### Sealing a secret

```bash
kubectl create secret generic my-secret \
  --from-literal=my-key=my-value \
  -n my-namespace \
  --dry-run=client -o yaml \
  | kubeseal --format yaml > deployments/apps/my-app/my-secret-sealed.yaml
```

### Secrets in this repo

| File | Namespace | Contains |
|---|---|---|
| `argocd/git-creds-sealed.yaml` | argocd | GitHub credentials for repo access |
| `cert-manager/cloudflare-api-token-sealed.yaml` | cert-manager | Cloudflare DNS token for TLS |
| `argocd/argocd-notifications-secret-sealed.yaml` | argocd | Slack bot token |
| `autopulse/sealedsecret.yaml` | servarr | Auth credentials + Plex/Jellyfin tokens |
| `homepage/homepage-sealedsecrets.yaml` | homepage | API keys for dashboard widgets |
| `unpackerr/api-tokens-sealed-secret.yaml` | servarr | Sonarr/Radarr API keys |

---

## Notifications

ArgoCD sends Slack notifications on sync failures via rich block messages:

```
┌─────────────────────────────────────────────────┐
│  🔴 Sync Failed — sonarr                        │
├─────────────────────────────────────────────────┤
│  Cluster: talos-cluster  │  Phase: Failed       │
│  Repository: https://bjw-s-labs.github.io/...   │
│  Error: `spec.selector is immutable...`         │
├─────────────────────────────────────────────────┤
│  [Open App]  [Sync Logs]                        │
└─────────────────────────────────────────────────┘
```

Test a notification manually:

```bash
argocd admin notifications template notify app-sync-failed <app-name> \
  --recipient slack:#deployments -n argocd
```

---

## Automated Updates

[Renovate](https://docs.renovatebot.com/) tracks all dependencies and opens PRs automatically:

| Group | What it tracks |
|---|---|
| `helm charts` | All Helm chart versions (Argo, Traefik, Longhorn, etc.) |
| `media stack` | sonarr, radarr, bazarr, prowlarr, qbittorrent images |
| `linuxserver images` | Other linuxserver.io images |
| `ghcr images` | All `ghcr.io/*` images (seerr, clonarr, autopulse, etc.) |
| `docker hub images` | unpackerr and other Docker Hub images |

Major updates get a `major-update` label and are never auto-merged.

---

## Adding a New App

Apps use the bjw-s/app-template multi-source pattern:

```
deployments/apps/my-app/
├── app.yaml               ← ArgoCD Application (multi-source)
├── my-app-values.yaml     ← app-template Helm values
├── httproute.yaml         ← Gateway API route (raw manifest)
└── pvc.yaml               ← Longhorn PVC (raw manifest, if stateful)
```

**app.yaml template:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
  labels:
    argocd.argoproj.io/managed-by: talos-cluster
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  sources:
    - repoURL: https://bjw-s-labs.github.io/helm-charts
      chart: app-template
      targetRevision: 5.0.1
      helm:
        valueFiles:
          - $values/deployments/apps/my-app/my-app-values.yaml
    - repoURL: https://github.com/obleey/talos-homelab
      targetRevision: HEAD
      ref: values
      path: deployments/apps/my-app
      directory:
        exclude: "{app.yaml,my-app-values.yaml}"
  destination:
    server: https://kubernetes.default.svc
    namespace: servarr
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**my-app-values.yaml template:**

```yaml
fullnameOverride: my-app

controllers:
  main:
    type: deployment
    strategy: Recreate
    containers:
      main:
        image:
          repository: ghcr.io/example/my-app
          tag: v1.0.0
        env:
          TZ: Europe/Ljubljana

service:
  app:
    controller: main
    ports:
      http:
        port: 8080

persistence:
  config:
    type: persistentVolumeClaim
    existingClaim: my-app-config
    globalMounts:
      - path: /config
```

Then add to `deployments/apps/kustomization.yaml` and push. ArgoCD picks it up within 30 seconds.

---

## Bootstrap

> One-time process. After this, everything is managed by ArgoCD from git.

### Prerequisites

- `kubectl` configured for your Talos cluster
- `helm` >= 3.x
- `kubeseal` CLI installed
- A private GitHub repo
- Cloudflare account with DNS API access

### Steps

**1. Seal your secrets**

```bash
# Cloudflare API token
kubectl create secret generic cloudflare-api-token \
  --from-literal=api-token=<your-token> \
  -n cert-manager --dry-run=client -o yaml \
  | kubeseal --format yaml \
  > deployments/infrastructure/cert-manager/cloudflare-api-token-sealed.yaml

# GitHub credentials
kubectl create secret generic git-creds \
  --from-literal=username=<github-user> \
  --from-literal=password=<github-pat> \
  -n argocd --dry-run=client -o yaml \
  | kubeseal --format yaml \
  > deployments/infrastructure/argocd/git-creds-sealed.yaml

# Slack token (optional)
kubectl create secret generic argocd-notifications-secret \
  --from-literal=slack-token=<slack-token> \
  -n argocd --dry-run=client -o yaml \
  | kubeseal --format yaml \
  > deployments/infrastructure/argocd/argocd-notifications-secret-sealed.yaml
```

**2. Install ArgoCD**

```bash
helm repo add argo https://argoproj.github.io/argo-helm && helm repo update
kubectl create namespace argocd
helm install argocd argo/argo-cd \
  -n argocd \
  -f deployments/infrastructure/argocd/argocd-values.yaml
```

**3. Apply bootstrap secrets**

```bash
kubectl apply -f deployments/infrastructure/argocd/git-creds-sealed.yaml
```

**4. Apply the root app — the last manual step**

```bash
kubectl apply -f bootstrap/talos-cluster.yaml
```

ArgoCD syncs everything from git automatically from here. Sync waves ensure correct ordering.

---

## Common Operations

```bash
# Check all app sync status
kubectl get applications -n argocd

# Resource usage
kubectl top nodes && kubectl top pods -A

# Seal a new secret
kubectl create secret generic my-secret --from-literal=key=value \
  -n my-namespace --dry-run=client -o yaml \
  | kubeseal --format yaml > path/to/sealed.yaml

# Force ArgoCD to refresh an app
argocd app get <app-name> --hard-refresh

# Test a notification
argocd admin notifications template notify app-sync-failed <app-name> \
  --recipient slack:#deployments -n argocd

# Rebuild cluster from scratch
helm install argocd argo/argo-cd -n argocd \
  -f deployments/infrastructure/argocd/argocd-values.yaml
kubectl apply -f deployments/infrastructure/argocd/git-creds-sealed.yaml
kubectl apply -f bootstrap/talos-cluster.yaml
# ArgoCD restores full cluster state from git
```

---

## Adaptation Checklist

Before deploying on your own cluster:

- [ ] `cilium/loadbalancer-pool.yaml` — IP range for LoadBalancer services
- [ ] `cilium/l2-announcement-policy.yaml` — network interface name (`ip link`)
- [ ] `cilium/cilium-values.yaml` — `k8sServiceHost` and `k8sServicePort`
- [ ] `cert-manager/cert-manager-cluster-issuer.yaml` — domain and email
- [ ] `traefik/wildcard-cert.yaml` — domain names
- [ ] `argocd/argocd-values.yaml` — ArgoCD URL
- [ ] `argocd/argocd-cm.yaml` — ArgoCD URL
- [ ] All `HTTPRoute` manifests — hostnames
- [ ] All `*-values.yaml` — NFS server IP (`10.0.0.104`)
- [ ] `bootstrap/talos-cluster.yaml` — your GitHub repo URL
- [ ] All `app.yaml` files — your GitHub repo URL
- [ ] Re-seal all secrets for your cluster

---

## License

MIT
