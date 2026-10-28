#!/bin/sh
# Fails when a cluster hostname has no blackbox probe target, or a probe target points at a hostname nothing in the repo serves.
set -eu
cd "$(git rev-parse --show-toplevel)"

domain='talos-cluster.local.obleey.com'
blackbox='deployments/infrastructure/observability/alloy-blackbox/values.yaml'
appset='deployments/apps/appset-servarr.yaml'
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# served: appset records with a port, plus every literal hostname outside the two consumer files (homepage, blackbox)
{
  yq -r --arg d "$domain" '.spec.generators[0].list.elements[] | select(.port) | "\(.host // .name).\($d)"' "$appset"
  grep -rhoE "[a-z0-9-]+\.$domain" deployments --include='*.yaml' \
    --exclude-dir=homepage --exclude="$(basename "$blackbox")" || true
} | sort -u > "$tmp/served"

grep -oE "https?://[a-z0-9-]+\.$domain" "$blackbox" | sed 's#.*://##' | sort -u > "$tmp/probed"
# a target named after the host also counts, so hosts probed by IP (technitium-secondary) pass
{ cat "$tmp/probed"; sed -n 's/^ *name *= *"\([a-z0-9-]*\)".*/\1.'"$domain"'/p' "$blackbox"; } | sort -u > "$tmp/covered"

status=0
if comm -23 "$tmp/served" "$tmp/covered" | grep .; then
  echo "^ served but not probed: add a target to $blackbox" >&2; status=1
fi
if comm -13 "$tmp/served" "$tmp/probed" | grep .; then
  echo "^ probed but not served by anything in the repo" >&2; status=1
fi
exit $status
