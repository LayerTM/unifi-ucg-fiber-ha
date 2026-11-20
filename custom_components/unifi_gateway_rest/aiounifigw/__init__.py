"""aiounifigw — async client for the UniFi OS gateway (UCG/UDM/UXG) local REST API."""

from __future__ import annotations

from .actions import GatewayActionClient
from .auth import AbstractAuth, ApiKeyAuth, SessionAuth
from .capabilities import Capabilities, probe
from .client import GatewayClient
from .exceptions import (
    GwApiError,
    GwAuthError,
    GwCapabilityError,
    GwConnectionError,
    GwError,
)
from .models import (
    DASHBOARD_WINDOW_S,
    ConsoleBackup,
    Dashboard,
    Device,
    Health,
    IpsSignatures,
    Isp,
    SfpPort,
    Speedtest,
    StorageVolume,
    SysInfo,
    SystemIdentity,
    Temperature,
    ThreatDetection,
    Vpn,
    Wan,
    WanQuality,
)
from .system_log import SystemLog, SystemLogCursor, SystemLogEntry
from .tls import (
    GwCertificateMismatch,
    TlsMode,
    async_probe_fingerprint,
    format_fingerprint,
    parse_fingerprint,
    ssl_param,
)
from .transport import GatewayTransport

__all__ = [
    "DASHBOARD_WINDOW_S",
    "AbstractAuth",
    "ApiKeyAuth",
    "Capabilities",
    "ConsoleBackup",
    "Dashboard",
    "Device",
    "GatewayActionClient",
    "GatewayClient",
    "GatewayTransport",
    "GwApiError",
    "GwAuthError",
    "GwCapabilityError",
    "GwCertificateMismatch",
    "GwConnectionError",
    "GwError",
    "Health",
    "IpsSignatures",
    "Isp",
    "SessionAuth",
    "SfpPort",
    "Speedtest",
    "StorageVolume",
    "SysInfo",
    "SystemIdentity",
    "SystemLog",
    "SystemLogCursor",
    "SystemLogEntry",
    "Temperature",
    "ThreatDetection",
    "TlsMode",
    "Vpn",
    "Wan",
    "WanQuality",
    "async_probe_fingerprint",
    "format_fingerprint",
    "parse_fingerprint",
    "probe",
    "ssl_param",
]
