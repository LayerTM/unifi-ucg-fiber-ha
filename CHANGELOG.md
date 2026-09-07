# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.7]

### Changed

- **Sub-devices are attached to the hub by device-registry id, not by identifiers.**
  Home Assistant 2026.8 replaced `DeviceInfo(via_device=…)` with `via_device_id` and
  removes the old key in **2027.8**; until then core logs a warning naming this
  integration every time a device is created that way — 18 of them in one run of the
  integration test-suite (core de-duplicates per call site, so a running Home
  Assistant shows the line rather than the count). `async_setup_entry`
  now registers the hub device before the platforms load, so a hub id exists to point
  at, and every WAN / SFP sub-device carries it.

  **No new minimum Home Assistant version.** Which spelling to send is asked of
  `DeviceInfo` itself rather than of a version number, so the 2025.3 floor is
  unchanged and nothing needs revisiting when the old key is finally removed. The
  hub device definition also lives in one place now, shared by the hub entities and
  by setup, instead of being written twice.

## [0.1.6]

### Fixed

- **The `ha` extra is resolvable again across the declared Python range.** It pulls
  a Home Assistant test harness that requires **Python 3.14.2**, while the library
  itself supports 3.12+, and the dependency carried no marker saying so. `pip` never
  noticed — it resolves for the one interpreter it runs on — but a universal resolver
  (`uv`) correctly reported the whole project as unsatisfiable, so `uv run` failed in
  a checkout. The requirement now carries
  `; python_full_version >= '3.14.2'`, which states that fact once.

### Documentation

- **README, *Data updates*:** "an authentication failure triggers re-authentication"
  no longer describes what the code does. It now says what actually counts as one —
  only a 401 that survives a re-login — and that a booting/updating console is
  treated as unavailable and retried.
- **README, *Troubleshooting*:** an entry for the symptom itself, "it keeps asking to
  re-authenticate but the credential still works", naming the version that fixes it
  and the entry reload that clears the stale repair.
- **docs/API.md:** a new *Responses that are not the API* section recording what the
  console answers while the application behind the proxy is down, and why redirects
  are not followed.
- The **quality-scale badge** now reads *self-reported*. `quality_scale` was dropped
  from the manifest in 0.1.5 precisely because it reads as an official rating; a
  badge claiming the same thing was the same claim in another place.

## [0.1.5]

### Fixed

- **The integration no longer loses authorization on its own.** The transport
  classified two non-authorization conditions as auth failures, and the coordinator
  turns any auth failure into `ConfigEntryAuthFailed` — which Home Assistant treats
  as terminal: polling stops and the entry waits for a manual re-authentication that
  never becomes necessary, because the credential was valid the whole time.
  - A **2xx carrying the console's web UI instead of JSON** was reported as
    "session may have expired". It means the console is not serving the API — it is
    booting, updating or restarting. It is now a retryable `GwApiError`. A
    session-based login still gets its one re-login attempt first, since the body
    may genuinely be a login shell.
  - **Redirects are no longer followed.** `aiohttp` follows them by default, and the
    UniFi OS proxy answers API paths with `302 → /manage` whenever the Network
    application is down; following that turned it into a `200 text/html` that was
    indistinguishable from an expired session. Redirects now surface as a
    `GwApiError` naming the target, so the cause is visible in the log.

  Measured on a live UCG-Fiber: the API key Home Assistant had marked as expired
  answered `200 application/json` on `stat/device` and `stat/health`, while a
  deliberately wrong key and no key both returned 401.

## [0.1.4]

Addresses the HACS review of
[hacs/default#9244](https://github.com/hacs/default/pull/9244).

### Fixed

- **A transient API error during setup no longer breaks the entry permanently.**
  `async_setup_entry` caught only `GwAuthError` and `GwConnectionError`; a
  `GwApiError` — raised on any non-2xx status, and when `/stat/device` carries no
  gateway — propagated and left the config entry in a failed state Home Assistant
  never retries. A console that is still booting, or a reverse proxy answering
  502/503, needed a manual reload. It now raises `ConfigEntryNotReady`, matching
  what the coordinator already did at runtime.

### Added

- **Speedtest in progress** binary sensor (diagnostic). The `Speedtest.in_progress`
  fact existed in the client model and was documented in the README, but no entity
  ever read it.

### Changed

- **Minimum Home Assistant lowered from 2026.6.0 to 2025.3.0.** The floor was far
  above what the code needs and hid the integration from everyone on an older
  release. 2025.3.0 is the release that introduced `AddConfigEntryEntitiesCallback`,
  the newest core API in use — measured against the Home Assistant sources, not
  assumed.
- **`quality_scale` removed from the manifest.** It is a Home Assistant core field,
  is not evaluated for custom integrations, and read as an official rating.
- **`mcp` extra pinned to `<2`.** The optional MCP server targets the v1 API;
  mcp 2.x renamed `FastMCP` to `MCPServer`, which broke the unpinned install.
  Migrating to the 2.x API is separate work.
- `DeviceInfo(via_device=…)` on the WAN / SFP sub-devices carries a typing
  suppression: the key left the TypedDict in 2026.8 in favour of `via_device_id`
  (a device-registry id this code does not hold at construction time). It stays
  functional until 2027.8 and is the only form that also works on the 2025.3 floor.

## [0.1.3]

### Added

- **Configurable polling interval** in the integration Options (15–3600 s,
  default 30) — previously fixed at 30 s.
- **Guest** and **IoT** client-count sensors (from the WLAN health subsystem).
  Diagnostic and disabled by default.

## [0.1.2]

### Added

- **Per-WAN data counters:** *Total downloaded* / *Total uploaded* sensors on
  each WAN uplink (cumulative bytes, `total_increasing`) — a building block for
  data-usage tracking / metered connections. Diagnostic and disabled by default.

## [0.1.1]

### Changed

- **SFP+ ports:** every physical SFP/SFP+ port is now surfaced as a sub-device
  (previously only ports with a module inserted were shown). An empty cage
  reports *module present = off*; vendor/part populate only when a module is
  present. The UCG-Fiber now shows both of its SFP+ ports.

## [0.1.0]

Initial release. Non-invasive, read-only-by-default Home Assistant integration
for UniFi OS gateways, verified on the UCG-Fiber.

### Added

- **Console (hub) entities:** CPU / memory utilization, load averages, per-sensor
  temperatures, uptime, storage usage, client counts, ISP name / ASN, internet
  latency, Network application version; binary sensors for internet, online,
  overheating, WAN failover, firmware-update-available and site-to-site VPN.
- **ISP speedtest:** download / upload / ping / last-run sensors, an in-progress
  binary sensor, and an opt-in **Run speedtest** button.
- **Per-WAN sub-devices:** link up, active uplink, IP, latency, availability,
  uptime, link speed, download/upload throughput, media.
- **Per-SFP+ sub-devices** (capability-gated): module present and module-problem
  (Rx-LOS / Tx-fault). Optical DDM is not reported by UCG-Fiber firmware.
- **Opt-in controls:** Run speedtest and Restart buttons (require write-capable
  auth; off by default).
- Config flow with API-key or local-account auth, site selection, TLS toggle,
  reauth and reconfigure flows; diagnostics with credential/MAC/WAN-IP redaction.
- Standalone `aiounifigw` async client (vendored into the integration; zero
  runtime PyPI dependency), targeting the platinum quality scale.
