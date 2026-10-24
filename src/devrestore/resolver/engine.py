"""Allowlisted cross-distribution package planning and execution."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Literal

from devrestore.core.models import Manifest, Tool
from devrestore.scanner.system import detect_system
from devrestore.scanner.tools import scan_tools

# These are plain distribution packages. Complex products require dedicated adapters.
PACKAGES: dict[str, dict[str, str]] = {
    "git": {"ubuntu": "git", "debian": "git", "fedora": "git"},
    "curl": {"ubuntu": "curl", "debian": "curl", "fedora": "curl"},
    "wget": {"ubuntu": "wget", "debian": "wget", "fedora": "wget"},
    "tmux": {"ubuntu": "tmux", "debian": "tmux", "fedora": "tmux"},
    "make": {"ubuntu": "make", "debian": "make", "fedora": "make"},
    "gcc": {"ubuntu": "gcc", "debian": "gcc", "fedora": "gcc"},
    "cmake": {"ubuntu": "cmake", "debian": "cmake", "fedora": "cmake"},
    "vim": {"ubuntu": "vim", "debian": "vim", "fedora": "vim-enhanced"},
    "zsh": {"ubuntu": "zsh", "debian": "zsh", "fedora": "zsh"},
}


@dataclass(frozen=True)
class Action:
    tool_id: str
    state: Literal["installed", "install", "unsupported", "version_conflict"]
    detail: str
    provider: str | None = None
    package: str | None = None


def plan_restore(
    manifest: Manifest, distro: str | None = None, installed: list[Tool] | None = None
) -> list[Action]:
    target = distro or detect_system().distro
    current = {tool.id: tool for tool in (installed if installed is not None else scan_tools())}
    provider = "apt" if target in {"ubuntu", "debian"} else "dnf" if target == "fedora" else None
    plan: list[Action] = []
    seen: set[str] = set()
    for tool in manifest.tools:
        if tool.id in seen:
            continue
        seen.add(tool.id)
        existing = current.get(tool.id)
        if existing:
            if tool.version_policy == "exact" and tool.version != existing.version:
                plan.append(
                    Action(
                        tool.id,
                        "version_conflict",
                        f"installed {existing.version or 'unknown'}; exact {tool.version} requested",
                    )
                )
            else:
                plan.append(
                    Action(
                        tool.id,
                        "installed",
                        f"already installed ({existing.version or 'unknown version'})",
                    )
                )
            continue
        if tool.version_policy == "exact":
            plan.append(
                Action(
                    tool.id,
                    "version_conflict",
                    f"exact version {tool.version or 'unspecified'} needs a verified provider",
                )
            )
            continue
        package = PACKAGES.get(tool.id, {}).get(target)
        if not package or not provider:
            plan.append(Action(tool.id, "unsupported", f"no verified installer for {target}"))
        else:
            plan.append(
                Action(tool.id, "install", f"install {package} using {provider}", provider, package)
            )
    for sdk in manifest.sdks:
        label = (
            f"{sdk.id} {sdk.version}"
            if sdk.version
            else f"{sdk.id} ({len(sdk.components)} components)"
        )
        plan.append(
            Action(label, "unsupported", "SDK restoration is not implemented; metadata only")
        )
    return plan


@dataclass(frozen=True)
class InstallResult:
    tool_id: str
    success: bool
    message: str


def execute_plan(actions: list[Action]) -> list[InstallResult]:
    """Run only generated package actions; callers must obtain explicit approval."""
    results: list[InstallResult] = []
    for action in actions:
        if action.state != "install" or action.provider not in {"apt", "dnf"} or not action.package:
            continue
        known_packages = {
            PACKAGES.get(action.tool_id, {}).get(distro)
            for distro in (("ubuntu", "debian") if action.provider == "apt" else ("fedora",))
        }
        if action.package not in known_packages:
            results.append(InstallResult(action.tool_id, False, "package is not allowlisted"))
            continue
        manager = "apt-get" if action.provider == "apt" else "dnf"
        executable = shutil.which(manager)
        if not executable:
            results.append(InstallResult(action.tool_id, False, f"{manager} is unavailable"))
            continue
        prefix = [] if os.geteuid() == 0 else [shutil.which("sudo") or "sudo"]
        command = [*prefix, executable, "install", "-y", action.package]
        try:
            result = subprocess.run(command, check=False)
            if result.returncode:
                results.append(
                    InstallResult(
                        action.tool_id, False, f"installer exited with code {result.returncode}"
                    )
                )
            else:
                verified = {tool.id for tool in scan_tools()}
                results.append(
                    InstallResult(
                        action.tool_id,
                        action.tool_id in verified,
                        "verified"
                        if action.tool_id in verified
                        else "installer succeeded but executable was not found",
                    )
                )
        except OSError as exc:
            results.append(InstallResult(action.tool_id, False, str(exc)))
    return results
