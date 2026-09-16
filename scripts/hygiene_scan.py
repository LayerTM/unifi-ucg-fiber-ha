#!/usr/bin/env python3
"""Repository hygiene — traces of one machine must not reach a distribution.

This repository is copied onto machines that are nothing like the one a change
was written on, so anything that only resolves on the author's computer is a
defect there: an absolute home-directory path, a temporary-directory path, a
symlink pointing at something the clone does not contain. None of it fails a
build here, and all of it fails somewhere else — which is why it needs a check
rather than a habit.

The same applies to the by-products of authoring tools. A link to an editing or
chat transcript is only reachable by the person who made it, and an attribution
trailer belongs to commit metadata, not to a file that ships.

WHAT THIS DOES NOT OWN. Secrets, personal e-mail addresses and non-routable
network addresses belong to ``secret_scan.py``. This scanner matches none of
them, and the one place the two deliberately meet — a macOS home path, which is
both a machine path and personal data — is pinned by ``test_hygiene_scan.py`` so
that neither scanner's scope can drift into the other's unnoticed.

FAIL CLOSED. A tracked file that cannot be read or decoded is a FAILURE, not a
skip: "I could not look" and "I looked and it was clean" must not share an exit
code. Tracked files only — what is not tracked is not distributed.

Usage:
    python scripts/hygiene_scan.py [path]   # default: current directory
Exit: 0 clean, 1 findings, 2 the scan could not be performed.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]


RULES: list[Rule] = [
    # A path rooted in somebody's home or in a per-boot temporary directory.
    # Two boundaries matter, and both were found by running this over a real
    # tree rather than by reasoning about it. A trailing separator, so that a
    # mention of the directory itself ("files under /Users") is not read as a
    # path into it. And a leading one: an application that keeps its own home
    # under a data directory writes /data/home/... , which contains "/home/"
    # without being anybody's home directory — and a path assembled from a
    # variable, "${work}/home/x", is a temporary directory, not this machine.
    # The one place a leading slash is not a segment boundary is a file:// URL,
    # which is how such a path reaches a README or a launch configuration, so
    # that scheme is matched explicitly rather than excluded with everything else.
    Rule(
        "machine-path",
        re.compile(
            r"(?<![A-Za-z0-9._/})-])(?:file://)?"
            r"(?:/Users/[A-Za-z0-9._-]+/"
            r"|/home/[A-Za-z0-9._-]+/"
            r"|/private/tmp/[A-Za-z0-9._-]+"
            r"|/var/folders/[A-Za-z0-9._+-]+"
            r"|[A-Za-z]:\\Users\\[A-Za-z0-9._-]+)"
        ),
    ),
    # A link into an authoring session: private to whoever created it, dead for
    # every reader of the repository.
    Rule(
        "transcript-url",
        re.compile(r"(?i)\bclaude\.ai/code/session[_/][A-Za-z0-9_-]+"),
    ),
    # Trailers are commit metadata. In a tracked file they are a copy that no
    # longer describes anything, and they name people and tools the file does
    # not otherwise involve.
    Rule(
        "attribution-trailer",
        re.compile(
            r"(?im)^[ \t]*co-authored-by[ \t]*:"
            r"|^[ \t]*(?:\U0001f916[ \t]*)?generated with[ \t]"
        ),
    ),
]

# This file and its test contain every pattern literally, so they are skipped by
# exact repository-relative path. A file of the same name anywhere else is scanned.
SELF = {
    "scripts/hygiene_scan.py",
    "scripts/test_hygiene_scan.py",
}

SKIP_SUFFIX = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".mo",
    ".woff",
    ".woff2",
    ".ttf",
}

OWNERSHIP = (
    "hygiene: machine-specific paths, symlinks leaving the repository, "
    "transcript URLs and attribution trailers.\n"
    "secret-scan: secrets, personal e-mail addresses and non-routable network "
    "addresses."
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int  # 0 = the file itself rather than a line in it
    rule: str
    text: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule} — {self.text[:70]}"


class ScanError(Exception):
    """The scan could not be performed — never reported as a clean tree."""


def tracked_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScanError(f"cannot list tracked files in {root}: {exc}") from exc
    return [p for p in out.stdout.split("\0") if p]


def symlink_finding(root: Path, rel: str) -> Finding | None:
    """A symlink is a file whose content is a path.

    One that is absolute, or that climbs out of the repository, describes a
    layout no clone has.
    """
    full = root / rel
    if not full.is_symlink():
        return None
    try:
        target = full.readlink()
    except OSError as exc:
        return Finding(rel, 0, "symlink-unreadable", str(exc))
    if target.is_absolute():
        return Finding(rel, 0, "symlink-absolute", f"-> {target}")
    # Repository paths are POSIX-shaped and so is a symlink target inside one.
    climbed = PurePosixPath(rel).parent / PurePosixPath(target.as_posix())
    parts: list[str] = []
    for part in climbed.parts:
        if part == "..":
            if not parts:
                return Finding(rel, 0, "symlink-outside-repo", f"-> {target}")
            parts.pop()
        elif part != ".":
            parts.append(part)
    return None


def file_text(root: Path, rel: str) -> str | None:
    """The file's text, or None when it is binary.

    Raises when it cannot be read or decoded; the caller turns that into a
    finding, never into a pass.
    """
    try:
        data = (root / rel).read_bytes()
    except OSError as exc:
        raise ScanError(str(exc)) from exc
    if b"\x00" in data[:2048]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScanError(f"not UTF-8 text: {exc}") from exc


def scan_text(text: str, rules: list[Rule] | None = None) -> list[tuple[str, str]]:
    """(rule name, matched text) for one line."""
    hits: list[tuple[str, str]] = []
    for rule in rules if rules is not None else RULES:
        hits.extend((rule.name, match.group(0)) for match in rule.pattern.finditer(text))
    return hits


def scan(root: Path, rules: list[Rule] | None = None, symlinks: bool = True) -> list[Finding]:
    findings: list[Finding] = []
    for rel in tracked_files(root):
        if rel in SELF:
            continue
        if symlinks:
            link = symlink_finding(root, rel)
            if link is not None:
                findings.append(link)
                continue  # its content is the target, already judged
        elif (root / rel).is_symlink():
            continue
        if PurePosixPath(rel).suffix.lower() in SKIP_SUFFIX:
            continue
        try:
            text = file_text(root, rel)
        except ScanError as exc:
            findings.append(Finding(rel, 0, "unreadable", str(exc)))
            continue
        if text is None:
            continue  # binary
        for lineno, line in enumerate(text.splitlines(), 1):
            findings.extend(Finding(rel, lineno, name, found) for name, found in scan_text(line))
    return findings


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path()
    try:
        findings = scan(root)
    except ScanError as exc:
        print(f"::error::hygiene: {exc}", file=sys.stderr)
        return 2
    if findings:
        print(
            "::error::hygiene: this tree carries traces of the machine it was written on:\n",
            file=sys.stderr,
        )
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(f"\n{OWNERSHIP}", file=sys.stderr)
        return 1
    print("hygiene: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
