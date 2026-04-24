# 🏠 talos-homelab

> A production-grade, fully GitOps-driven Kubernetes homelab built on [Talos Linux](https://www.talos.dev/) — declarative, immutable, and reproducible from a single `kubectl apply`.

![GitOps](https://img.shields.io/badge/GitOps-ArgoCD-orange)
![Kubernetes](https://img.shields.io/badge/Kubernetes-v1.35-blue)
![Talos](https://img.shields.io/badge/OS-Talos%20Linux-purple)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ Highlights

- **100% GitOps** — every cluster resource is defined in git. No manual `kubectl apply` after bootstrap.
- **Immutable OS** — Talos Linux: no SSH, no shell, API-only access.
- **Encrypted secrets** — all secrets are sealed with [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) and safe to commit.
- **App of Apps pattern** — a single root ArgoCD application manages all others via Kustomize.
- **Sync waves** — infrastructure components are applied in dependency order automatically.
- **Gateway API** — modern Kubernetes networking with Traefik as the gateway controller.
- **Automatic TLS** — wildcard certificates via cert-manager + Cloudflare DNS-01 challenge.
- **Slack notifications** — ArgoCD notifies on sync failures.

---

## 📐 Architecture

The repo follows the App of Apps pattern. A single root application (`bootstrap/talos-cluster.yaml`) is applied once manually. After that, ArgoCD manages everything from git — including itself.

```
bootstrap/talos-cluster.yaml  ← applied once
└── deployments/
    ├── infrastructure/        sync waves -5 to -1
    └── apps/                  sync wave 0+
```

ArgoCD polls the repo every 30 seconds and reconciles any drift automatically.

### Cluster Layout

| Node            | Role          | Label      |
| --------------- | ------------- | ---------- |
| `talos-3sw-0t2` | control-plane | `node=c-1` |
| `talos-0z8-aw8` | worker        | `node=w-1` |
| `talos-xxc-2bm` | worker        | `node=w-2` |

> **Adapt this:** Change node names and labels to match your own Talos node hostnames.

---

## 🗂️ Repository Structure

```
.
├── bootstrap/
│   └── talos-cluster.yaml           ← Root ArgoCD app — applied ONCE manually
├── deployments/
│   ├── kustomization.yaml           ← Points to infrastructure/ and apps/
│   ├── infrastructure/              ← Cluster-level components
│   │   ├── kustomization.yaml
│   │   ├── argocd/                  ← ArgoCD manages itself
│   │   ├── cert-manager/            ← TLS via Cloudflare DNS-01
│   │   ├── cilium/                  ← CNI + L2 LoadBalancer
│   │   ├── metrics-server/          ← Resource metrics
│   │   ├── sealed-secrets/          ← Secret encryption controller
│   │   ├── storageclasses/          ← NFS + local-path storage
│   │   └── traefik/                 ← Gateway API controller
│   └── apps/                        ← Workloads
│       ├── kustomization.yaml
│       ├── autopulse/               ← Media server scan automation
│       ├── bazarr/                  ← Subtitle manager
│       └── kubeseal-webgui/         ← Sealed Secrets web UI
└── README.md
```

---

## ⚙️ Infrastructure Components

| Component                                                                   | Chart Version | Namespace          | Description                                    |
| --------------------------------------------------------------------------- | ------------- | ------------------ | ---------------------------------------------- |
| [ArgoCD](https://argo-cd.readthedocs.io/)                                   | 9.4.12        | argocd             | GitOps controller                              |
| [Cilium](https://cilium.io/)                                                | 1.19.2        | kube-system        | CNI + LoadBalancer via L2                      |
| [cert-manager](https://cert-manager.io/)                                    | v1.20.0       | cert-manager       | Automatic TLS certificates                     |
| [Traefik](https://traefik.io/)                                              | 39.0.7        | traefik            | Gateway API ingress controller                 |
| [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets)            | 2.18.4        | kube-system        | Secret encryption                              |
| [Metrics Server](https://github.com/kubernetes-sigs/metrics-server)         | v0.8.1        | kube-system        | Resource metrics (`kubectl top`)               |
| [CSI Driver NFS](https://github.com/kubernetes-csi/csi-driver-nfs)          | v4.12.1       | kube-system        | NFS storage provisioner                        |
| [Local Path Provisioner](https://github.com/rancher/local-path-provisioner) | v0.0.35       | local-path-storage | Node-local storage                             |
| [Longhorn](https://longhorn.io/)                                            | —             | longhorn-system    | Distributed block storage for app config/state |

---

## 📺 Apps

| App                                                          | Namespace | Version | Description                                                                     |
| ------------------------------------------------------------ | --------- | ------- | ------------------------------------------------------------------------------- |
| [autopulse](https://github.com/dan-online/autopulse)         | servarr   | v1.6.0  | Webhook receiver from Sonarr/Radarr → targeted library scans in Plex + Jellyfin |
| [bazarr](https://www.bazarr.media/)                          | servarr   | 1.5.6   | Subtitle manager for Sonarr/Radarr                                              |
| [kubeseal-webgui](https://github.com/Mahsad/kubeseal-webgui) | —         | —       | Web UI for sealing secrets                                                      |

### autopulse

autopulse replaces autoscan. It receives webhooks from Sonarr and Radarr when media is downloaded or upgraded, then sends targeted refresh requests directly to Plex and Jellyfin — no full library scans needed.

```
Sonarr/Radarr → webhook → autopulse → Plex  (targeted metadata refresh)
                                    → Jellyfin (targeted library scan)
```

**Stack layout:**

```
deployments/apps/autopulse/
├── app.yaml              ← ArgoCD Application manifest
├── pvc.yaml              ← 1Gi Longhorn PVC for SQLite DB + config
├── configmap.yaml        ← config.yaml (no secrets — tokens injected via env vars)
├── sealedsecret.yaml     ← auth credentials + Plex/Jellyfin tokens
├── deployment.yaml       ← autopulse v1.6.0-sqlite
├── deployment-ui.yaml    ← autopulse UI
├── services.yaml         ← ClusterIP services for API (:2875) + UI (:3000)
└── httproutes.yaml       ← HTTPRoutes via traefik-gateway (websecure)
```

**Sonarr/Radarr webhook config:**

| Field    | Value                                                             |
| -------- | ----------------------------------------------------------------- |
| URL      | `http://autopulse.servarr.svc.cluster.local:2875/triggers/sonarr` |
| Method   | POST                                                              |
| Triggers | On Import, On Upgrade, On Rename                                  |
| Auth     | Basic — credentials from sealed secret                            |

**Hostnames:**

| Service       | URL                                                   |
| ------------- | ----------------------------------------------------- |
| autopulse API | `https://autopulse.talos-cluster.local.obleey.com`    |
| autopulse UI  | `https://autopulse-ui.talos-cluster.local.obleey.com` |

---

## 🔄 Sync Waves

ArgoCD applies resources in dependency order using sync waves:

| Wave | Component                                    | Why                                            |
| ---- | -------------------------------------------- | ---------------------------------------------- |
| `-5` | sealed-secrets                               | Must exist before any sealed secret is applied |
| `-4` | cilium                                       | CNI must be ready before other networking      |
| `-3` | cert-manager, metrics-server, storageclasses | Depends on CNI                                 |
| `-2` | traefik                                      | Depends on cert-manager for TLS                |
| `-1` | argocd                                       | Self-manages after initial install             |
| `0`  | apps                                         | Default, runs after all infrastructure         |

---

## 🌐 Networking

### LoadBalancer IP Pool

Cilium handles `LoadBalancer` type services using L2 announcements — no BGP, no MetalLB required.

```yaml
# cilium/loadbalancer-pool.yaml
spec:
  blocks:
    - start: "10.0.0.153" # ← Change to your IP range start
      stop: "10.0.0.199" # ← Change to your IP range end
```

```yaml
# cilium/l2-announcement-policy.yaml
spec:
  interfaces:
    - ens18 # ← Change to your network interface (run: ip link)
```

> **Adapt this:** Run `ip link` on your nodes to find the correct interface name. Update the IP range to match your home network subnet.

### Gateway API

Traefik is configured as a Gateway API controller with two listeners:

| Listener    | Port | Protocol                |
| ----------- | ---- | ----------------------- |
| `web`       | 80   | HTTP                    |
| `websecure` | 443  | HTTPS with wildcard TLS |

All apps use `HTTPRoute` resources pointing at `traefik-gateway` in the `traefik` namespace:

```yaml
parentRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: traefik-gateway
    namespace: traefik
    sectionName: websecure
```

### TLS Certificates

cert-manager automatically issues and renews a wildcard certificate using Cloudflare DNS-01.

> **Adapt this:** Replace `local.obleey.com` with your own domain in `cert-manager-cluster-issuer.yaml`. You need a Cloudflare API token with DNS:Edit permission. Seal the token before committing.

### DNS Pattern

All services follow: `<service>.<cluster-name>.<your-domain>`

> **Adapt this:** Replace the domain everywhere — `argocd-values.yaml` and all `HTTPRoute` manifests.

---

## 💾 Storage

| StorageClass | Provisioner             | Default | Use For                                 |
| ------------ | ----------------------- | ------- | --------------------------------------- |
| `local-path` | `rancher.io/local-path` | ✅      | Single-node workloads                   |
| `nfs-client` | `nfs.csi.k8s.io`        | ❌      | Shared storage, media                   |
| `longhorn`   | `driver.longhorn.io`    | ❌      | App config, databases, replicated state |

### NFS Configuration

```yaml
# storageclasses/nfs-storageclass.yaml
parameters:
  server: 10.0.0.23 # ← Change to your NFS server IP
  share: /serve/k8s # ← Change to your NFS export path
```

> **Adapt this:** Update the NFS server IP and share path. If you have no NFS server, remove `nfs-storageclass.yaml` and the `csi-driver-nfs` source from `storageclasses/app.yaml`.

### Longhorn

Longhorn provides replicated block storage across worker nodes. Used for app config volumes (e.g. autopulse SQLite DB) where data needs to survive node failures without NFS.

---

## 🔐 Secrets Management

All secrets are encrypted with Sealed Secrets and committed to git. The private key never leaves the cluster.

### How it works

```
Plain Secret  →  kubeseal  →  SealedSecret (safe to commit to git)
                                      |
                          sealed-secrets controller decrypts
                                      |
                               Plain Secret in cluster
```

### Sealing a new secret

```bash
# 1. Create a raw secret — never commit this file
kubectl create secret generic my-secret \
  --dry-run=client \
  --from-literal=my-key=my-value \
  -n my-namespace -o yaml > /tmp/my-secret.yaml

# 2. Seal it with the cluster's public key
kubeseal -f /tmp/my-secret.yaml \
  -w deployments/apps/my-app/my-secret-sealed.yaml

# 3. Commit the sealed secret safely
git add deployments/apps/my-app/my-secret-sealed.yaml
git commit -m "feat: add sealed secret for my-app"
git push
```

### Migrating secrets between clusters

Sealed secrets are **cluster-specific** — you cannot copy a SealedSecret from one cluster to another. You must re-seal:

```bash
# Get raw secret from old cluster
kubectl get secret my-secret -n my-namespace --context old-cluster -o yaml \
  | grep -v 'resourceVersion\|uid\|creationTimestamp\|managedFields' \
  > /tmp/raw-secret.yaml

# Seal for the new cluster (ensure kubeseal points to new cluster)
kubeseal -f /tmp/raw-secret.yaml -w sealed-secret.yaml
```

### Secrets in this repo

| Secret                                    | Namespace    | Contains                                              |
| ----------------------------------------- | ------------ | ----------------------------------------------------- |
| `git-creds-sealed.yaml`                   | argocd       | GitHub credentials for repo access                    |
| `cloudflare-api-token-sealed.yaml`        | cert-manager | Cloudflare DNS token for TLS                          |
| `argocd-notifications-secret-sealed.yaml` | argocd       | Slack bot token                                       |
| `mount-options-sealed.yaml`               | kube-system  | NFS mount options                                     |
| `sealedsecret.yaml`                       | servarr      | autopulse auth credentials + Plex/Jellyfin API tokens |

---

## 🚀 Bootstrap

> One-time process. After this, everything is managed by ArgoCD from git.

### Prerequisites

- `kubectl` configured for your Talos cluster
- `helm` >= 3.x
- `kubeseal` CLI installed
- A private GitHub repo
- Cloudflare account with DNS API access
- Slack bot token (optional)

### Steps

**1. Clone and configure**

```bash
git clone https://github.com/obleey/talos-homelab
cd talos-homelab
```

Work through the adaptation checklist at the bottom of this README before proceeding.

**2. Seal your secrets**

```bash
# Cloudflare API token
kubectl create secret generic cloudflare-api-token \
  --dry-run=client \
  --from-literal=api-token=<your-token> \
  -n cert-manager -o yaml | \
  kubeseal -w deployments/infrastructure/cert-manager/cloudflare-api-token-sealed.yaml

# GitHub credentials
kubectl create secret generic git-creds \
  --dry-run=client \
  --from-literal=username=<github-user> \
  --from-literal=password=<github-pat> \
  -n argocd -o yaml | \
  kubeseal -w deployments/infrastructure/argocd/git-creds-sealed.yaml

# Slack token (optional)
kubectl create secret generic argocd-notifications-secret \
  --dry-run=client \
  --from-literal=slack-token=<slack-token> \
  -n argocd -o yaml | \
  kubeseal -w deployments/infrastructure/argocd/argocd-notifications-secret-sealed.yaml

# autopulse credentials + media server tokens
kubectl create secret generic autopulse-secret \
  --namespace servarr \
  --from-literal=AUTOPULSE__AUTH__USERNAME=<username> \
  --from-literal=AUTOPULSE__AUTH__PASSWORD=<password> \
  --from-literal=PLEX_TOKEN=<plex-token> \
  --from-literal=JELLYFIN_TOKEN=<jellyfin-token> \
  --dry-run=client -o yaml | \
  kubeseal --format yaml > deployments/apps/autopulse/sealedsecret.yaml
```

**3. Install ArgoCD**

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
kubectl create namespace argocd
helm install argocd argo/argo-cd \
  -n argocd \
  -f deployments/infrastructure/argocd/argocd-values.yaml
```

**4. Apply bootstrap secrets and httproute**

```bash
kubectl apply -f deployments/infrastructure/argocd/git-creds-sealed.yaml
kubectl apply -f deployments/infrastructure/argocd/argocd-httproute.yaml
```

**5. Apply the root app — this is the last manual step ever**

```bash
kubectl apply -f bootstrap/talos-cluster.yaml
```

**6. Sync apps in order via ArgoCD UI**

Open ArgoCD at `https://argocd.<your-domain>` and sync in this order:

1. `sealed-secrets`
2. `cilium`
3. `cert-manager`
4. `traefik`
5. `argocd`
6. `metrics-server`
7. `storageclasses`

Everything is automatic from here. ✅

---

## 📦 Adding a New App

Every app follows the same pattern:

```
deployments/apps/my-app/
├── app.yaml              ← ArgoCD Application manifest
├── deployment.yaml       ← Workload
├── service.yaml          ← ClusterIP service
├── httproute.yaml        ← Gateway API route
├── pvc.yaml              ← Longhorn PVC (if stateful)
└── sealedsecret.yaml     ← Sealed secrets (if needed)
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
  source:
    repoURL: https://github.com/obleey/talos-homelab
    targetRevision: HEAD
    path: deployments/apps/my-app
    directory:
      exclude: "{app.yaml}"
  destination:
    server: https://kubernetes.default.svc
    namespace: my-namespace
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

Add to `deployments/apps/kustomization.yaml` and push. ArgoCD picks it up within 30 seconds.

---

## 🔔 Notifications

ArgoCD sends Slack notifications on sync failures.

```
🔴 [TALOS-CLUSTER] MY-APP sync failed!
Repo: https://github.com/obleey/talos-homelab
Error: <error details>
```

> **Adapt this:** Update the cluster name in `argocd-values.yaml` notifications template. Replace the Slack channel with your own.

---

## 🛠️ Common Operations

```bash
# Check sync status of all apps
kubectl get applications -n argocd

# View resource usage
kubectl top nodes
kubectl top pods -A

# Seal a new secret
kubeseal -f /tmp/secret.yaml -w deployments/apps/my-app/sealed-secret.yaml

# Tail autopulse logs
kubectl logs -f -n servarr deploy/autopulse

# Restart autopulse after config change
kubectl rollout restart -n servarr deployment/autopulse

# Edit autopulse config live
kubectl edit configmap autopulse-config -n servarr

# Rebuild cluster from scratch (everything is in git)
helm install argocd argo/argo-cd -n argocd \
  -f deployments/infrastructure/argocd/argocd-values.yaml
kubectl apply -f deployments/infrastructure/argocd/git-creds-sealed.yaml
kubectl apply -f bootstrap/talos-cluster.yaml
# Done — ArgoCD restores the full cluster state from git
```

---

## 📋 Adaptation Checklist

Before deploying to your own cluster, update these files:

- [ ] `cilium/loadbalancer-pool.yaml` — IP range for LoadBalancer services
- [ ] `cilium/l2-announcement-policy.yaml` — network interface name
- [ ] `cilium/cilium-values.yaml` — `k8sServiceHost` and `k8sServicePort`
- [ ] `cert-manager/cert-manager-cluster-issuer.yaml` — domain and email
- [ ] `argocd/argocd-values.yaml` — ArgoCD URL and cluster name in notifications
- [ ] `argocd/argocd-httproute.yaml` — hostname
- [ ] `traefik/traefik-values.yaml` — certificate secret name and listener ports
- [ ] `traefik/traefik-dashboard-route.yaml` — hostname
- [ ] `storageclasses/nfs-storageclass.yaml` — NFS server IP and share path
- [ ] All `HTTPRoute` manifests — hostnames
- [ ] `bootstrap/talos-cluster.yaml` — your GitHub repo URL
- [ ] All `app.yaml` files — your GitHub repo URL
- [ ] Re-seal all secrets for your cluster

---

## 📄 License

MIT
