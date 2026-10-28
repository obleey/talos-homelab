#!/usr/bin/env python3
"""Renders every Helm-based app the way ArgoCD does and fails if any of them does not render.

- each Application with a chart source: `helm template` with its valueFiles ($values = repo root)
- each servarr ApplicationSet element: the appset's valueFiles plus its go-templated helm.values
- `kubectl kustomize` of the root (deployments/)
"""
import os
import subprocess
import sys
import tempfile

import yaml

from repo import Repo

ROOT = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
os.chdir(ROOT)
failures = []
# APIs the live cluster serves that charts probe with .Capabilities (ArgoCD passes the real list)
API_VERSIONS = ["--api-versions", "monitoring.coreos.com/v1"]


def run(label, cmd, stdin=None):
    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
    if r.returncode != 0:
        failures.append(f"{label}:\n{r.stderr.strip()}")
    return r.stdout


def helm_template(label, release, ns, src, value_files, extra_values=""):
    files = [f.replace("$values/", "") for f in value_files]
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as extra:
        extra.write(extra_values)
        extra.flush()
        run(label, ["helm", "template", release, src["chart"], "--repo", src["repoURL"], "--version", str(src["targetRevision"]),
                    "-n", ns, *API_VERSIONS, *sum((["-f", f] for f in files), []), "-f", extra.name])


def go_template(template, element):
    """Render an appset string field with Go template + sprig, via a throwaway Helm chart."""
    with tempfile.TemporaryDirectory() as d:
        os.mkdir(f"{d}/templates")
        open(f"{d}/Chart.yaml", "w").write("apiVersion: v2\nname: gotpl\nversion: 0.0.1\n")
        open(f"{d}/values.yaml", "w").write(yaml.safe_dump({"el": element}))
        # trailing comment keeps the output non-empty: helm errors on an empty --show-only template
        open(f"{d}/templates/t.txt", "w").write("{{- with .Values.el }}" + template + "{{ end }}\n# end\n")
        out = run(f"appset template ({element['name']})", ["helm", "template", "x", d, "--show-only", "templates/t.txt"])
        return out.split("\n", 2)[2]


for path, doc in Repo().docs:
    if doc.get("kind") == "Application":
        spec = doc["spec"]
        for src in spec.get("sources") or [spec["source"]]:
            if "chart" in src:
                helm_template(f"{path} ({src['chart']})", doc["metadata"]["name"], spec["destination"]["namespace"],
                              src, (src.get("helm") or {}).get("valueFiles", []))
    elif doc.get("kind") == "ApplicationSet":
        tmpl = doc["spec"]["template"]
        for el in doc["spec"]["generators"][0]["list"]["elements"]:
            src = tmpl["spec"]["sources"][0]
            helm_cfg = src.get("helm") or {}
            files = [f.replace("{{.name}}", el["name"]) for f in helm_cfg.get("valueFiles", [])]
            values = go_template(helm_cfg.get("values", ""), el)
            helm_template(f"{path} ({el['name']})", el["name"], tmpl["spec"]["destination"]["namespace"], src, files, values)

run("kustomize deployments/", ["kubectl", "kustomize", "deployments"])

for f in failures:
    print(f"FAILED {f}\n")
print(f"{len(failures)} render failure(s)" if failures else "all apps render")
sys.exit(1 if failures else 0)
