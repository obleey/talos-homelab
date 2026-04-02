# 🏠 talos-homelab

A GitOps-driven Kubernetes homelab running on [Talos Linux](https://www.talos.dev/), managed by [ArgoCD](https://argo-cd.readthedocs.io/).

---

## 📐 Architecture

### Cluster
- **OS**: Talos Linux
- **Nodes**: 1 control-plane (`c-1`), 2 workers (`w-1`, `w-2`)
- **CNI**: Cilium (with L2 announcements + LoadBalancer IP pool)
- **GitOps**: ArgoCD (App of Apps pattern)

### App of Apps Pattern
```
bootstrap/talos-cluster.yaml     ← applied once manually
└── deployments/
    ├── infrastructure/          ← cluster-level components (sync waves -5 to -1)
    └── apps/                    ← workloads (sync wave 0+)
```

---

## 🗂️ Repository Structure

```
.
├── bootstrap/
│   └── talos-cluster.yaml           ← Root ArgoCD app, applied once
├── deployments/
│   ├── kustomization.yaml           ← Top-level kustomization
│   ├── infrastructure/
│   │   ├── kustomization.yaml       ← Infrastructure kustomization
│   │   ├── argocd/                  ← ArgoCD (manages itself)
│   │   │   ├── app.yaml
│   │   │   ├── argocd-values.yaml
│   │   │   ├── argocd-httproute.yaml
│   │   │   ├── argocd-notifications-secret-sealed.yaml
│   │   │   └── git-creds-sealed.yaml
│   │   ├── cert-manager/            ← TLS certificate management
│   │   │   ├── app.yaml
│   │   │   ├── cert-manager-values.yaml
│   │   │   ├── cert-manager-cluster-issuer.yaml
│   │   │   └── cloudflare-api-token-sealed.yaml
│   │   ├── cilium/                  ← CNI + LoadBalancer
│   │   │   ├── app.yaml
│   │   │   ├── cilium-values.yaml
│   │   │   ├── l2-announcement-policy.yaml
│   │   │   └── loadbalancer-pool.yaml
│   │   ├── metrics-server/          ← Kubernetes metrics
│   │   │   ├── app.yaml
│   │   │   └── metrics-server.yaml
│   │   ├── sealed-secrets/          ← Secret encryption controller
│   │   │   ├── app.yaml
│   │   │   └── sealed-secrets-values.yaml
│   │   ├── storageclasses/          ← Storage provisioners
│   │   │   ├── app.yaml
│   │   │   ├── csi-driver-nfs-values.yaml
│   │   │   ├── local-path-provisioner.yaml
│   │   │   ├── nfs-storageclass.yaml
│   │   │   └── mount-options-sealed.yaml
│   │   └── traefik/                 ← Ingress / Gateway
│   │       ├── app.yaml
│   │       ├── traefik-values.yaml
│   │       ├── traefik-dashboard-route.yaml
│   │       └── traefik-redirect-route.yaml
│   └── apps/
│       ├── kustomization.yaml
│       └── kubeseal-webgui/         ← Sealed Secrets Web UI
└── README.md
```

---

## ⚙️ Infrastructure Components

| Component | Version | Namespace | Description |
|-----------|---------|-----------|-------------|
| ArgoCD | 9.4.12 | argocd | GitOps controller |
| Cilium | 1.19.2 | kube-system | CNI + LoadBalancer |
| cert-manager | v1.20.0 | cert-manager | TLS certificates via Cloudflare DNS |
| Traefik | 39.0.7 | traefik | Gateway API ingress |
| Sealed Secrets | 2.18.4 | kube-system | Secret encryption |
| Metrics Server | v0.8.1 | kube-system | Resource metrics |
| CSI Driver NFS | v4.12.1 | kube-system | NFS storage provisioner |
| Local Path Provisioner | v0.0.35 | local-path-storage | Local storage provisioner |

---

## 🔄 Sync Waves

Resources are applied in order using ArgoCD sync waves:

| Wave | Component |
|------|-----------|
| `-5` | sealed-secrets |
| `-4` | cilium |
| `-3` | cert-manager, metrics-server, storageclasses |
| `-2` | traefik |
| `-1` | argocd |
| `0` | apps (default) |

---

## 🌐 Networking

### LoadBalancer IP Pool
Cilium manages LoadBalancer IPs in the range `10.0.0.153 - 10.0.0.199` via L2 announcements on interface `ens18`.

### Gateway API
Traefik is configured as a Gateway API controller with:
- `web` listener on port 80 (HTTP)
- `websecure` listener on port 443 (HTTPS) with wildcard TLS certificate

### DNS
All services use the pattern: `<service>.talos-cluster.local.obleey.com`

### Services

| Service | URL |
|---------|-----|
| ArgoCD | https://argocd.talos-cluster.local.obleey.com |
| Traefik Dashboard | https://traefik.talos-cluster.local.obleey.com |

---

## 💾 Storage

| StorageClass | Provisioner | Default | ReclaimPolicy |
|--------------|-------------|---------|---------------|
| `local-path` | rancher.io/local-path | ✅ | Delete |
| `nfs-client` | nfs.csi.k8s.io | ❌ | Delete |

NFS server: `10.0.0.23:/serve/k8s`

---

## 🔐 Secrets Management

All secrets are encrypted using [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) and safe to commit to git.

### Sealing a new secret
```bash
# Create a raw secret
kubectl create secret generic my-secret \
  --dry-run=client \
  --from-literal=key=value \
  -n my-namespace -o yaml > /tmp/my-secret.yaml

# Seal it
kubeseal -f /tmp/my-secret.yaml -w deployments/infrastructure/my-app/my-secret-sealed.yaml

# Commit
git add deployments/infrastructure/my-app/my-secret-sealed.yaml
git commit -m "feat: add sealed secret for my-app"
git push
```

### Copying sealed secrets from another cluster
Since sealed secrets are cluster-specific, you must re-seal when migrating:
```bash
# Get raw secret from old cluster
kubectl get secret my-secret -n my-namespace --context old-cluster -o yaml > /tmp/secret.yaml

# Seal for new cluster (make sure kubeseal points to new cluster)
kubeseal -f /tmp/secret.yaml -w sealed-secret.yaml
```

---

## 🚀 Bootstrap

This only needs to be done once when setting up a new cluster.

### Prerequisites
- `kubectl` configured for the Talos cluster
- `helm` installed
- `kubeseal` installed
- ArgoCD Helm repo added

### Steps

**1. Install ArgoCD**
```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
kubectl create namespace argocd
helm install argocd argo/argo-cd \
  -n argocd \
  -f deployments/infrastructure/argocd/argocd-values.yaml
```

**2. Apply sealed secrets and httproute**
```bash
kubectl apply -f deployments/infrastructure/argocd/git-creds-sealed.yaml
kubectl apply -f deployments/infrastructure/argocd/argocd-httproute.yaml
```

**3. Apply the root app**
```bash
kubectl apply -f bootstrap/talos-cluster.yaml
```

**4. Sync apps in order via ArgoCD UI**

Sync each app manually in sync wave order:
1. `sealed-secrets`
2. `cilium`
3. `cert-manager`
4. `traefik`
5. `argocd`
6. `metrics-server`
7. `storageclasses`

---

## 📦 Adding a New App

1. Create a directory under `deployments/apps/my-app/`
2. Add `app.yaml` (ArgoCD Application manifest)
3. Add values file and any extra manifests
4. Add to `deployments/apps/kustomization.yaml`:
```yaml
resources:
  - my-app/app.yaml
```
5. Commit and push — ArgoCD will pick it up automatically within 30 seconds.

---

## 🔔 Notifications

ArgoCD is configured to send Slack notifications to `#deployments` on sync failure.

Template:
```
🔴 [TALOS-CLUSTER] APP-NAME sync failed!
Repo: <repoURL>
Error: <error message>
```

---

## 🏷️ Node Labels

| Node | Role | Label |
|------|------|-------|
| talos-3sw-0t2 | control-plane | `node=c-1` |
| talos-0z8-aw8 | worker | `node=w-1` |
| talos-xxc-2bm | worker | `node=w-2` |

To schedule a workload on a specific node:
```yaml
nodeSelector:
  node: w-1
```
