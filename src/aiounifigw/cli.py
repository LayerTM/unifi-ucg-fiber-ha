"""Command-line interface for aiounifigw.

Install with ``pip install "aiounifigw[cli]"``. Credentials come from the
environment:

* ``UNIFI_GW_HOST`` — gateway IP/host (required)
* ``UNIFI_GW_APIKEY`` — API key (recommended), OR
* ``UNIFI_GW_USER`` + ``UNIFI_GW_PASS`` — local account
* ``UNIFI_GW_SITE`` — site name (default ``default``)
* ``UNIFI_GW_PORT`` — console port (default 443)

TLS trust, in order of precedence:

* ``UNIFI_GW_CERT_FINGERPRINT`` — accept only this SHA-256 certificate
  (print it with ``unifi-gateway fingerprint``)
* ``UNIFI_GW_VERIFY_SSL`` — set truthy to verify against the system CA store
* neither — **unverified**, the historical behaviour of these developer tools
"""

from __future__ import annotations

import asyncio
import json as jsonlib
from typing import Any

import aiohttp
import typer
from rich.console import Console
from rich.table import Table

from .exceptions import GwError
from .summary import env_host, env_port, make_action_client, make_client, read_all, status_payload
from .tls import async_probe_fingerprint

app = typer.Typer(add_completion=False, help="Query a UniFi OS gateway (UCG/UDM/UXG) locally.")
console = Console()
# Failures go to stderr, so `VALUE=$(unifi-gateway fingerprint)` captures a
# fingerprint or nothing — never an error message that would then be pinned.
err_console = Console(stderr=True)


def _run(coro: Any) -> Any:
    """Run a command's work, reporting the two failures a user can act on.

    Both arrive here rather than at each command: a gateway that cannot be
    reached (``GwError``) and an environment that does not describe one
    (``ValueError`` from the ``UNIFI_GW_*`` readers, including a malformed
    ``UNIFI_GW_CERT_FINGERPRINT``). A traceback states neither.
    """
    try:
        return asyncio.run(coro)
    except (GwError, ValueError) as err:
        err_console.print(f"[red]{err}[/]")
        raise typer.Exit(1) from err


@app.command()
def status(as_json: bool = typer.Option(False, "--json", help="Machine-readable output.")) -> None:
    """Show a gateway / WAN / internet summary."""

    async def _go() -> dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            device, health, sysinfo = await read_all(make_client(session))
            return status_payload(device, health, sysinfo)

    payload = _run(_go())
    if as_json:
        console.print_json(jsonlib.dumps(payload))
        return

    c = payload["console"]
    i = payload["internet"]
    st = i["speedtest"]
    console.print(f"[bold]{c['name']}[/] · {c['model']} · UniFi OS fw {c['firmware']}")
    table = Table(show_header=False, box=None)
    table.add_row("Online", "yes" if c["online"] else "no")
    table.add_row("CPU / Memory", f"{c['cpu_percent']}% / {c['memory_percent']}%")
    table.add_row("Clients", str(c["clients"]))
    table.add_row(
        "Internet", ("up" if i["up"] else "down") + f" · {i['isp'] or '?'} ({i['asn'] or '?'})"
    )
    table.add_row("Latency", f"{i['latency_ms']} ms" if i["latency_ms"] is not None else "-")
    table.add_row(
        "Speedtest", f"{st['download_mbps']} / {st['upload_mbps']} Mbit/s ({st['status']})"
    )
    table.add_row(
        "Active WAN",
        f"{payload['active_wan']}" + (" (failover!)" if payload["failover_active"] else ""),
    )
    console.print(table)

    wt = Table(title="WAN uplinks")
    for col in ("WAN", "Up", "Media", "Speed", "Latency", "Avail"):
        wt.add_column(col)
    for w in payload["wans"]:
        wt.add_row(
            w["id"],
            "yes" if w["up"] else "no",
            w["media"],
            f"{w['speed_mbps']}M",
            f"{w['latency_ms']}ms" if w["latency_ms"] is not None else "-",
            f"{w['availability']}%" if w["availability"] is not None else "-",
        )
    console.print(wt)


@app.command()
def speedtest(yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation.")) -> None:
    """Trigger an ISP speedtest on the active WAN (write; needs write-capable auth)."""
    if not yes:
        typer.confirm("Run an ISP speedtest on the gateway now?", abort=True)

    async def _go() -> None:
        async with aiohttp.ClientSession() as session:
            await make_action_client(session).run_speedtest()

    _run(_go())
    console.print("[green]speedtest triggered[/] — results appear after it finishes")


@app.command()
def fingerprint() -> None:
    """Print the SHA-256 fingerprint of the gateway's TLS certificate.

    Read it here, compare it with the one the console shows, then pin it — via
    UNIFI_GW_CERT_FINGERPRINT for these tools, or by accepting it in the Home
    Assistant setup flow. Nothing is trusted by running this.
    """

    async def _go() -> str:
        # Read inside the coroutine: an argument evaluated at the call site would
        # raise past _run, which is where an unset UNIFI_GW_HOST is reported.
        return await async_probe_fingerprint(env_host(), env_port())

    # Plain, unwrapped: this is a value to copy or capture in `$(...)`, and a
    # 95-character fingerprint is wider than many terminals.
    typer.echo(_run(_go()))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
