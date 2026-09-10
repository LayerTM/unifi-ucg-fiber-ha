#!/usr/bin/env python3
"""Secret / PII scanner — blocks device data from leaking into the public repo.

Pattern-based (no real device values are hardcoded here), so it protects *any*
contributor's device, not just one. Runs in pre-commit and CI. Exit code 1 on
any finding. Placeholder/example values (e.g. ``<redacted>``, ``AA:BB:CC:...``,
``EXAMPLE``) are allowed so sanitized fixtures and docs pass.

Usage:
    python scripts/secret_scan.py [path]   # default: current directory
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

# Snippets that mark a value as an intentional placeholder (allowed).
# NOTE: keep these anchored to explicit placeholder tokens. Do NOT add broad
# substrings like ``0{6,}`` or ``x{4,}`` — a real MAC/serial can contain long
# zero runs (e.g. ``F492BF000000``) and would then slip past the scanner.
ALLOW = re.compile(
    r"(?i)(redacted|example|placeholder|synthetic|dummy|sample|changeme|your[-_]?|"
    r"sk-ant-\.\.\.|<[a-z0-9_.\-]+>|aa:bb:cc|aabbcc|00:11:22|de:ad:be)"
)

# name -> compiled pattern. Each matches a *real-looking* secret/PII value.
PATTERNS: dict[str, re.Pattern[str]] = {
    "UniFi direct-connect domain": re.compile(r"(?i)\b[0-9a-z]{8,}\.[0-9a-z.]*id\.ui\.direct\b"),
    "JWT / bearer token": re.compile(
        r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{4,}"
    ),
    "MAC address": re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
    "MAC address (dotted)": re.compile(r"\b[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\b"),
    "MAC/serial (bare 12-hex)": re.compile(
        r"(?<![0-9A-Fa-f:.\-])[0-9A-Fa-f]{12}(?![0-9A-Fa-f:.\-])"
    ),
    "GPS coordinate field": re.compile(
        r'"(?:lat|lon|lng|long|latitude|longitude)"\s*:\s*-?\d{1,3}\.\d{3,}'
    ),
    "device serial field": re.compile(r'"serial(?:no|Number)?"\s*:\s*"[^"<\s][^"<]{2,}"'),
    "MAC field value": re.compile(r'"mac(?:Address)?"\s*:\s*"[^"<\s][^"<]{5,}"'),
    "directConnectDomain field": re.compile(r'"directConnectDomain"\s*:\s*"[^"<\s][^"<]+"'),
    "X-API-Key value": re.compile(r'(?i)x-api-key\s*[:=]\s*["\']?[A-Za-z0-9_\-]{16,}'),
    "TOKEN cookie value": re.compile(r"\bTOKEN=[A-Za-z0-9._\-]{16,}"),
    "hardcoded password": re.compile(r'(?i)\bpassword\b\s*[:=]\s*["\'][^"\'{}<\s]{4,}["\']'),
    # Generic service/cloud credentials and personal data (never belong in a
    # public repo). These complement the UniFi-specific patterns above.
    "Anthropic API key": re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"),
    "GitHub token (classic)": re.compile(r"\bghp_[A-Za-z0-9]{30,}"),
    "GitHub token (fine-grained)": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    "AWS access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "private key block": re.compile(r"BEGIN (RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY"),
    "personal macOS path": re.compile(r"/Users/[a-z]"),
    "personal email (gmail)": re.compile(r"[A-Za-z0-9._%+-]+@gmail\.com"),
    "private LAN IP": re.compile(r"\b(?:192\.168|10\.0\.0)\.\d{1,3}\b"),
}

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "captures",
    ".secrets",
}
SKIP_SUFFIX = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".svg",
    ".pdf",
    ".zip",
    ".gz",
    ".mo",
    ".woff",
    ".woff2",
}
# These files legitimately hold pattern literals / synthetic PII test vectors,
# so they are excluded from scanning (both are small and code-reviewed).
SKIP_FILES = {Path(__file__).name, "test_secret_scan.py"}


def _git_tracked(root: Path) -> list[Path] | None:
    """Files git would commit (tracked + untracked, excluding .gitignored)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-c", "-o", "--exclude-standard"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return [root / line for line in out.stdout.splitlines() if line]


def _is_binary(path: Path) -> bool:
    try:
        return b"\x00" in path.read_bytes()[:2048]
    except OSError:
        return True


def iter_files(root: Path) -> Iterator[Path]:
    # Scan exactly what git would commit (respects .gitignore, so venvs/caches
    # are excluded); fall back to a filtered filesystem walk outside a git repo.
    tracked = _git_tracked(root)
    candidates = tracked if tracked is not None else sorted(root.rglob("*"))
    for p in candidates:
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in SKIP_SUFFIX:
            continue
        if p.name in SKIP_FILES:
            continue
        if _is_binary(p):
            continue
        yield p


def scan_text(text: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for name, rx in PATTERNS.items():
        for m in rx.finditer(text):
            snippet = m.group(0)
            if ALLOW.search(snippet):
                continue
            hits.append((name, snippet[:70]))
    return hits


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path()
    problems: list[tuple[Path, str, str]] = []
    for f in iter_files(root):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name, snip in scan_text(text):
            problems.append((f, name, snip))

    if problems:
        print("SECRET-SCAN: potential PII/secret leakage detected:\n", file=sys.stderr)
        for f, name, snip in problems:
            print(f"  {f}: [{name}] {snip}", file=sys.stderr)
        print(
            "\nBlocked. Sanitize the value, add a placeholder, or move it to a "
            "gitignored path (captures/, .secrets/).",
            file=sys.stderr,
        )
        return 1

    print("secret-scan: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
