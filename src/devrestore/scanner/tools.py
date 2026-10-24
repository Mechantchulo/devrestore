"""Allowlisted executable probes. No executable name comes from a manifest."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

from devrestore.core.models import ScanResult, Tool
from devrestore.scanner.sdks import scan_sdks
from devrestore.scanner.system import detect_system


@dataclass(frozen=True)
class Probe:
    executable: str
    arguments: tuple[str, ...]
    category: str


PROBES: dict[str, Probe] = {
    "git": Probe("git", ("--version",), "core"),
    "docker": Probe("docker", ("--version",), "devops"),
    "podman": Probe("podman", ("--version",), "devops"),
    "code": Probe("code", ("--version",), "editor"),
    "nvim": Probe("nvim", ("--version",), "editor"),
    "vim": Probe("vim", ("--version",), "editor"),
    "gh": Probe("gh", ("--version",), "core"),
    "curl": Probe("curl", ("--version",), "core"),
    "wget": Probe("wget", ("--version",), "core"),
    "tmux": Probe("tmux", ("-V",), "core"),
    "zsh": Probe("zsh", ("--version",), "shell"),
    "make": Probe("make", ("--version",), "build"),
    "gcc": Probe("gcc", ("--version",), "build"),
    "cmake": Probe("cmake", ("--version",), "build"),
    "terraform": Probe("terraform", ("version",), "devops"),
    "kubectl": Probe("kubectl", ("version", "--client", "--output=yaml"), "devops"),
    "ansible": Probe("ansible", ("--version",), "devops"),
    "aws": Probe("aws", ("--version",), "devops"),
    "python": Probe("python3", ("--version",), "runtime"),
    "nodejs": Probe("node", ("--version",), "runtime"),
    "go": Probe("go", ("version",), "runtime"),
    "rust": Probe("rustc", ("--version",), "runtime"),
    "java": Probe("java", ("-version",), "runtime"),
    "bun": Probe("bun", ("--version",), "runtime"),
    "ruby": Probe("ruby", ("--version",), "runtime"),
    "fnm": Probe("fnm", ("--version",), "manager"),
    "pyenv": Probe("pyenv", ("--version",), "manager"),
    "rustup": Probe("rustup", ("--version",), "manager"),
    "uv": Probe("uv", ("--version",), "manager"),
    "pipx": Probe("pipx", ("--version",), "manager"),
    "pnpm": Probe("pnpm", ("--version",), "manager"),
}

FILTERS: dict[str, set[str]] = {
    "frontend": {"git", "nodejs", "code", "nvim", "vim", "pnpm", "bun", "fnm"},
    "backend": {
        "git",
        "python",
        "nodejs",
        "go",
        "rust",
        "java",
        "ruby",
        "docker",
        "podman",
        "uv",
        "pyenv",
    },
    "fullstack": set(PROBES),
    "devops": {"git", "docker", "podman", "terraform", "kubectl", "ansible", "aws", "gh", "zsh"},
}
SDK_FILTERS: dict[str, set[str]] = {
    "frontend": {"android-sdk", "flutter-sdk"},
    "backend": {"java-jdk", "dotnet-sdk"},
    "fullstack": {"android-sdk", "java-jdk", "dotnet-sdk", "flutter-sdk"},
    "devops": set(),
}


def extract_version(output: str) -> str | None:
    match = re.search(r"(?<!\w)v?(\d+(?:\.\d+){0,3}(?:[-+][\w.]+)?)", output)
    return match.group(1) if match else None


def scan_tools() -> list[Tool]:
    found: list[Tool] = []
    for identifier, probe in PROBES.items():
        path = shutil.which(probe.executable)
        if path is None:
            continue
        try:
            result = subprocess.run(
                [path, *probe.arguments], capture_output=True, text=True, timeout=3, check=False
            )
            version = extract_version(result.stdout + "\n" + result.stderr)
        except (OSError, subprocess.TimeoutExpired):
            version = None
        found.append(
            Tool(
                id=identifier,
                version=version,
                executable=probe.executable,
                path=path,
                category=probe.category,
            )
        )
    return found


def scan_environment(profile: str | None = None) -> ScanResult:
    if profile is not None and profile not in FILTERS:
        raise ValueError(f"unknown scan filter: {profile}")
    tools = scan_tools()
    sdks = scan_sdks()
    if profile:
        tools = [tool for tool in tools if tool.id in FILTERS[profile]]
        sdks = [sdk for sdk in sdks if sdk.id in SDK_FILTERS[profile]]
    return ScanResult(system=detect_system(), tools=tools, sdks=sdks)
