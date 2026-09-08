# UniFi Network local REST API — endpoints used

All telemetry is read from the **classic** UniFi Network application API under
`/proxy/network/api/...`, reachable with either an `X-API-Key` header or a
local-account session (CSRF + `TOKEN` cookie). The newer API-key **Integration
API** (`/proxy/network/integration/v1/...`) is intentionally *not* used as a data
source — it exposes only site/device summaries, not the WAN / speedtest /
temperature / SFP payload this integration needs.

Verified against a UCG-Fiber (`UDMA6A8`) on UniFi OS `5.1.19.33549`, UniFi
Network `10.5.62`. `{site}` is the internal site name (usually `default`).

## Authentication

| Method | How |
|---|---|
| API key | `X-API-Key: <key>` on every request. Created in the UniFi OS UI (Settings → Control Plane → Integrations → Create API Key). Recommended; the read paths need nothing more. |
| Local account | `POST /api/auth/login` `{username, password}` → captures `TOKEN` cookie + `X-CSRF-Token`. The fallback when a key is limited to the Integration API, and the credential the control actions were built around. |

TLS is self-signed on UniFi OS; certificate verification is off by default.

### Responses that are not the API

While the Network application behind the UniFi OS proxy is down — booting, mid
firmware update, restarting — the console still answers, but with its **web UI**
rather than the API. Two shapes were observed on a live UCG-Fiber, both while
carrying a *valid* API key:

| Response | Meaning |
|---|---|
| `302` to `/manage` | the proxy is up, the application is not |
| `200` with `text/html` | what the redirect resolves to, if it is followed |

`aiohttp` follows redirects by default, which turns the first into the second and
makes it indistinguishable from an expired session. The client therefore sets
`allow_redirects=False` and classifies both as *unavailable* (retryable), never as
an authentication failure. **A rejected credential is a `401`, and nothing else.**
For reference, a healthy application returns JSON even for its errors —
`api.err.NotFound` arrives as `404 application/json`.

## `GET /api/system` — console identity

Short payload (with an API key). Used for the config-entry `unique_id`.

| Field | Meaning |
|---|---|
| `mac` | console MAC (→ unique_id) |
| `name` | friendly console name (e.g. `UCG Fiber`) |
| `hardware.shortname` | model short name (e.g. `UCGF`) |
| `hasInternet` | current internet reachability |

## `GET /proxy/network/api/s/{site}/stat/device` — device telemetry

Returns `{ "data": [ <device>, … ] }`. The gateway is the device whose `type` is
one of `ugw` / `uxg` / `ucg` / `udm` (fallback: any device with a `wan1`).

Fields consumed from the gateway object:

| Field | Used for |
|---|---|
| `model`, `type`, `name`, `version` | device identity / firmware |
| `state` (1 = connected), `uptime`, `overheating` | online / uptime / overheating |
| `system-stats.cpu`, `system-stats.mem` | CPU / memory % |
| `sys_stats.loadavg_1/5/15`, `mem_total`, `mem_used` | load averages / memory bytes |
| `num_sta` | client count |
| `temperatures[]` = `{name, type, value}` | per-sensor temperature |
| `storage[]` = `{name, mount_point, type, size, used}` | internal storage usage |
| `wan1`..`wan6` = `{up, is_uplink, enable, ip, media, speed, max_speed, rx_bytes[-r], tx_bytes[-r]}` | per-WAN state / throughput |
| `uptime_stats.WAN`/`WAN2` = `{availability, latency_average, uptime}` | per-WAN availability / latency / uptime |
| `port_table[]` `sfp_found`, `sfp_vendor`, `sfp_part`, `sfp_rx_los`, `sfp_tx_fault` | SFP presence / health (optical DDM is **not** reported) |

`wanN` maps to the `uptime_stats` key `WAN` (n=1) or `WAN{n}`. The active uplink
is the `wanN` with `is_uplink == true`; failover is "active uplink is not WAN1".

## `GET /proxy/network/api/s/{site}/stat/health` — subsystem health

Returns `{ "data": [ <subsystem>, … ] }`, one row per `subsystem`.

| Subsystem | Fields used |
|---|---|
| `www` | `status`, `speedtest_status`, `xput_down`, `xput_up`, `speedtest_ping`, `speedtest_lastrun`, `latency` |
| `wan` | `status`, `isp_name`, `isp_organization`, `asn`, `wan_ip` |
| `lan` | `num_user` (wired clients), `num_sw` |
| `wlan` | `num_user` (wireless clients), `num_guest`, `num_ap` |
| `vpn` | `site_to_site_enabled`, `remote_user_enabled`, `remote_user_num_active/inactive` |

## `GET /proxy/network/api/s/{site}/stat/sysinfo` — controller info

`data[0]` fields: `version` (Network application version), `name`,
`console_display_version`, `previous_version`, `timezone`, `update_available`.

## `POST /proxy/network/api/s/{site}/cmd/devmgr` — control actions (write)

Opt-in only. Whether a given credential may run these commands is decided by the
console — an API key is not read-only by nature — and a refusal comes back as
401/403. See the README's *Controls* section for the boundary as a whole.

| Action | Body |
|---|---|
| Run speedtest | `{"cmd": "speedtest"}` |
| Restart gateway | `{"cmd": "restart", "mac": "<gw-mac>", "reboot_type": "soft"}` |
