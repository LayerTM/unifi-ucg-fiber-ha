"""Command-line interface for aiounifigw.

Install with ``pip install "aiounifigw[cli]"``. Credentials come from the
environment:

* ``UNIFI_GW_HOST`` — gateway IP/host (required)
* ``UNIFI_GW_APIKEY`` — API key (recommended), OR
* ``UNIFI_GW_USER`` + ``UNIFI_GW_PASS`` — local account
* ``UNIFI_GW_SITE`` — site name (default ``default``)
* ``UNIFI_GW_VERIFY_SSL`` — set truthy to verify TLS (off by default)
"""

from __future__ import annotations

import asyncio
import json as jsonlib
from typing import Any

import aiohttp
import typer
from rich.console import Console
from rich.table import Table

from .summary import make_action_client, make_client, read_all, status_payload

app = typer.Typer(add_completion=False, help="Query a UniFi OS gateway (UCG/UDM/UXG) locally.")
console = Console()


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
