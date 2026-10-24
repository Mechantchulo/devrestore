"""Read-only discovery of SDK installations and their local metadata."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from devrestore.core.models import SavedSDK, SDKComponent, SDKInstallation

MAX_METADATA_BYTES = 64 * 1024
ANDROID_GROUPS = ("build-tools", "platforms", "cmdline-tools", "ndk")


def _read_small_file(path: Path) -> str | None:
    try:
        if path.is_symlink() or path.stat().st_size > MAX_METADATA_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _properties(path: Path) -> dict[str, str]:
    content = _read_small_file(path)
    if content is None:
        return {}
    result: dict[str, str] = {}
    for line in content.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip('"')
    return result


def _children(path: Path) -> list[Path]:
    try:
        return sorted(
            (child for child in path.iterdir() if child.is_dir()), key=lambda item: item.name
        )[:100]
    except OSError:
        return []


def scan_android_root(root: Path) -> SDKInstallation | None:
    if not root.is_dir():
        return None
    components: list[SDKComponent] = []
    for name in ("platform-tools", "emulator"):
        location = root / name
        if location.is_dir():
            revision = _properties(location / "source.properties").get("Pkg.Revision")
            components.append(SDKComponent(id=name, version=revision))
    for group in ANDROID_GROUPS:
        for location in _children(root / group):
            revision = _properties(location / "source.properties").get("Pkg.Revision")
            components.append(SDKComponent(id=f"{group}/{location.name}", version=revision))
    if not components:
        return None
    return SDKInstallation(id="android-sdk", path=str(root.resolve()), components=components)


def scan_android(
    env: Mapping[str, str] | None = None, home: Path | None = None
) -> list[SDKInstallation]:
    values = env if env is not None else os.environ
    user_home = home or Path.home()
    candidates = [
        values.get("ANDROID_HOME"),
        values.get("ANDROID_SDK_ROOT"),
        str(user_home / "Android/Sdk"),
        "/opt/android-sdk",
        "/usr/lib/android-sdk",
    ]
    found: list[SDKInstallation] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if not candidate:
            continue
        root = Path(candidate).expanduser().resolve()
        if root in seen:
            continue
        seen.add(root)
        sdk = scan_android_root(root)
        if sdk:
            found.append(sdk)
    return found


def scan_jdk_root(root: Path) -> SDKInstallation | None:
    if not (root / "bin/javac").is_file():
        return None
    version = _properties(root / "release").get("JAVA_VERSION")
    return SDKInstallation(id="java-jdk", version=version, path=str(root.resolve()))


def scan_jdks(
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    system_root: Path = Path("/usr/lib/jvm"),
) -> list[SDKInstallation]:
    values = env if env is not None else os.environ
    user_home = home or Path.home()
    candidates = [Path(values["JAVA_HOME"])] if values.get("JAVA_HOME") else []
    for parent in (system_root, user_home / ".sdkman/candidates/java", user_home / ".jdks"):
        candidates.extend(_children(parent))
    found: list[SDKInstallation] = []
    seen: set[Path] = set()
    for candidate in candidates:
        root = candidate.expanduser().resolve()
        if root in seen:
            continue
        seen.add(root)
        sdk = scan_jdk_root(root)
        if sdk:
            found.append(sdk)
    return found


def parse_dotnet_sdks(output: str) -> list[SDKInstallation]:
    results: list[SDKInstallation] = []
    for line in output.splitlines():
        match = re.fullmatch(r"\s*([0-9][\w.+-]*)\s+\[([^\]\n]+)\]\s*", line)
        if match:
            version, base = match.groups()
            results.append(
                SDKInstallation(id="dotnet-sdk", version=version, path=str(Path(base) / version))
            )
    return results


def scan_dotnet() -> list[SDKInstallation]:
    executable = shutil.which("dotnet")
    if not executable:
        return []
    try:
        result = subprocess.run(
            [executable, "--list-sdks"], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_dotnet_sdks(result.stdout) if result.returncode == 0 else []


def scan_flutter() -> list[SDKInstallation]:
    executable = shutil.which("flutter")
    if not executable:
        return []
    root = Path(executable).resolve().parent.parent
    if not (root / "bin/flutter").is_file():
        return []
    version = (_read_small_file(root / "version") or "").strip() or None
    if version is None:
        metadata = _read_small_file(root / "bin/cache/flutter.version.json")
        if metadata:
            try:
                version = json.loads(metadata).get("frameworkVersion")
            except (json.JSONDecodeError, AttributeError):
                version = None
    return [SDKInstallation(id="flutter-sdk", version=version, path=str(root))]


def scan_sdks() -> list[SDKInstallation]:
    return [*scan_android(), *scan_jdks(), *scan_dotnet(), *scan_flutter()]


def sdk_status(saved: SavedSDK, installed: list[SDKInstallation]) -> str:
    candidates = [item for item in installed if item.id == saved.id]
    if not candidates:
        return "missing"
    same_version = [
        item for item in candidates if saved.version is None or item.version == saved.version
    ]
    if not same_version:
        return "version differs"
    wanted = {(part.id, part.version) for part in saved.components}
    if any(
        wanted <= {(part.id, part.version) for part in item.components} for item in same_version
    ):
        return "present"
    return "components differ"
