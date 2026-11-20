# UniFi Network local REST API — endpoints used

All telemetry is read from the **classic** UniFi Network application API under
`/proxy/network/api/...`, reachable with either an `X-API-Key` header or a
local-account session (CSRF + `TOKEN` cookie). The newer API-key **Integration
API** (`/proxy/network/integration/v1/...`) is intentionally *not* used as a data
source — it exposes only site/device summaries, not the WAN / speedtest /
temperature / SFP payload this integration needs.

Verified against a UCG-Fiber (`UDMA6A8`) on UniFi OS `6.0.17.36539`, UniFi
Network `11.0.102`. `{site}` is the internal site name (usually `default`).

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
| `autoBackupEnabled` *(session only)* | console auto-backup on / off |
| `backupSchedule` = `{frequency (DAILY/WEEKLY/MONTHLY), dayOfWeek (0 = Sunday), dayOfMonth, hour, localRetention, destinations}` *(session only)* | console backup frequency |

With a local-account session the console returns the full payload (about 60 KB),
which carries the console's own backup schedule; with an API key it returns only
the short identity above. The schedule is read every ten minutes.

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
| `wan1`..`wan6` = `{ifname, up, is_uplink, enable, ip, media, speed, max_speed, rx_bytes[-r], tx_bytes[-r]}` | per-WAN state / throughput |
| `uptime_stats.WAN`/`WAN2` = `{availability, latency_average, uptime}` | per-WAN availability / latency / uptime |
| `ids_ips_signature` = `{rule_count, update_time (epoch ms), signature_type, is_activating}` | IDS/IPS rules loaded / rule-set update time |
| `speedtest-status.interface_name` | interface of the last speedtest, matched to `wanN.ifname` (Network 10.6+) |
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

## `GET /proxy/network/v2/api/site/{site}/aggregated-dashboard` — site dashboard

Read as `?historySeconds=3600&widgets=wan_activity,cybersecure`: only the two
widgets used, over the last hour (about 10 KB). The endpoint is optional; a
`404` at setup means the firmware does not serve it and its entities are not
created.

| Field | Used for |
|---|---|
| `dashboard_meta.end_timestamp` (epoch ms) | end of the window, to skip the interval still filling |
| `wan_activity.activity_by_network_group.<WAN id>.history[]` = `{timestamp (epoch ms), avg_packet_loss_pct, min_latency_ms, avg_latency_ms, max_latency_ms}` | per-WAN packet loss / peak latency, five-minute intervals |
| `cybersecure.ips_enabled`, `is_activating`, `signatures` | IPS rules missing (enabled, not activating, zero rules) |
| `cybersecure.threats` | threats detected within the window |

The newest interval is reported while it is still filling; the last interval
that had ended by `end_timestamp` is used. `threats` and `scanned_bytes` are
totals over the requested window.

## `POST /proxy/network/v2/api/site/{site}/system-log/all` — system log (read query)

A search, not a change: the body is the query. Sent as
`{"timestampFrom", "timestampTo" (epoch ms), "pageNumber", "pageSize": 100,
"categories": [...]}` with every category except `CLIENT_DEVICES`, page by page
(from `0`) while `total_element_count` exceeds the entries read, up to five pages. The endpoint is
optional; when setup cannot read it, the event entity is not created.

Returns `{ "data": [ <entry>, … ], "total_element_count", "page_number", "total_page_count" }`,
newest first.

| Field | Used for |
|---|---|
| `id`, `timestamp` (epoch ms) | identity of an entry; reported once |
| `category` | event type (`INTERNET_AND_WAN`, `POWER`, `AUDIT`, `SECURITY`, `UNIFI_DEVICES`, `SOFTWARE_UPDATES`, `UNIFI_ETHERNET_PORTS`, `VPN`) |
| `event`, `severity` | event attributes (e.g. `THREAT_BLOCKED`, `HIGH`) |
| `title_raw`, `message_raw` + `parameters.<NAME>.name` | title and message, `{NAME}` placeholders filled from the parameters |

The log has no "after this entry" query, so each poll searches a window that
overlaps the previous one by five minutes and drops entries already reported.

## `POST /proxy/network/api/s/{site}/cmd/devmgr` — control actions (write)

Opt-in only. Whether a given credential may run these commands is decided by the
console — an API key is not read-only by nature — and a refusal comes back as
401/403. See the README's *Controls* section for the boundary as a whole.

| Action | Body |
|---|---|
| Run speedtest | `{"cmd": "speedtest"}` |
| Restart gateway | `{"cmd": "restart", "mac": "<gw-mac>", "reboot_type": "soft"}` |
