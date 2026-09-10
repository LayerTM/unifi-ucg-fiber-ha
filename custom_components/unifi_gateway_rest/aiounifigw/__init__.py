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
    Device,
    Health,
    Isp,
    SfpPort,
    Speedtest,
    StorageVolume,
    SysInfo,
    SystemIdentity,
    Temperature,
    Vpn,
    Wan,
)
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
    "AbstractAuth",
    "ApiKeyAuth",
    "Capabilities",
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
    "Isp",
    "SessionAuth",
    "SfpPort",
    "Speedtest",
    "StorageVolume",
    "SysInfo",
    "SystemIdentity",
    "Temperature",
    "TlsMode",
    "Vpn",
    "Wan",
    "async_probe_fingerprint",
    "format_fingerprint",
    "parse_fingerprint",
    "probe",
    "ssl_param",
]
