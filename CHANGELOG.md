# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
