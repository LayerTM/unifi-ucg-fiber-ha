<h1 align="center">UniFi Gateway for Home Assistant (non-invasive)</h1>

<p align="center">
  <img src="https://raw.githubusercontent.com/LayerTM/unifi-ucg-fiber-ha/main/assets/brand/banner.png" alt="UniFi Gateway — non-invasive gateway & WAN monitoring for Home Assistant" width="760">
</p>

<p align="center">
  <em>Agentless monitoring — and opt-in control — for Ubiquiti UniFi OS gateways in Home Assistant.<br>
  Talks to the UniFi Network application over HTTPS only — no SSH, nothing installed on the gateway, no cloud.</em>
</p>

<div align="center">

[![release](https://img.shields.io/github/v/release/LayerTM/unifi-ucg-fiber-ha?sort=semver&color=41BDF5)](https://github.com/LayerTM/unifi-ucg-fiber-ha/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![quality scale: platinum (self-reported)](https://img.shields.io/badge/quality%20scale-platinum%20(self--reported)-8A2BE2)](custom_components/unifi_gateway_rest/quality_scale.yaml)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.3%2B-41BDF5?logo=home-assistant&logoColor=white)](https://www.home-assistant.io/)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)

[![tests](https://github.com/LayerTM/unifi-ucg-fiber-ha/actions/workflows/tests.yml/badge.svg)](https://github.com/LayerTM/unifi-ucg-fiber-ha/actions/workflows/tests.yml)
[![ha-integration](https://github.com/LayerTM/unifi-ucg-fiber-ha/actions/workflows/ha-integration.yml/badge.svg)](https://github.com/LayerTM/unifi-ucg-fiber-ha/actions/workflows/ha-integration.yml)
[![hassfest](https://github.com/LayerTM/unifi-ucg-fiber-ha/actions/workflows/hassfest.yml/badge.svg)](https://github.com/LayerTM/unifi-ucg-fiber-ha/actions/workflows/hassfest.yml)
[![hacs](https://github.com/LayerTM/unifi-ucg-fiber-ha/actions/workflows/hacs.yml/badge.svg)](https://github.com/LayerTM/unifi-ucg-fiber-ha/actions/workflows/hacs.yml)
[![lint](https://github.com/LayerTM/unifi-ucg-fiber-ha/actions/workflows/lint.yml/badge.svg)](https://github.com/LayerTM/unifi-ucg-fiber-ha/actions/workflows/lint.yml)
[![secret-scan](https://github.com/LayerTM/unifi-ucg-fiber-ha/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/LayerTM/unifi-ucg-fiber-ha/actions/workflows/secret-scan.yml)

</div>

---

## Why this integration

Home Assistant's official **UniFi Network** integration is excellent for what it
does — clients, presence, PoE/firewall/traffic-route switches, and basic device
diagnostics — and you should keep using it. What it does **not** expose (verified
against its source) is the **gateway / WAN / ISP** picture a fiber-gateway owner
actually wants. This integration fills exactly that gap, over the same local API,
read-only by default. Run the two side by side: the official one for network
*management*, this one for gateway / WAN / console *monitoring*.

| | This project | official `unifi` (HA core) | `holdestmade/Unifi-WAN` |
|---|:--:|:--:|:--:|
| WAN up/down, IP, per-WAN throughput | ✅ | ❌ | ✅ |
| Per-WAN availability % & uptime | ✅ | ❌ | ❌ |
| ISP name / ASN | ✅ | ❌ | ❌ |
| ISP speedtest (down/up/ping) | ✅ | ❌ | ✅ |
| WAN failover state | ✅ | ❌ | ❌ |
| Console health (CPU / mem / temps / load) | ✅ | partial | ❌ |
| SFP+ module presence & fault | ✅ | ❌ | ❌ |
| VPN status | ✅ | ❌ | ❌ |
| Read-only by default, agentless | ✅ | ✅ | partial |
| Platinum quality scale, vendored (zero-dep) | ✅ | ✅ | ❌ |

## How it works

UniFi OS gateways run the UniFi Network application, whose classic REST API sits
behind the console reverse proxy (`https://<host>/proxy/network/api/...`). The
integration authenticates locally and polls three read endpoints —
`/stat/device`, `/stat/health`, `/stat/sysinfo` — plus `/api/system` for device
identity. Everything is served from one shared coordinator fetch. See
[`docs/API.md`](docs/API.md) for the exact endpoints and fields.

Two authentication methods are supported; pick one during setup:

- **API key** (recommended) — created in the UniFi OS UI. On the UCG-Fiber it
  reaches the full classic telemetry.
- **Local account** (username + password) — the same reads, and the fallback when
  a key is limited to the Integration API.

Either way the integration only reads, until you turn the opt-in controls on —
see [Controls](#controls-opt-in) for what that changes and what it needs.

## Entities

Everything is grouped under one hub device (the gateway/console), with a
sub-device per WAN uplink and per populated SFP+ port.

- **Console** — CPU %, memory %, load average (1 / 5 / 15 min), per-sensor
  temperatures (CPU / board / PMIC), uptime, internal storage usage, client
  counts (total / wired / wireless), UniFi Network application version; binary
  sensors for **internet**, **online**, **overheating**, **WAN failover active**,
  firmware-update-available and site-to-site VPN.
- **ISP & internet** — ISP name, ISP ASN, internet latency, and an internet
  connectivity binary sensor.
- **Speedtest** — last download / upload / ping and last-run time, and (with
  controls enabled) a **Run speedtest** button.
- **Per WAN uplink** *(WAN, WAN2, …)* — link up, active-uplink, IP address,
  latency, availability %, uptime, negotiated link speed, download / upload
  throughput, and media.
- **Per SFP+ port** *(only when a module is present)* — module present and a
  module-problem binary sensor (Rx-LOS / Tx-fault); vendor and part appear on the
  sub-device info.
- **VPN** — site-to-site enabled and active remote-user count.

Requires **Home Assistant 2025.3+** — the release that introduced
`AddConfigEntryEntitiesCallback`, the newest core API this integration uses.
Development and CI run against the current release. Configuration is through the
UI; re-authentication and reconfiguration are supported.

## Installation

Via HACS (custom repository):

1. HACS → ⋮ → **Custom repositories** → add
   `https://github.com/LayerTM/unifi-ucg-fiber-ha` (category: **Integration**).
2. Install **UniFi Gateway (non-invasive)**, then restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → UniFi Gateway**, then
   complete the flow:
   - **Host / Port / Site** of the gateway console, and whether to verify TLS
     (off by default — UniFi OS ships a self-signed certificate).
   - **Authentication** — an API key (recommended) or a local account.

Use a least-privilege credential — an API key, or a dedicated limited local
admin — rather than your owner account. The `aiounifigw` client is bundled inside
the integration and has no external dependencies (Home Assistant already ships
`aiohttp` and `yarl`), so HACS installs everything.

## Removal

1. **Settings → Devices & Services → UniFi Gateway**, open the ⋮ menu on the
   integration entry and choose **Delete**. This removes the config entry and all
   its devices and entities; the stored credential is discarded.
2. Optional — remove the integration in **HACS → UniFi Gateway (non-invasive) →
   Remove**, then restart Home Assistant.

Nothing is written to or left on the gateway, so no device-side cleanup is needed.

## Security & privacy

- Read-only by default: the polling client issues nothing but GET requests, and
  the control actions are opt-in and off until you switch them on — see
  [Controls](#controls-opt-in).
- **The gateway's certificate is trusted on first use, not ignored.** A UniFi OS
  console serves a self-signed certificate, so ordinary CA verification cannot
  succeed against one. Setup reads the certificate, shows you its SHA-256
  fingerprint to compare against the console's own screen, and from then on
  accepts only that certificate — see [Certificate trust](#certificate-trust).
- Credentials live only in the Home Assistant config entry; nothing is sent to
  third parties.
- Diagnostics redact credentials, MAC and WAN IP, and a secret/PII scanner
  (`scripts/secret_scan.py`) runs in pre-commit and CI.

## Certificate trust

Setup offers three choices, and **pinning is the default**:

| Choice | What it means |
| --- | --- |
| Pin this gateway's certificate | The certificate served at setup is recorded by SHA-256 and every later connection must present that exact certificate. |
| Verify against the system CA store | Ordinary verification. Only works if you gave the console a certificate signed by a real authority. |
| Accept any certificate | No assurance the host answering is your gateway. |

**What pinning is, and what it is not.** Trust on first use assumes the first
contact was not already intercepted — it is **not** equivalent to a certificate
signed by a public authority. That assumption is exactly why the fingerprint is
put on screen instead of being adopted silently: compare it with the value the
console itself shows before you continue. Once pinned, a substituted certificate
is refused *before the request is written*, so credentials never reach an
impostor.

**If the certificate changes.** Reissuing a certificate and impersonating a
gateway look identical from here, so nothing is decided for you: a repair
notification appears showing both the pinned fingerprint and the new one, and
accepting the new one is an explicit act. Home Assistant never asks you to
re-enter credentials for this — a swapped certificate is not a bad password.

**Upgrading an existing setup.** An entry created before this existed keeps
working exactly as before, unchanged: pinning whatever the gateway happened to
serve during an upgrade would record a certificate nobody looked at. Instead a
repair notification offers the one-time step, with the fingerprint shown. You can
dismiss it and carry on unverified.

## Controls (opt-in)

Off by default. Enable **Configure → Enable control actions** to add a **Run
speedtest** button and a **Restart** button.

**Where the read-only boundary actually is.** It is a property of this
integration, not of your credential. The polling client only ever issues GET
requests, and no control exists until you switch it on. A UniFi API key is *not*
read-only by nature: UniFi's own local Network API authenticates state-changing
requests with the same `X-API-Key` header it uses for reads.

So once controls are on, a button sends its command with whichever credential you
configured, and it succeeds only if the console permits that credential to write.
If it does not, the action fails with a clear permissions error and nothing on the
gateway changes. Which credentials the console accepts on the classic command
endpoint is decided by the console and is not documented by UniFi, so this is
worth confirming on your own gateway rather than assuming: a local account with
write permission is the combination this integration was built around.

The official `unifi` integration remains the place for firmware installs and
network management.

## Supported devices

Any UniFi OS console running the UniFi Network application and reachable on your
LAN. Verified against a **UCG-Fiber** (`UDMA6A8`) on **UniFi OS 5.1.19 / Network
10.5.62**; the UDM / UXG / UCG family is expected to work — telemetry a given
model does not report is simply omitted (entities are capability-gated). Devices
are identified by their MAC, so one Home Assistant can monitor several gateways.

Not supported: cloud-only access (UniFi Site Manager) — only local access is used.

## Data updates

The integration **polls** the local REST API (`local_polling`) on a fixed
interval — **30 seconds** by default. Every entity is served from a single shared
coordinator fetch, so the poll cost does not grow with the number of entities.
Supplementary reads (`/stat/health`, `/stat/sysinfo`) degrade to *unknown* on a
transient permission/API error without taking the core WAN/console sensors
unavailable.

**Only a rejected credential asks you to re-authenticate.** A console that is
booting, updating or restarting answers differently — a redirect to its web UI,
or a page of HTML where JSON belongs — and that is treated as *unavailable*, so
the poll simply retries and recovers on its own. A local-account session still
gets one silent re-login first, since such a response can also be a genuine login
page. Re-authentication is requested only for a 401 that survives that re-login.

## Known limitations

- **No SFP optical DDM.** UCG-Fiber firmware reports SFP presence, vendor, part,
  Rx-LOS and Tx-fault, but **not** optical Rx/Tx power or module temperature — so
  those sensors are not created (a DAC/copper module has no optics at all).
- **Overlap with the official integration.** Console CPU/memory/temperature/
  uptime and firmware-update overlap the official `unifi` integration; those
  entities here are diagnostic and some are disabled by default, so this
  integration leads with the gap it fills.
- **API-key scope.** An API key limited to the Integration API only cannot reach
  the classic `/stat/*` telemetry — use a full-access key or a local account.

## Troubleshooting

- **"Failed to connect"** — check host/port and that Home Assistant can reach the
  console over HTTPS on your LAN. TLS verification is off by default (self-signed
  certificate); leave it off unless you pin a CA.
- **"Insufficient permissions" / empty data** — the credential can't read the
  classic API; use a local account or a full-access API key.
- **It keeps asking to re-authenticate, but the credential still works** — fixed
  in **v0.1.5**. Earlier versions read a console that was busy restarting (typically
  during a firmware update) as an expired session, and Home Assistant treats that as
  final: polling stops until you click through re-authentication. Update, then reload
  the entry — reloading also clears the stale *"Authentication expired"* repair.
- **A control action is refused** — the console does not permit that credential
  to write; the action reports a permissions error and changes nothing. See
  [Controls](#controls-opt-in).
- **A removed WAN/SFP lingers as a device** — it goes *unavailable*; delete it
  from the device page (removing stale sub-devices is allowed).
- **Diagnostics** — download redacted diagnostics from the device page when
  reporting an issue.

## Examples

Notify when the internet goes down:

```yaml
automation:
  - alias: Gateway internet down
    triggers:
      - trigger: state
        entity_id: binary_sensor.ucg_fiber_internet
        to: "off"
        for: "00:01:00"
    actions:
      - action: notify.mobile_app_phone
        data:
          title: Internet down
          message: "The gateway reports no internet on the active WAN."
```

Alert when the gateway fails over to the backup WAN:

```yaml
automation:
  - alias: Gateway on backup WAN
    triggers:
      - trigger: state
        entity_id: binary_sensor.ucg_fiber_wan_failover_active
        to: "on"
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "Gateway failed over to the backup WAN."
```

Warn on slow ISP speedtest results:

```yaml
automation:
  - alias: Slow internet
    triggers:
      - trigger: numeric_state
        entity_id: sensor.ucg_fiber_speedtest_download
        below: 100
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "Last speedtest download dropped below 100 Mbit/s."
```

## Beyond Home Assistant: CLI & MCP

The same client powers a command-line tool and a **read-only** MCP server for
scripts, agents and LLMs. Credentials come from the environment (`UNIFI_GW_HOST`
+ `UNIFI_GW_APIKEY`, or `UNIFI_GW_USER` / `UNIFI_GW_PASS`).

```bash
pip install "aiounifigw[cli]"                      # CLI
export UNIFI_GW_HOST=192.0.2.1 UNIFI_GW_APIKEY=... # or UNIFI_GW_USER / UNIFI_GW_PASS
unifi-gateway fingerprint                          # print the certificate's SHA-256
export UNIFI_GW_CERT_FINGERPRINT=$(unifi-gateway fingerprint)   # then pin it
unifi-gateway status                               # gateway / WAN / internet summary
unifi-gateway status --json                        # machine-readable
unifi-gateway speedtest --yes                      # write — trigger an ISP speedtest

pip install "aiounifigw[mcp]"                      # MCP server (read-only)
unifi-gateway-mcp                                  # exposes a gateway_status tool
```

**Safety model:** reads are always open; the only write (`speedtest`) prompts for
confirmation (or `--yes`), and the MCP server registers **no** write tools.

**TLS for these tools is unverified unless you say otherwise** — the historical
behaviour against local hardware, stated here rather than left to be discovered.
`UNIFI_GW_CERT_FINGERPRINT` pins that one certificate (run `unifi-gateway
fingerprint` against a gateway you trust, then compare it with the console's own
screen); `UNIFI_GW_VERIFY_SSL=1` verifies against the system CA store; a pinned
fingerprint wins over both. Home Assistant does not use this path — it stores a
pinned fingerprint per config entry. `UNIFI_GW_PORT` overrides the default 443.

## License

[MIT](LICENSE) © LayerTM
