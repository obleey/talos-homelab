"""What the repo declares, read once for every check: YAML docs, appset apps, sealed keys, alert rules, dashboards."""
import glob
import json
import os
import re

import yaml

DOMAIN = "talos-cluster.local.obleey.com"
BLACKBOX = "deployments/infrastructure/observability/alloy-blackbox/values.yaml"


class StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys (PyYAML silently keeps the last one)."""


def _no_duplicates(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate key {key!r}", key_node.start_mark)
        seen.add(key)
    return loader.construct_mapping(node, deep)


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates)


def load_all(text):
    return [d for d in yaml.load_all(text, Loader=StrictLoader) if isinstance(d, dict)]


class Repo:
    def __init__(self, root="."):
        self.root = root
        self.errors = []  # parse errors; every check reports them
        self.texts, self.docs = {}, []  # docs: (path, doc)
        for full in sorted(glob.glob(os.path.join(root, "deployments/**/*.yaml"), recursive=True)):
            path = os.path.relpath(full, root)
            self.texts[path] = text = open(full).read()
            try:
                self.docs += [(path, d) for d in load_all(text)]
            except yaml.YAMLError as e:
                self.errors.append(f"{path}: {str(e).splitlines()[0]} {getattr(e, 'problem_mark', '') or ''}".strip())

    def kind(self, kind):
        return [(p, d) for p, d in self.docs if d.get("kind") == kind]

    def appset_apps(self):
        """One dict per ApplicationSet element: name, port, host, namespace."""
        apps = []
        for _, d in self.kind("ApplicationSet"):
            ns = d["spec"]["template"]["spec"]["destination"]["namespace"]
            for el in d["spec"]["generators"][0]["list"]["elements"]:
                apps.append({"host": el["name"], **el, "namespace": el.get("namespace", ns)})
        return apps

    def sealed_keys(self):
        """{secret name: set of encryptedData keys}; key names are plaintext in a SealedSecret."""
        return {d["metadata"]["name"]: set(d["spec"].get("encryptedData", {})) for _, d in self.kind("SealedSecret")}

    def alert_rules(self):
        """(path, rule) for every rule in a grafana_alert ConfigMap."""
        rules = []
        for path, d in self.kind("ConfigMap"):
            if (d["metadata"].get("labels") or {}).get("grafana_alert") != "1":
                continue
            for body in (d.get("data") or {}).values():
                try:
                    groups = load_all(body)[0].get("groups", [])
                except (yaml.YAMLError, IndexError) as e:
                    self.errors.append(f"{path}: embedded alert YAML: {str(e).splitlines()[0] if str(e) else 'empty'}")
                    continue
                rules += [(path, r) for g in groups for r in g.get("rules", [])]
        return rules

    def dashboards(self):
        """{dashboard uid: set of panel ids, rows' nested panels included}."""
        boards = {}
        for path, d in self.kind("ConfigMap"):
            for name, body in (d.get("data") or {}).items():
                if name.endswith(".json"):
                    j = json.loads(body)
                    boards[j.get("uid")] = {p.get("id") for p in walk(j.get("panels", [])) if "type" in p}
        return boards


def walk(node):
    """Every dict nested anywhere in a parsed doc."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def hostnames(text):
    return set(re.findall(r"[a-z0-9-]+\." + re.escape(DOMAIN), text))
