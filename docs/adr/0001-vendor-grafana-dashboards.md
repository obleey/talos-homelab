# Grafana dashboards stay vendored in git, not referenced by gnetId

Community dashboards (Node Exporter Full, Longhorn, k8s-views, …) are about 80% of the repo's YAML, so referencing them by `gnetId` + `revision` in the Grafana values looks like an easy cut. We keep them as ConfigMaps instead.

- The chart fetches `gnetId` dashboards from grafana.com in an init container at every Grafana start; grafana.com rate-limited us (HTTP 429) after ~40 requests during evaluation, and a failed download keeps Grafana (and alerting) from starting.
- Most of them carry local edits (Blackbox, Traefik, Scraparr, ArgoCD job names), so they would stay vendored anyway; only Node Exporter Full and Longhorn matched an upstream revision exactly.
- Upstream uids differ from ours (Node Exporter Full is `rYdddlPWk`), so alert `__dashboardUid__` links would need repointing, and `scripts/lint.py` could no longer check those links because the JSON would leave the repo.
