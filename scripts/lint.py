#!/usr/bin/env python3
"""Fails when the repo contradicts itself. Each check returns error strings; run with no args from anywhere in the repo.

- yaml:        every file parses, no duplicate keys
- conventions: critical apps carry no cascade finalizer; each namespace is created exactly once; no managed-by marker
- routes:      every served hostname has a blackbox target, every target hostname is served
- secrets:     every secretKeyRef into a SealedSecret names a key it has
- homepage:    every {{HOMEPAGE_VAR_*}} used is defined in homepage's env or homepage-secrets
- ports:       every <app>.<ns>.svc.cluster.local:<port> URL matches the appset port
- alerts:      no rule filters its query to <= 0 and then fires on > 0; dashboard links resolve
"""
import os
import re
import subprocess
import sys

from repo import BLACKBOX, DOMAIN, Repo, hostnames, walk

CRITICAL = {"sealed-secrets", "cilium", "cert-manager", "argocd", "longhorn"}
PREEXISTING = {"kube-system", "argocd"}  # argocd is created during bootstrap (README)


def conventions(repo):
    errors = [f"{p}: remove argocd.argoproj.io/managed-by (nothing reads it)"
              for p, t in repo.texts.items() if "argocd.argoproj.io/managed-by" in t]
    namespaces = {d["metadata"]["name"] for _, d in repo.kind("Namespace")}
    for path, d in repo.kind("Application"):
        name, ns = d["metadata"]["name"], d["spec"]["destination"].get("namespace")
        creates = "CreateNamespace=true" in (d["spec"].get("syncPolicy") or {}).get("syncOptions", [])
        if name in CRITICAL and d["metadata"].get("finalizers"):
            errors.append(f"{path}: {name} is cluster-critical; drop resources-finalizer")
        if creates and ns in namespaces:
            errors.append(f"{path}: {ns} has a Namespace manifest; drop CreateNamespace=true")
        if not creates and ns not in namespaces | PREEXISTING:
            errors.append(f"{path}: nothing creates namespace {ns}; add CreateNamespace=true")
    return errors


def routes(repo):
    served = {f"{a['host']}.{DOMAIN}" for a in repo.appset_apps() if a.get("port")}
    for path, text in repo.texts.items():
        # homepage and the blackbox config only point at hosts, they don't serve them
        if not path.startswith("deployments/apps/homepage/") and path != BLACKBOX:
            served |= hostnames(text)
    blackbox = repo.texts[BLACKBOX]
    probed = set(re.findall(r"https?://([a-z0-9-]+\." + re.escape(DOMAIN) + ")", blackbox))
    # a target named after the host also counts, so hosts probed by IP (technitium-secondary) pass
    named = {f"{n}.{DOMAIN}" for n in re.findall(r'^\s*name\s*=\s*"([a-z0-9-]+)"', blackbox, re.M)}
    return ([f"{h}: served but not probed; add a target to {BLACKBOX}" for h in sorted(served - probed - named)] +
            [f"{h}: probed but nothing in the repo serves it" for h in sorted(probed - served)])


def secrets(repo):
    sealed, errors = repo.sealed_keys(), []
    for path, d in repo.docs:
        for node in walk(d):
            ref = node.get("secretKeyRef")
            if isinstance(ref, dict) and ref.get("name") in sealed and ref.get("key") not in sealed[ref["name"]]:
                errors.append(f"{path}: secretKeyRef {ref['name']}/{ref.get('key')} is not in the SealedSecret")
    return errors


def homepage(repo):
    used = {(p, v) for p, t in repo.texts.items() for v in re.findall(r"\{\{\s*(HOMEPAGE_VAR_\w+)\s*\}\}", t)}
    defined = set(repo.sealed_keys().get("homepage-secrets", set()))
    for _, d in repo.docs:
        for node in walk(d):
            if isinstance(node.get("env"), dict):
                defined |= {k for k in node["env"] if k.startswith("HOMEPAGE_VAR_")}
    return [f"{p}: {v} is used but homepage defines no such env var" for p, v in sorted(used) if v not in defined]


def ports(repo):
    port = {(a["name"], a["namespace"]): str(a["port"]) for a in repo.appset_apps() if a.get("port")}
    errors = []
    for path, text in repo.texts.items():
        for name, ns, p in re.findall(r"([a-z0-9-]+)\.([a-z0-9-]+)\.svc\.cluster\.local:(\d+)", text):
            if (name, ns) in port and port[(name, ns)] != p:
                errors.append(f"{path}: {name}.{ns} uses port {p}, the appset says {port[(name, ns)]}")
    return errors


# Go template keywords plus the Prometheus-compatible functions Grafana alert annotations support
TEMPLATE_FUNCS = {"if", "else", "end", "range", "with", "and", "or", "not", "eq", "ne", "lt", "le", "gt", "ge", "len", "index",
                  "print", "printf", "println", "humanize", "humanize1024", "humanizeDuration", "humanizePercentage",
                  "humanizeTimestamp", "title", "toUpper", "toLower", "match", "reReplaceAll", "externalURL", "pathPrefix",
                  "safeHtml", "stripPort", "parseDuration", "graphLink", "tableLink", "args"}
# shortcut: only catches the filter at the very end of the expr (x == 0), not inside parentheses or before and/or
FILTER_TO_ZERO = re.compile(r"(==|<=|<)\s*-?0(\.0+)?\s*$")


def alerts(repo):
    uids, errors = repo.dashboard_uids(), []
    for path, rule in repo.alert_rules():
        where = f"{path}: {rule.get('uid')}"
        exprs = [d["model"]["expr"] for d in rule.get("data", []) if "expr" in d.get("model", {})]
        cond = next((d["model"] for d in rule.get("data", []) if d.get("refId") == rule.get("condition")), {})
        for c in cond.get("conditions", []):
            ev = c.get("evaluator", {})
            if ev.get("type") == "gt" and ev.get("params") == [0] and any(FILTER_TO_ZERO.search(e.strip()) for e in exprs):
                errors.append(f"{where}: query filters to values <= 0 but fires on > 0, so it never fires; "
                              "query the raw metric and use an lt threshold")
        annotations = rule.get("annotations") or {}
        uid = annotations.get("__dashboardUid__")
        if uid and uid not in uids:
            errors.append(f"{where}: __dashboardUid__ {uid} matches no dashboard")
        # Grafana sends the raw template when it fails to render; these are the two ways that has happened here
        for text in annotations.values():
            if re.search(r"\$value\b(?!s)", text):
                errors.append(f"{where}: $value is a string of all query results in Grafana; use $values.A.Value")
            for fn in re.findall(r"\|\s*([a-zA-Z]\w*)|\{\{-?\s*([a-zA-Z]\w*)", text):
                fn = fn[0] or fn[1]
                if fn not in TEMPLATE_FUNCS:
                    errors.append(f"{where}: template function {fn!r} does not exist in Grafana alert templates")
    return errors


CHECKS = [conventions, routes, secrets, homepage, ports, alerts]


def lint(root="."):
    repo = Repo(root)
    errors = []
    for check in CHECKS:
        errors += check(repo)
    return repo.errors + errors  # parse errors are filled while checks read the repo


if __name__ == "__main__":
    os.chdir(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip())
    errors = lint()
    for e in errors:
        print(e)
    sys.exit(1 if errors else 0)
