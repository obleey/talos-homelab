#!/usr/bin/env python3
"""Self-test for lint.py: the repo passes, and breaking each guarded fact in a copy of it makes the matching check fail."""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from lint import lint  # noqa: E402

ROOT = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
APPS = "deployments/apps"
ALERTS = "deployments/infrastructure/observability/victoria-metrics-k8s-stack/alerts"

# (file, old text, new text, substring the error must contain)
CASES = [
    (f"{APPS}/_common-values.yaml", "TZ: Europe/Ljubljana", "TZ: Europe/Ljubljana\n          TZ: UTC", "duplicate key 'TZ'"),
    (f"{APPS}/starr-data.yaml", "---", "# argocd.argoproj.io/managed-by\n---", "remove argocd.argoproj.io/managed-by"),
    (f"{APPS}/starr-data.yaml", "---", "# newapp.talos-cluster.local.obleey.com\n---",
     "newapp.talos-cluster.local.obleey.com: served but not probed"),
    ("deployments/infrastructure/observability/alloy-blackbox/values.yaml", "https://bazarr.", "https://bazarrx.",
     "bazarrx.talos-cluster.local.obleey.com: probed but nothing"),
    (f"{APPS}/homepage/homepage-values.yaml", "key: sonarr-api-key", "key: sonarr-api-kee", "servarr-credentials/sonarr-api-kee"),
    (f"{APPS}/homepage/homepage-values.yaml", "{{HOMEPAGE_VAR_ARGOCD_TOKEN}}", "{{HOMEPAGE_VAR_ARGOCD_TOKN}}",
     "HOMEPAGE_VAR_ARGOCD_TOKN is used"),
    (f"{APPS}/unpackerr/unpackerr-values.yaml", "sonarr.servarr.svc.cluster.local:8989", "sonarr.servarr.svc.cluster.local:8988",
     "sonarr.servarr uses port 8988, the appset says 8989"),
    (f"{ALERTS}/grafana-blackbox-rules.yaml", '=~"technitium-.*"} == 0) == 2', '=~"technitium-.*"} == 0) == 0',
     "blackbox-technitium-outage: query filters to values <= 0"),
    (f"{ALERTS}/grafana-blackbox-rules.yaml", '__dashboardUid__: "blackbox-http-prober"', '__dashboardUid__: "nope"',
     "__dashboardUid__ nope matches no dashboard"),
    (f"{ALERTS}/grafana-blackbox-rules.yaml", "has expired {{ $values.A.Value }} days", "has expired {{ $value }} days",
     "blackbox-ssl-expired: $value is a string"),
    (f"{ALERTS}/grafana-blackbox-rules.yaml", "has expired {{ $values.A.Value }} days", "has expired {{ $values.A.Value | abs }} days",
     "template function 'abs' does not exist"),
    (f"{ALERTS}/grafana-coredns-rules.yaml", '__panelId__: "25"', 'note: "25"', "coredns-panic: Grafana rejects the whole provisioning reload"),
    (f"{ALERTS}/grafana-coredns-rules.yaml", '__panelId__: "25"', '__panelId__: "999"', "__panelId__ 999 is not a panel of dashboard k8s_system_coredns"),
]

assert lint(ROOT) == [], lint(ROOT)

with tempfile.TemporaryDirectory() as tmp:
    for path, old, new, expected in CASES:
        copy = os.path.join(tmp, "repo")
        shutil.rmtree(copy, ignore_errors=True)
        shutil.copytree(os.path.join(ROOT, "deployments"), os.path.join(copy, "deployments"))
        text = open(os.path.join(copy, path)).read()
        assert old in text, f"fixture drifted: {old!r} not in {path}"
        open(os.path.join(copy, path), "w").write(text.replace(old, new, 1))
        errors = lint(copy)
        assert any(expected in e for e in errors), f"{path}: expected {expected!r}, got {errors}"

print(f"lint self-test: {len(CASES)} cases ok")
