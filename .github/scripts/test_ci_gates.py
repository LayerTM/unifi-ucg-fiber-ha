#!/usr/bin/env python3
"""Self-test for ci_gates.py — the rules every workflow and script is held to.

Its whole value is in what it REFUSES: a checker that passes everything would
keep the rules looking enforced while a workflow broke them. So each rule is
asserted in both directions, the named exceptions are held to exactly what they
name, and the repository's own files are checked last.

Run: python3 .github/scripts/test_ci_gates.py
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).resolve().parent / "ci_gates.py"
REPO = SCRIPT.parents[2]

fails = 0




def check(label: str, got, want) -> None:
    global fails
    if got == want:
        print(f"  ok  - {label}")
    else:
        print(f"  NOT ok - {label} (got {got!r}, want {want!r})")


print("A curl that retries must retry every error, not only the transient HTTP ones")
sys.path.insert(0, str(SCRIPT.parent))
from ci_gates import curl_retry_complaints  # noqa: E402

BAD = "curl -fsSL --retry 3 --retry-delay 2 -o /f https://x/y"
check("--retry alone is refused", len(curl_retry_complaints("f", BAD)), 1)
check("--retry-all-errors is accepted", curl_retry_complaints("f", BAD.replace("--retry 3", "--retry 3 --retry-all-errors")), [])
check("no --retry is not this rule", curl_retry_complaints("f", "curl -fsSL -o /f https://x/y"), [])
check("--retry-delay alone is not --retry", curl_retry_complaints("f", "curl -fsSL --retry-delay 2 https://x/y"), [])
check("a continuation line is one command", len(curl_retry_complaints("f", "RUN curl -fsSL --retry 3 \\\n    -o /f https://x/y")), 1)
check("a flag on a continuation line counts", curl_retry_complaints("f", "RUN curl -fsSL --retry 3 \\\n    --retry-all-errors -o /f https://x/y"), [])
check("each curl in a && chain is judged alone", len(curl_retry_complaints("f", "curl --retry 3 --retry-all-errors a && curl --retry 3 b")), 1)

print("A pip install must demand hashes")
from ci_gates import pip_hash_complaints  # noqa: E402

check("an unhashed install is refused", len(pip_hash_complaints("f", "run: python3 -m pip install --quiet pyyaml")), 1)
check("pip3 is the same command", len(pip_hash_complaints("f", "pip3 install requests")), 1)
check("uv pip install is the same command", len(pip_hash_complaints("f", "uv pip install requests")), 1)
check("--require-hashes is accepted", pip_hash_complaints("f", "python3 -m pip install --require-hashes --no-deps -r a.lock"), [])
check("a flag on a continuation line counts", pip_hash_complaints("f", "RUN pip install --no-deps \\\n    --require-hashes -r a.lock"), [])
check("--require-hashes of another command does not count", len(pip_hash_complaints("f", "pip install x && echo --require-hashes")), 1)
check("each pip in a && chain is judged alone", len(pip_hash_complaints("f", "pip install --require-hashes -r a && pip install b")), 1)
check("a comment line runs nothing", pip_hash_complaints("f", "# or: pip install pre-commit\n  # pip install x\n"), [])
check("the word pip alone is not an install", pip_hash_complaints("f", "apt-get install python3-pip"), [])

print("An npm install must come from a lock")
from ci_gates import npm_package_complaints  # noqa: E402

check("a version-only install is refused", len(npm_package_complaints("f", 'RUN npm install --global --no-audit "some-package@${V}"')), 1)
check("npm i and npm add are the same command", len(npm_package_complaints("f", "npm i left-pad && npm add right-pad")), 2)
check("npm ci is accepted", npm_package_complaints("f", "RUN npm ci --omit=dev"), [])
check("a lockfile refresh names no package", npm_package_complaints("f", "npm install --package-lock-only --ignore-scripts"), [])

print("Only the named installs may float")
from ci_gates import check_curl_retries, floating  # noqa: E402


def complaint(command):
    return pip_hash_complaints("w.yml", command)[0]


check("the project with extras floats", floating(complaint('pip install -e ".[dev,ha]"')), True)
check("the project alone floats", floating(complaint('pip install -e "."')), True)
check("the minimum harness resolution floats", floating(complaint(
    'pip install "pytest-homeassistant-custom-component" "homeassistant==$MIN"')), True)
check("a named package does not float", floating(complaint("pip install uv")), False)
check("the project plus a package does not float", floating(complaint('pip install -e "." uv')), False)
check("another path does not float", floating(complaint('pip install -e "../other"')), False)
check("a curl complaint is never exempt", floating("w.yml: curl has --retry but not --retry-all-errors: curl"), False)
check("the repository's scripts and workflows pass the download and pip rules",
      [c for c in check_curl_retries(REPO) if not floating(c)], [])

print("A pipe must run under a pipefail shell")
import yaml  # noqa: E402
from ci_gates import pipefail_complaints  # noqa: E402

PIPED = "name: w\non: [push]\n{top}jobs:\n  j:\n{job}    runs-on: ubuntu-latest\n    steps:\n      - {step}run: producer | tee -a \"$GITHUB_OUTPUT\"\n"


def piped(top="", job="", step=""):
    return pipefail_complaints("w.yml", yaml.safe_load(PIPED.format(top=top, job=job, step=step)))


check("a pipe under the default shell is refused", len(piped()), 1)
check("it names the step", "job 'j' step 1" in piped()[0], True)
check("a step's shell: bash passes", piped(step="shell: bash\n        "), [])
check("workflow defaults pass", piped(top="defaults:\n  run:\n    shell: bash\n"), [])
check("job defaults pass", piped(job="    defaults:\n      run:\n        shell: bash\n"), [])
check("an explicit pipefail-less bash -e is refused", len(piped(step="shell: bash -e {0}\n        ")), 1)
check("a step's shell overrides a good default", len(piped(top="defaults:\n  run:\n    shell: bash\n", step="shell: sh\n        ")), 1)
check("|| is not a pipe", pipefail_complaints("w.yml", yaml.safe_load("jobs:\n  j:\n    steps:\n      - run: a || b\n")), [])
check("a comment line is not a pipe", pipefail_complaints("w.yml", yaml.safe_load("jobs:\n  j:\n    steps:\n      - run: |\n          # a | b\n          true\n")), [])
repo_run = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=REPO)
check("every workflow in the repository passes", repo_run.returncode, 0)
check("and says nothing", repo_run.stderr.strip(), "")

print("The mechanism: a failing producer behind tee")
bare = subprocess.run(["bash", "-e", "-c", "false | tee /dev/null"], capture_output=True)
piper = subprocess.run(["bash", "-eo", "pipefail", "-c", "false | tee /dev/null"], capture_output=True)
check("bash -e stays green", bare.returncode, 0)
check("bash -eo pipefail fails", piper.returncode, 1)

print(f"\n{'FAILED' if fails else 'ok'} — {fails} failing check(s)")
sys.exit(1 if fails else 0)
