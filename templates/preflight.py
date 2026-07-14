#!/usr/bin/env python3
"""Stdlib-only, non-secret environment capability probes for project controls."""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


def configured_environment(name: str, dotenv: Path | None) -> bool:
    if os.environ.get(name):
        return True
    if dotenv is None or not dotenv.is_file():
        return False
    for raw in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip().removeprefix("export ").strip() == name and value.strip().strip("'\""):
            return True
    return False


def quiet_command(command: list[str], timeout: int = 10) -> bool:
    try:
        return subprocess.run(
            command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def has_privilege() -> bool:
    return (hasattr(os, "geteuid") and os.geteuid() == 0) or quiet_command(["sudo", "-n", "true"])


def has_cap_bpf() -> bool:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return True
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
        cap_eff = next(line.split()[1] for line in status.splitlines() if line.startswith("CapEff:"))
        if int(cap_eff, 16) & (1 << 39):
            return True
    except (OSError, StopIteration, ValueError):
        pass
    return quiet_command(["sudo", "-n", "true"])


def writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".guardrails-preflight-", dir=path)
        os.close(descriptor)
        Path(name).unlink()
        return True
    except OSError:
        return False


def network(host: str, port: int, timeout: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def browser() -> bool:
    if any(shutil.which(name) for name in ("chromium", "chromium-browser", "google-chrome")):
        return True
    cache = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", Path.home() / ".cache" / "ms-playwright"))
    return cache.is_dir() and any(cache.iterdir())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="probe", required=True)
    command = sub.add_parser("command")
    command.add_argument("name")
    path = sub.add_parser("writable")
    path.add_argument("path")
    environment = sub.add_parser("env")
    environment.add_argument("name")
    environment.add_argument("--dotenv")
    endpoint = sub.add_parser("network")
    endpoint.add_argument("host")
    endpoint.add_argument("port", type=int)
    endpoint.add_argument("--timeout", type=int, default=5)
    sub.add_parser("root")
    sub.add_parser("cap-bpf")
    sub.add_parser("docker")
    sub.add_parser("browser")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    available = {
        "command": lambda: shutil.which(args.name) is not None,
        "writable": lambda: writable(Path(args.path).expanduser()),
        "env": lambda: configured_environment(
            args.name, Path(args.dotenv).expanduser() if args.dotenv else None,
        ),
        "network": lambda: network(args.host, args.port, args.timeout),
        "root": has_privilege,
        "cap-bpf": has_cap_bpf,
        "docker": lambda: quiet_command(["docker", "info"]),
        "browser": browser,
    }[args.probe]()
    return 0 if available else 1


if __name__ == "__main__":
    raise SystemExit(main())
