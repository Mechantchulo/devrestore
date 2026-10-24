"""Small, side-effect-free Linux system detector."""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

from devrestore.core.models import SystemInfo


def parse_os_release(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key.isidentifier():
            result[key] = value.strip().strip('"').strip("'")
    return result


def detect_system(os_release: Path = Path("/etc/os-release")) -> SystemInfo:
    try:
        values = parse_os_release(os_release.read_text(encoding="utf-8"))
    except OSError:
        values = {}
    distro = values.get("ID", "unknown").lower()
    family = (
        "debian"
        if distro in {"ubuntu", "debian"}
        else "fedora"
        if distro == "fedora"
        else "unknown"
    )
    managers = [
        name
        for name in ("apt", "dnf", "pipx", "npm", "pnpm", "cargo", "flatpak")
        if shutil.which(name)
    ]
    version_managers = [name for name in ("fnm", "pyenv", "rustup", "uv") if shutil.which(name)]
    if (Path.home() / ".nvm").is_dir():
        version_managers.append("nvm")
    return SystemInfo(
        distro=distro,
        version=values.get("VERSION_ID", "unknown"),
        family=family,
        architecture=platform.machine(),
        shell=os.environ.get("SHELL", "unknown"),
        package_managers=managers,
        version_managers=version_managers,
    )
