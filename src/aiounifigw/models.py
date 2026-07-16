"""Immutable typed models parsed from UniFi Network REST API responses.

Pure parsing + derived properties; no I/O. Field names follow the schema
verified against a real UCG-Fiber (UniFi OS 5.1.19 / Network 10.5.62) and
documented in ``docs/API.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


def _f(value: Any, default: float = 0.0) -> float:
    """Coerce to float; bools fall back to *default*. Numeric strings accepted."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _fo(value: Any) -> float | None:
    """Coerce to float or None (bools and non-numerics -> None)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _i(value: Any) -> int | None:
    """Coerce to int or None (bools treated as absent). Numeric strings accepted."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _i0(value: Any) -> int:
    """Coerce to int, defaulting to 0."""
    parsed = _i(value)
    return parsed if parsed is not None else 0


def _s(value: Any, default: str = "") -> str:
    """Return the string value, else *default*."""
    return value if isinstance(value, str) else default


def _b(value: Any) -> bool:
    """True only for a literal boolean True."""
    return value is True


def _epoch(value: Any) -> datetime | None:
    """Parse an epoch-seconds timestamp to a UTC datetime; 0/absent -> None."""
    secs = _i(value)
    if not secs:  # None or 0 (0 == "never run")
        return None
    try:
        return datetime.fromtimestamp(secs, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _uptime(value: Any) -> datetime | None:
    """Convert an uptime in seconds to the boot-time UTC datetime.

    Home Assistant renders a TIMESTAMP sensor as a stable device_class; a
    boot-time timestamp is preferred over a raw seconds counter.
    """
    secs = _i(value)
    if secs is None or secs < 0:
        return None
    try:
        return datetime.fromtimestamp(_now() - secs, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _now() -> float:
    """Wall-clock seconds (isolated so tests can monkeypatch it)."""
    import time

    return time.time()


@dataclass(frozen=True, slots=True)
class SystemIdentity:
    """Public console identity from the short /api/system payload."""

    mac: str
    name: str
    model_shortname: str
    device_state: str
    has_internet: bool

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> SystemIdentity:
        hw = d.get("hardware") or {}
        return cls(
            mac=_s(d.get("mac")),
            name=_s(d.get("name")),
            model_shortname=_s(hw.get("shortname")),
            device_state=_s(d.get("deviceState")),
            has_internet=_b(d.get("hasInternet")),
        )


@dataclass(frozen=True, slots=True)
class Temperature:
    """A named temperature sensor from the gateway ``temperatures[]`` array."""

    name: str
    type: str
    value: float

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Temperature:
        return cls(name=_s(d.get("name")), type=_s(d.get("type")), value=_f(d.get("value")))


@dataclass(frozen=True, slots=True)
class StorageVolume:
    """An internal storage volume (eMMC / tmpfs) from ``storage[]``."""

    name: str
    mount_point: str
    type: str
    size: int  # bytes
    used: int  # bytes

    @property
    def usage_percent(self) -> float:
        return round(self.used / self.size * 100, 1) if self.size else 0.0

    @property
    def available(self) -> int:
        return max(self.size - self.used, 0)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> StorageVolume:
        return cls(
            name=_s(d.get("name")),
            mount_point=_s(d.get("mount_point")),
            type=_s(d.get("type")),
            size=_i0(d.get("size")),
            used=_i0(d.get("used")),
        )


@dataclass(frozen=True, slots=True)
class Wan:
    """A WAN uplink interface, merging ``wanN`` with its ``uptime_stats`` entry."""

    id: str  # "WAN", "WAN2", ...
    ifname: str
    up: bool
    is_active: bool  # is this the currently-active uplink?
    enabled: bool
    ip: str  # PII — redacted in diagnostics; kept for the WAN-IP sensor
    media: str
    speed: int  # negotiated Mbps
    max_speed: int  # Mbps
    latency_ms: int | None
    availability: float | None  # %
    uptime_s: int | None
    rx_rate_bps: int  # bytes / second
    tx_rate_bps: int  # bytes / second
    rx_bytes: int
    tx_bytes: int

    @property
    def uptime_since(self) -> datetime | None:
        return _uptime(self.uptime_s)

    @classmethod
    def from_api(cls, wan_id: str, d: dict[str, Any], uptime: dict[str, Any]) -> Wan:
        return cls(
            id=wan_id,
            ifname=_s(d.get("ifname") or d.get("name")),
            up=_b(d.get("up")),
            is_active=_b(d.get("is_uplink")),
            enabled=_b(d.get("enable")),
            ip=_s(d.get("ip")),
            media=_s(d.get("media")),
            speed=_i0(d.get("speed")),
            max_speed=_i0(d.get("max_speed")),
            latency_ms=_i(uptime.get("latency_average")) if uptime else _i(d.get("latency")),
            availability=_fo(uptime.get("availability")) if uptime else _fo(d.get("availability")),
            uptime_s=_i(uptime.get("uptime")) if uptime else None,
            rx_rate_bps=_i0(d.get("rx_bytes-r")),
            tx_rate_bps=_i0(d.get("tx_bytes-r")),
            rx_bytes=_i0(d.get("rx_bytes")),
            tx_bytes=_i0(d.get("tx_bytes")),
        )


@dataclass(frozen=True, slots=True)
class SfpPort:
    """A physical SFP/SFP+ port (from the gateway ``port_table``).

    Every SFP port on the device is surfaced; ``present`` reflects whether a
    module is inserted (an empty cage is present=False, with empty vendor/part).
    UCG-Fiber firmware exposes presence + vendor/part + rx-LOS / tx-fault, but
    NOT optical DDM (rx/tx power, module temperature), so no optical sensors are
    modelled.
    """

    port_idx: int
    media: str
    present: bool
    vendor: str
    part: str
    rx_los: bool  # Receiver Loss Of Signal (a problem when True)
    tx_fault: bool  # Transmitter fault (a problem when True)

    @property
    def has_problem(self) -> bool:
        return self.present and (self.rx_los or self.tx_fault)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> SfpPort:
        return cls(
            port_idx=_i0(d.get("port_idx")),
            media=_s(d.get("media")),
            present=_b(d.get("sfp_found")),
            vendor=_s(d.get("sfp_vendor")),
            part=_s(d.get("sfp_part")),
            rx_los=_b(d.get("sfp_rx_los")),
            tx_fault=_b(d.get("sfp_tx_fault")),
        )


@dataclass(frozen=True, slots=True)
class Device:
    """The gateway/console device object from ``/stat/device``."""

    mac: str
    model: str
    type: str
    name: str
    firmware_version: str  # console/UniFi OS firmware (e.g. 5.1.19.33549)
    state: int  # 1 == connected
    uptime_s: int
    overheating: bool
    cpu_percent: float
    memory_percent: float
    loadavg_1: float
    loadavg_5: float
    loadavg_15: float
    memory_total: int  # bytes
    memory_used: int  # bytes
    num_clients: int
    temperatures: tuple[Temperature, ...]
    storage: tuple[StorageVolume, ...]
    wans: tuple[Wan, ...]
    sfp_ports: tuple[SfpPort, ...]

    @property
    def online(self) -> bool:
        return self.state == 1

    @property
    def uptime_since(self) -> datetime | None:
        return _uptime(self.uptime_s)

    @property
    def active_wan(self) -> Wan | None:
        return next((w for w in self.wans if w.is_active), None)

    @property
    def failover_active(self) -> bool:
        """True when the active uplink is not the primary (WAN1)."""
        active = self.active_wan
        return active is not None and active.id != "WAN"

    @property
    def persistent_storage(self) -> StorageVolume | None:
        """The main writable volume (the eMMC ``/persistent`` mount)."""
        return next((s for s in self.storage if s.mount_point == "/persistent"), None)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Device:
        sys_stats = d.get("sys_stats") or {}
        system_stats = d.get("system-stats") or {}
        uptime_stats = d.get("uptime_stats") or {}

        wans: list[Wan] = []
        for i in range(1, 7):
            wan_dict = d.get(f"wan{i}")
            if not isinstance(wan_dict, dict):
                continue
            wan_id = "WAN" if i == 1 else f"WAN{i}"
            up = uptime_stats.get(wan_id)
            wans.append(Wan.from_api(wan_id, wan_dict, up if isinstance(up, dict) else {}))

        # Every physical SFP/SFP+ port is surfaced (the device has a fixed number
        # of them); an empty cage reports present=False. Module details (vendor /
        # part) only populate when a module is inserted.
        sfp_ports: list[SfpPort] = []
        for p in d.get("port_table") or []:
            if not isinstance(p, dict):
                continue
            if "SFP" in _s(p.get("media")).upper():
                sfp_ports.append(SfpPort.from_api(p))

        return cls(
            mac=_s(d.get("mac")),
            model=_s(d.get("model")),
            type=_s(d.get("type")),
            name=_s(d.get("name")),
            firmware_version=_s(d.get("version")),
            state=_i0(d.get("state")),
            uptime_s=_i0(d.get("uptime")),
            overheating=_b(d.get("overheating")),
            cpu_percent=round(_f(system_stats.get("cpu")), 1),
            memory_percent=round(_f(system_stats.get("mem")), 1),
            loadavg_1=_f(sys_stats.get("loadavg_1")),
            loadavg_5=_f(sys_stats.get("loadavg_5")),
            loadavg_15=_f(sys_stats.get("loadavg_15")),
            memory_total=_i0(sys_stats.get("mem_total")),
            memory_used=_i0(sys_stats.get("mem_used")),
            num_clients=_i0(d.get("num_sta")),
            temperatures=tuple(
                Temperature.from_api(t) for t in d.get("temperatures") or [] if isinstance(t, dict)
            ),
            storage=tuple(
                StorageVolume.from_api(s) for s in d.get("storage") or [] if isinstance(s, dict)
            ),
            wans=tuple(wans),
            sfp_ports=tuple(sfp_ports),
        )


@dataclass(frozen=True, slots=True)
class Speedtest:
    """ISP speedtest result from the ``www`` health subsystem."""

    status: str
    download_mbps: float | None
    upload_mbps: float | None
    ping_ms: int | None
    latency_ms: int | None
    last_run: datetime | None

    @property
    def in_progress(self) -> bool:
        return self.status.lower() in ("running", "in_progress", "spawning")

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Speedtest:
        return cls(
            status=_s(d.get("speedtest_status")) or "unknown",
            download_mbps=_fo(d.get("xput_down")),
            upload_mbps=_fo(d.get("xput_up")),
            ping_ms=_i(d.get("speedtest_ping")),
            latency_ms=_i(d.get("latency")),
            last_run=_epoch(d.get("speedtest_lastrun")),
        )


@dataclass(frozen=True, slots=True)
class Isp:
    """ISP / uplink status from the ``wan`` health subsystem."""

    status: str
    name: str
    organization: str
    asn: int | None
    wan_ip: str  # PII — redacted in diagnostics

    @property
    def asn_label(self) -> str | None:
        """Autonomous-system number in canonical ``AS####`` form."""
        return f"AS{self.asn}" if self.asn is not None else None

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Isp:
        return cls(
            status=_s(d.get("status")),
            name=_s(d.get("isp_name")),
            organization=_s(d.get("isp_organization")),
            asn=_i(d.get("asn")),
            wan_ip=_s(d.get("wan_ip")),
        )


@dataclass(frozen=True, slots=True)
class Vpn:
    """VPN status from the ``vpn`` health subsystem."""

    status: str
    site_to_site_enabled: bool
    remote_enabled: bool
    remote_active: int
    remote_inactive: int

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Vpn:
        return cls(
            status=_s(d.get("status")),
            site_to_site_enabled=_b(d.get("site_to_site_enabled")),
            remote_enabled=_b(d.get("remote_user_enabled")),
            remote_active=_i0(d.get("remote_user_num_active")),
            remote_inactive=_i0(d.get("remote_user_num_inactive")),
        )


@dataclass(frozen=True, slots=True)
class Health:
    """Aggregated subsystem health from ``/stat/health``."""

    internet_status: str
    internet_latency_ms: int | None
    wan_status: str
    speedtest: Speedtest
    isp: Isp
    vpn: Vpn
    num_wired: int
    num_wireless: int
    num_guest: int
    num_iot: int
    num_ap: int
    num_switch: int

    @property
    def internet_up(self) -> bool:
        return self.internet_status.lower() == "ok"

    @classmethod
    def from_api(cls, data: Any) -> Health:
        rows = data if isinstance(data, list) else []
        subs: dict[str, dict[str, Any]] = {
            _s(r.get("subsystem")): r for r in rows if isinstance(r, dict)
        }
        www = subs.get("www", {})
        wan = subs.get("wan", {})
        lan = subs.get("lan", {})
        wlan = subs.get("wlan", {})
        vpn = subs.get("vpn", {})
        return cls(
            internet_status=_s(www.get("status")),
            internet_latency_ms=_i(www.get("latency")),
            wan_status=_s(wan.get("status")),
            speedtest=Speedtest.from_api(www),
            isp=Isp.from_api(wan),
            vpn=Vpn.from_api(vpn),
            num_wired=_i0(lan.get("num_user")),
            num_wireless=_i0(wlan.get("num_user")),
            num_guest=_i0(wlan.get("num_guest")),
            num_iot=_i0(wlan.get("num_iot")),
            num_ap=_i0(wlan.get("num_ap")),
            num_switch=_i0(lan.get("num_sw")),
        )


@dataclass(frozen=True, slots=True)
class SysInfo:
    """Controller / console info from ``/stat/sysinfo``."""

    netapp_version: str  # UniFi Network application version (e.g. 10.5.62)
    name: str  # friendly console name (e.g. "UCG Fiber")
    console_version: str  # UniFi OS display version (e.g. 5.1.19)
    previous_version: str
    timezone: str
    update_available: bool

    @classmethod
    def from_api(cls, data: Any) -> SysInfo:
        rows = data if isinstance(data, list) else [data]
        d = rows[0] if rows and isinstance(rows[0], dict) else {}
        return cls(
            netapp_version=_s(d.get("version")),
            name=_s(d.get("name")),
            console_version=_s(d.get("console_display_version")),
            previous_version=_s(d.get("previous_version")),
            timezone=_s(d.get("timezone")),
            update_available=_b(d.get("update_available")),
        )
