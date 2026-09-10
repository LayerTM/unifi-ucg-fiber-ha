#!/usr/bin/env python3
"""Summarize a UniFi OS /stat/device capture into a PII-SAFE report.

Input : raw JSON from GET /proxy/network/api/s/<site>/stat/device
Output: captures/capability_summary.json  (safe to share — structure + whitelisted
        non-PII telemetry only; NO WAN IP / MAC / serial / hostname / ISP / SSID)

The point of this file is to answer, without leaking anything:
  * what fields does THIS UCG-Fiber actually expose on /stat/device?
  * are WAN interfaces / speedtest / temperatures / fan / storage populated?
  * does the gateway populate SFP+ optical DDM (rx/tx power, module temp)?

Usage: python3 scripts/summarize_capture.py <raw.json> [out.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# key values that are safe to surface verbatim (telemetry, not identifiers).
SAFE_SCALAR_KEYS = {
    # console health
    "general_temperature",
    "overheating",
    "has_temperature",
    "fan_level",
    "has_fan",
    "uptime",
    "state",
    "num_sta",
    "user-num_sta",
    "guest-num_sta",
    "cpu",
    "mem",
    "loadavg_1",
    "loadavg_5",
    "loadavg_15",
    "load_avg",
    "system-stats",
    "sys_stats",
    # speedtest
    "xput_download",
    "xput_upload",
    "latency",
    "rundate",
    "server",
    "status_download",
    "status_upload",
    "status_ping",
    "speedtest_status",
    # wan link (safe subset — NOT ip/gateway/dns/mac)
    "up",
    "enable",
    "type",
    "ifname",
    "speed",
    "full_duplex",
    "is_uplink",
    "latency_average",
    "availability",
    "avg_latency",
    "max_latency",
    # ports / poe / sfp optical (optical power & temp are NOT pii)
    "port_idx",
    "media",
    "poe_power",
    "poe_voltage",
    "poe_current",
    "poe_enable",
    "op_mode",
    "sfp_found",
    "sfp_present",
    "sfp_rxpower",
    "sfp_txpower",
    "sfp_temperature",
    "sfp_voltage",
    "sfp_current",
    "sfp_rxfault",
    "sfp_txfault",
    "sfp_vendor",
    "sfp_part",
    # firmware / model (safe)
    "version",
    "model",
    "model_in_lts",
    "adopted",
}
# any key matching these is redacted to "<redacted>" even inside safe dumps.
REDACT_SUBSTR = (
    "mac",
    "serial",
    "hostname",
    "ip",
    "gateway",
    "dns",
    "netmask",
    "ssid",
    "essid",
    "bssid",
    "isp",
    "name",
    "key",
    "token",
    "password",
    "user",
    "jwt",
    "cookie",
    "address",
    "lat",
    "lon",
    "geo",
    "x_",
    "_id",
    "site_id",
)


def tn(v: Any) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, list):
        inner = tn(v[0]) if v else "?"
        return f"list[{inner}]({len(v)})"
    return type(v).__name__


def is_redacted(key: str) -> bool:
    k = key.lower()
    # allow explicitly-safe keys even if a substring would trip the blocklist
    if key in SAFE_SCALAR_KEYS:
        return False
    return any(s in k for s in REDACT_SUBSTR)


def type_map(obj: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """Structure only: key -> typename. Recurses one level into dict/list-of-dict."""
    out: dict[str, Any] = {}
    for k, v in sorted(obj.items()):
        if isinstance(v, dict) and depth < 1:
            out[k] = type_map(v, depth + 1)
        elif isinstance(v, list) and v and isinstance(v[0], dict) and depth < 1:
            out[k] = {"__list_of__": type_map(v[0], depth + 1), "__len__": len(v)}
        else:
            out[k] = tn(v)
    return out


def safe_values(obj: dict[str, Any]) -> dict[str, Any]:
    """Whitelisted, PII-redacted values pulled from a dict (shallow)."""
    out: dict[str, Any] = {}
    for k, v in obj.items():
        if is_redacted(k):
            continue
        if isinstance(v, (int, float, bool, str)) and k in SAFE_SCALAR_KEYS:
            out[k] = v
    return out


def find_gateway(devices: list[dict[str, Any]]) -> dict[str, Any] | None:
    gw_types = {"ugw", "uxg", "ucg", "udm"}
    scored: list[tuple[int, dict[str, Any]]] = []
    for d in devices:
        if not isinstance(d, dict):
            continue
        score = 0
        t = str(d.get("type", "")).lower()
        m = str(d.get("model", "")).upper()
        if t in gw_types:
            score += 3
        if any(x in m for x in ("UCG", "UXG", "UDM", "UGW")):
            score += 3
        if "wan1" in d or "wan2" in d:
            score += 4
        if "speedtest_status" in d or "uptime_stats" in d:
            score += 2
        if score:
            scored.append((score, d))
    if not scored:
        return None
    scored.sort(key=lambda s: s[0], reverse=True)
    return scored[0][1]


def summarize(raw: Any) -> dict[str, Any]:
    devices = raw.get("data", raw) if isinstance(raw, dict) else raw
    if not isinstance(devices, list):
        return {"error": "unexpected shape; expected a list or {data:[...]}"}

    gw = find_gateway(devices)
    if gw is None:
        return {
            "error": "no gateway-like device found",
            "device_count": len(devices),
            "types_seen": sorted({str(d.get("type")) for d in devices if isinstance(d, dict)}),
        }

    report: dict[str, Any] = {}
    report["gateway"] = {
        "model": gw.get("model"),
        "type": gw.get("type"),
        "version": gw.get("version"),
        "adopted": gw.get("adopted"),
    }
    report["top_level_types"] = type_map(gw)

    # WAN interfaces (structure only — subkeys reveal what to model)
    wan = {}
    for i in range(1, 7):
        key = f"wan{i}"
        if isinstance(gw.get(key), dict):
            wan[key] = {
                "types": type_map(gw[key], depth=1),
                "safe": safe_values(gw[key]),
            }
    report["wan_interfaces"] = wan or "none present"

    # speedtest
    st = gw.get("speedtest_status")
    report["speedtest_status"] = {
        "present": st is not None,
        "types": type_map(st) if isinstance(st, dict) else tn(st),
        "safe": safe_values(st) if isinstance(st, dict) else st,
    }

    # uptime_stats (WAN monitors: availability/latency)
    us = gw.get("uptime_stats")
    report["uptime_stats_present"] = us is not None
    if isinstance(us, dict):
        report["uptime_stats_keys"] = sorted(us.keys())

    # console health
    report["health"] = {
        "general_temperature": gw.get("general_temperature"),
        "temperatures_present": "temperatures" in gw,
        "temperatures_types": type_map({"t": gw["temperatures"]})["t"]
        if "temperatures" in gw
        else None,
        "fan_level": gw.get("fan_level"),
        "has_fan": gw.get("has_fan"),
        "overheating": gw.get("overheating"),
        "storage_present": "storage" in gw,
        "storage_types": type_map({"s": gw["storage"]})["s"] if "storage" in gw else None,
        "sys_stats_keys": sorted(gw.get("sys_stats", {}).keys())
        if isinstance(gw.get("sys_stats"), dict)
        else None,
        "system_stats_keys": sorted(gw.get("system-stats", {}).keys())
        if isinstance(gw.get("system-stats"), dict)
        else None,
    }

    # SFP+ optical probe (the UCG-Fiber differentiator) — inspect port_table
    ports = gw.get("port_table") or []
    sfp_report = []
    any_sfp = False
    for p in ports if isinstance(ports, list) else []:
        if not isinstance(p, dict):
            continue
        sfp_keys = sorted(k for k in p if k.lower().startswith("sfp"))
        media = p.get("media")
        looks_sfp = bool(sfp_keys) or (isinstance(media, str) and "SFP" in media.upper())
        if not looks_sfp:
            continue
        any_sfp = True
        entry = {
            "port_idx": p.get("port_idx"),
            "media": media,
            "is_uplink": p.get("is_uplink"),
            "sfp_keys_present": sfp_keys,
        }
        # surface optical values (NOT serial) so we can confirm population
        for k in sfp_keys:
            if "serial" in k.lower():
                entry[k] = "<redacted>"
            else:
                entry[k] = p.get(k)
        sfp_report.append(entry)
    report["sfp_optical"] = {
        "any_sfp_like_port": any_sfp,
        "port_table_len": len(ports) if isinstance(ports, list) else 0,
        "ports": sfp_report or "no SFP fields found on any port",
    }
    # sample of a generic port's structure (to model per-port entities)
    report["port_table_sample_types"] = (
        type_map(ports[0])
        if isinstance(ports, list) and ports and isinstance(ports[0], dict)
        else None
    )

    # IDS/IPS / threat / VPN hints (need new parsing)
    report["ids_vpn_keys"] = sorted(
        k for k in gw if any(x in k.lower() for x in ("ips", "ids", "threat", "vpn", "dpi"))
    )

    return report


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "captures/capability_summary.json"
    try:
        raw = json.loads(Path(src).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"ERROR reading {src}: {e}")
        return 1
    rep = summarize(raw)
    Path(out).write_text(json.dumps(rep, indent=2, sort_keys=False), encoding="utf-8")

    # human-readable gist
    print(f"\n=== CAPABILITY SUMMARY ({src}) ===")
    if "error" in rep:
        print("  !!", rep["error"], "|", {k: v for k, v in rep.items() if k != "error"})
        return 0
    g = rep["gateway"]
    print(f"  gateway: model={g['model']} type={g['type']} version={g['version']}")
    w = rep["wan_interfaces"]
    print(f"  WAN interfaces: {list(w.keys()) if isinstance(w, dict) else w}")
    print(
        f"  speedtest populated: {rep['speedtest_status']['present']}  "
        f"values={rep['speedtest_status'].get('safe')}"
    )
    h = rep["health"]
    print(
        f"  temp={h['general_temperature']} temps_present={h['temperatures_present']} "
        f"fan={h['fan_level']} overheating={h['overheating']} storage={h['storage_present']}"
    )
    sfp = rep["sfp_optical"]
    print(f"  SFP-like ports: {sfp['any_sfp_like_port']}  ->  ", end="")
    if isinstance(sfp["ports"], list):
        for port in sfp["ports"]:
            print(f"port{port.get('port_idx')} keys={port.get('sfp_keys_present')}", end="  ")
        print()
    else:
        print(sfp["ports"])
    print(f"  IDS/VPN/DPI keys: {rep['ids_vpn_keys']}")
    print(f"\n  -> wrote PII-safe report to {out}  (safe to paste back)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
