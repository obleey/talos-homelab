#!/usr/bin/env python3
"""Fails when an ArgoCD Application breaks the repo's conventions:
- cluster-critical apps never carry the cascade-delete finalizer
- a namespace comes from a Namespace manifest or CreateNamespace=true, never both, never neither
- the unused argocd.argoproj.io/managed-by marker stays gone
"""
import glob
import sys

import yaml

CRITICAL = {"sealed-secrets", "cilium", "cert-manager", "argocd", "longhorn"}
PREEXISTING = {"kube-system", "argocd"}  # argocd is created during bootstrap (README)

docs, errors = [], []
for path in sorted(glob.glob("deployments/**/*.yaml", recursive=True)):
    text = open(path).read()
    if "argocd.argoproj.io/managed-by" in text:
        errors.append(f"{path}: remove argocd.argoproj.io/managed-by (nothing reads it)")
    try:
        docs += [(path, d) for d in yaml.safe_load_all(text) if isinstance(d, dict)]
    except yaml.YAMLError:
        pass  # Go-templated files (appset values) are not plain YAML

namespaces = {d["metadata"]["name"] for _, d in docs if d.get("kind") == "Namespace"}

for path, d in docs:
    if d.get("kind") != "Application":
        continue
    name = d["metadata"]["name"]
    ns = d["spec"]["destination"].get("namespace")
    creates = "CreateNamespace=true" in (d["spec"].get("syncPolicy") or {}).get("syncOptions", [])
    if name in CRITICAL and d["metadata"].get("finalizers"):
        errors.append(f"{path}: {name} is cluster-critical; drop resources-finalizer")
    if creates and ns in namespaces:
        errors.append(f"{path}: {ns} has a Namespace manifest; drop CreateNamespace=true")
    if not creates and ns not in namespaces | PREEXISTING:
        errors.append(f"{path}: nothing creates namespace {ns}; add CreateNamespace=true")

for e in errors:
    print(e)
sys.exit(1 if errors else 0)
