#!/usr/bin/env bash
# Capture /stat/device from a UCG-Fiber (UniFi OS) via BOTH auth methods, then
# produce a PII-safe capability summary you can share.
#
# Nothing is installed on the gateway. All calls are local + read-only (GET).
#
# Config via env vars:
#   GW=192.0.2.1                 # UCG-Fiber IP/host (NO https://, NO trailing slash)   [required]
#   SITE=default                   # UniFi site "name" (internal id); auto-detected, falls back to "default"
#   # then EITHER an API key (preferred: clean, read-only):
#   UNIFI_API_KEY=xxxxxxxx         # Settings -> Control Plane -> Integrations -> Create API Key
#   # AND/OR a local account (proven fallback that always reaches /stat/device):
#   UNIFI_USER=admin
#   UNIFI_PASS='secret'
#
# Example:
#   GW=192.0.2.1 UNIFI_API_KEY=abcd UNIFI_USER=admin UNIFI_PASS='pw' bash scripts/capture_ucg.sh
#
set -uo pipefail

# Load local secrets file if present (gitignored) so credentials never need to
# be passed on the command line or pasted into a chat. Format = shell exports:
#   GW=192.0.2.1
#   UNIFI_API_KEY=...
#   UNIFI_USER=... ; UNIFI_PASS=...
if [ -f "captures/.secrets.env" ]; then
  # shellcheck disable=SC1091
  set -a; . "captures/.secrets.env"; set +a
fi

GW="${GW:?set GW (in captures/.secrets.env or the env) to the UCG-Fiber IP/host, e.g. GW=192.0.2.1}"
BASE="https://$GW"
OUT="captures"
CK="$OUT/.cookies.txt"
mkdir -p "$OUT"

have_key=0; have_pw=0
[ -n "${UNIFI_API_KEY:-}" ] && have_key=1
{ [ -n "${UNIFI_USER:-}" ] && [ -n "${UNIFI_PASS:-}" ]; } && have_pw=1
if [ "$have_key" -eq 0 ] && [ "$have_pw" -eq 0 ]; then
  echo "ERROR: set UNIFI_API_KEY and/or UNIFI_USER+UNIFI_PASS" >&2
  exit 1
fi

detect_site() {  # $1 = self_sites json file
  [ -s "$1" ] || { echo "${SITE:-default}"; return; }
  python3 - "$1" <<'PY' 2>/dev/null || echo "${SITE:-default}"
import json,sys
d=json.load(open(sys.argv[1])); data=d.get("data",d)
print((data[0].get("name") if isinstance(data,list) and data else "default") or "default")
PY
}

# --------------------------------------------------------------------------
if [ "$have_key" -eq 1 ]; then
  echo "[*] API-key: list sites (classic)"
  curl -sk --max-time 20 -H "X-API-Key: $UNIFI_API_KEY" \
    "$BASE/proxy/network/api/self/sites" -o "$OUT/self_sites.apikey.json"
  SITE="${SITE:-$(detect_site "$OUT/self_sites.apikey.json")}"
  echo "    site = $SITE"

  echo "[*] API-key: classic /stat/device  (the RICH endpoint)"
  curl -sk --max-time 30 -H "X-API-Key: $UNIFI_API_KEY" \
    "$BASE/proxy/network/api/s/$SITE/stat/device" -o "$OUT/stat_device.apikey.json"

  echo "[*] API-key: Integration API /integration/v1/sites  (for comparison; telemetry-poor)"
  curl -sk --max-time 20 -H "X-API-Key: $UNIFI_API_KEY" \
    "$BASE/proxy/network/integration/v1/sites" -o "$OUT/integration_sites.json" || true
fi

# --------------------------------------------------------------------------
if [ "$have_pw" -eq 1 ]; then
  echo "[*] session: login (POST /api/auth/login)"
  curl -sk --max-time 20 -c "$CK" -D "$OUT/.login.headers" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"$UNIFI_USER\",\"password\":\"$UNIFI_PASS\"}" \
    "$BASE/api/auth/login" -o "$OUT/.login.json"
  # CSRF token is saved in .login.headers (needed later for WRITE calls; not for these GETs).
  # Never print it — avoid leaking secrets to stdout/logs.
  grep -qi 'x-\(updated-\)\?csrf-token' "$OUT/.login.headers" 2>/dev/null \
    && echo "    (csrf token captured to .login.headers)" || true

  echo "[*] session: list sites"
  curl -sk --max-time 20 -b "$CK" \
    "$BASE/proxy/network/api/self/sites" -o "$OUT/self_sites.session.json"
  SITE="${SITE:-$(detect_site "$OUT/self_sites.session.json")}"
  echo "    site = $SITE"

  echo "[*] session: classic /stat/device"
  curl -sk --max-time 30 -b "$CK" \
    "$BASE/proxy/network/api/s/$SITE/stat/device" -o "$OUT/stat_device.session.json"
fi

# --------------------------------------------------------------------------
RAW="$OUT/stat_device.apikey.json"
[ -s "$RAW" ] || RAW="$OUT/stat_device.session.json"
if [ ! -s "$RAW" ]; then
  echo "ERROR: no /stat/device capture produced. Check GW / credentials / that the key can reach the classic endpoint." >&2
  [ -s "$OUT/stat_device.apikey.json" ] || echo "  (api-key path returned nothing — key may be scoped to /integration/v1 only; use UNIFI_USER/PASS)" >&2
  exit 1
fi

echo "[*] summarizing $RAW"
python3 scripts/summarize_capture.py "$RAW" "$OUT/capability_summary.json"

echo
echo "[*] DONE."
echo "    RAW (contains PII — keep LOCAL, gitignored):   $OUT/stat_device.*.json"
echo "    SAFE TO SHARE:                                 $OUT/capability_summary.json"
echo "    Paste capability_summary.json back to Claude to unblock the model code."
