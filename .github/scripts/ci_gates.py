#!/usr/bin/env python3
"""Rules every workflow and shell script in this repository is held to.

curl's --retry covers only a timeout and HTTP 408/429/500/502/503/504, so a
connection that dies mid-transfer (exit 56) is never retried by it. A curl that
asks for --retry therefore also asks for --retry-all-errors, in every Dockerfile,
shell script and workflow.

A `pip install` installs only from a hash-locked requirements file
(`--require-hashes`), so a package index that serves another file under a pinned
name fails the install instead of running in CI. The exceptions are named in
FLOATING below: the installs of this project and of its test dependencies, which
resolve to the newest releases on purpose (see `pyproject.toml`), so there is no
pinned name for an index to substitute. The CI tools are hash-locked in
`.github/ci-tools/requirements.txt`.

An image or workflow step never runs `npm install <package>` (a version alone is
not an integrity check); it installs a package.json with `npm ci` from the
package-lock.json beside it, which fails on a tarball whose integrity differs.

A workflow `run:` that pipes runs under a pipefail shell. GitHub's default
(`bash -e {0}`, no `shell:`) returns the LAST command's status, so
`producer | tee -a "$GITHUB_OUTPUT"` stays green when the producer fails;
`shell: bash` (`bash --noprofile --norc -eo pipefail {0}`) fails the step that
failed. A step's own `shell:`, or a job's or the workflow's `defaults.run.shell`,
supplies it.

Usage:
  ci_gates.py   -> silent and 0 when every rule holds
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]

# The installs that float on purpose, each the whole command as a workflow runs it.
FLOATING = (
    # The project with its extras: the library and test dependencies are lower
    # bounds, and CI tests the newest release of each.
    re.compile(r'pip install -e "\.(\[[a-z,]+\])?"'),
    # The minimum-version job lets the resolver pick the harness that pins the
    # oldest supported Home Assistant. pip, not uv: that release pins an aiohttp
    # since yanked, which pip installs when it is pinned exactly and uv refuses.
    re.compile(r'pip install "pytest-homeassistant-custom-component" "homeassistant==\$MIN"'),
)


# One curl invocation, ending at the next shell separator or the end of the
# (continuation-joined) line.
CURL = re.compile(r"\bcurl\b(?:(?!&&|\|\||[;|\n]).)*")
RETRY = re.compile(r"(?<![\w-])--retry(?![\w-])")
RETRY_ALL = re.compile(r"(?<![\w-])--retry-all-errors(?![\w-])")
# One `pip install` command (also `python -m pip install`, `uv pip install`).
PIP_INSTALL = re.compile(r"\bpip3?\s+install\b(?:(?!&&|\|\||[;|\n]).)*")
REQUIRE_HASHES = re.compile(r"(?<![\w-])--require-hashes(?![\w-])")
# One `npm install|i|add` command; `npm install` of no package (a lockfile refresh) is fine.
NPM_INSTALL = re.compile(r"\bnpm\s+(?:install|i|add)\b((?:(?!&&|\|\||[;|\n]).)*)")
NPM_SCANNED = re.compile(r"(^|/)Dockerfile[^/]*$|^\.github/.*\.(sh|ya?ml)$")
SCANNED = re.compile(r"(^|/)Dockerfile[^/]*$|\.(sh|ya?ml)$")


def curl_retry_complaints(name: str, text: str) -> list[str]:
    """Each curl in `text` that sets --retry without --retry-all-errors."""
    joined = re.sub(r"\\\n", " ", text)
    return [
        f"{name}: curl has --retry but not --retry-all-errors: {m.group(0).strip()[:90]}"
        for m in CURL.finditer(joined)
        if RETRY.search(m.group(0)) and not RETRY_ALL.search(m.group(0))
    ]


def pip_hash_complaints(name: str, text: str) -> list[str]:
    """Each `pip install` in `text` that does not demand hashes (a comment line runs nothing)."""
    code = re.sub(r"^[ \t]*#.*$", "", text, flags=re.MULTILINE)
    joined = re.sub(r"\\\n", " ", code)
    return [
        f"{name}: pip install without --require-hashes: {m.group(0).strip()[:90]}"
        for m in PIP_INSTALL.finditer(joined)
        if not REQUIRE_HASHES.search(m.group(0))
    ]


def npm_package_complaints(name: str, text: str) -> list[str]:
    """Each `npm install <package>` in `text` (a comment line runs nothing)."""
    code = re.sub(r"^[ \t]*#.*$", "", text, flags=re.MULTILINE)
    joined = re.sub(r"\\\n", " ", code)
    return [
        f"{name}: npm install of a package by name, not from a lock (use npm ci): {m.group(0).strip()[:90]}"
        for m in NPM_INSTALL.finditer(joined)
        if any(not arg.startswith("-") for arg in m.group(1).split())
    ]


# A pipe, not `||`.
PIPE = re.compile(r"(?<!\|)\|(?!\|)")


def pipefail_complaints(name: str, workflow) -> list[str]:
    """Each step of a parsed workflow that pipes under a shell without pipefail."""
    if not isinstance(workflow, dict) or not isinstance(workflow.get("jobs"), dict):
        return []

    def shell_of(owner) -> object:
        defaults = owner.get("defaults") if isinstance(owner, dict) else None
        run = defaults.get("run") if isinstance(defaults, dict) else None
        return run.get("shell") if isinstance(run, dict) else None

    complaints = []
    for job_id, job in workflow["jobs"].items():
        if not isinstance(job, dict):
            continue
        for index, step in enumerate(job.get("steps") or []):
            body = step.get("run") if isinstance(step, dict) else None
            if not isinstance(body, str):
                continue
            code = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
            if not PIPE.search(code):
                continue
            shell = step.get("shell") or shell_of(job) or shell_of(workflow)
            if not (isinstance(shell, str) and (shell == "bash" or "pipefail" in shell)):
                complaints.append(
                    f"{name}: job '{job_id}' step {index + 1} pipes without a pipefail shell "
                    f"(set `shell: bash` on the step or under `defaults.run`): a failing "
                    f"producer would leave the step green"
                )
    return complaints


def check_curl_retries(root: pathlib.Path) -> list[str]:
    """Scan every tracked Dockerfile, shell script and workflow under `root`."""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files"], capture_output=True, text=True
    )
    if listed.returncode != 0:
        return [f"cannot list the files of {root}: {listed.stderr.strip()}"]
    complaints = []
    for rel in listed.stdout.splitlines():
        if SCANNED.search(rel) and (root / rel).is_file():
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
            complaints += curl_retry_complaints(rel, text) + pip_hash_complaints(rel, text)
            if NPM_SCANNED.search(rel):
                complaints += npm_package_complaints(rel, text)
    return complaints


def floating(complaint: str) -> bool:
    """Whether a pip-hash complaint names one of the FLOATING installs."""
    _, _, command = complaint.partition(": pip install without --require-hashes: ")
    return any(pattern.fullmatch(command) for pattern in FLOATING)


def main() -> None:
    complaints = [c for c in check_curl_retries(ROOT) if not floating(c)]
    for workflow in sorted((ROOT / ".github/workflows").glob("*.yml")):
        complaints += pipefail_complaints(
            workflow.name, yaml.safe_load(workflow.read_text(encoding="utf-8"))
        )
    if complaints:
        for line in complaints:
            print(line, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
