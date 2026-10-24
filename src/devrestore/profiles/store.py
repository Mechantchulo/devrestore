"""Local YAML profile storage with restricted names and atomic writes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml
from pydantic import ValidationError

from devrestore.core.models import Manifest, ProfileInfo, SavedSDK, SavedTool, ScanResult


class ProfileError(ValueError):
    """Invalid or conflicting profile operation."""


class ProfileStore:
    MAX_MANIFEST_BYTES = 1024 * 1024

    def __init__(self, root: Path | None = None) -> None:
        self.root = (
            root
            or Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
            / "devrestore/profiles"
        )

    def path(self, name: str) -> Path:
        ProfileInfo(name=name)
        return self.root / f"{name}.yaml"

    def list_names(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(path.stem for path in self.root.glob("*.yaml") if not path.is_symlink())

    @staticmethod
    def parse(data: str) -> Manifest:
        if len(data.encode("utf-8")) > ProfileStore.MAX_MANIFEST_BYTES:
            raise ProfileError("manifest is too large")
        try:
            document = yaml.safe_load(data)
            if not isinstance(document, dict):
                raise ProfileError("manifest must be a YAML mapping")
            return Manifest.model_validate(document)
        except (yaml.YAMLError, ValidationError) as exc:
            raise ProfileError(f"invalid manifest: {exc}") from exc

    def load(self, name: str) -> Manifest:
        path = self.path(name)
        if path.is_symlink():
            raise ProfileError("symlink profiles are not accepted")
        try:
            if path.stat().st_size > self.MAX_MANIFEST_BYTES:
                raise ProfileError("manifest is too large")
            manifest = self.parse(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ProfileError(f"profile {name!r} does not exist") from exc
        if manifest.profile.name != name:
            raise ProfileError("profile name does not match filename")
        return manifest

    def save(self, manifest: Manifest, *, overwrite: bool = False) -> Path:
        path = self.path(manifest.profile.name)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if (path.exists() or path.is_symlink()) and (not overwrite or path.is_symlink()):
            raise ProfileError(f"profile {manifest.profile.name!r} already exists")
        serialized = yaml.safe_dump(
            manifest.model_dump(mode="json", exclude_none=True), sort_keys=False
        )
        fd, temp_name = tempfile.mkstemp(prefix=".devrestore-", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(serialized)
            os.chmod(temp_name, 0o600)
            if overwrite:
                os.replace(temp_name, path)
            else:
                try:
                    os.link(temp_name, path)
                except FileExistsError as exc:
                    raise ProfileError(f"profile {manifest.profile.name!r} already exists") from exc
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return path

    def create(self, name: str, scan: ScanResult, description: str = "") -> Manifest:
        return Manifest(
            profile=ProfileInfo(name=name, description=description),
            source=scan.system,
            tools=[
                SavedTool(id=tool.id, version=tool.version, source_provider=tool.source_provider)
                for tool in scan.tools
            ],
            sdks=[
                SavedSDK(id=sdk.id, version=sdk.version, components=sdk.components)
                for sdk in scan.sdks
            ],
        )

    def import_file(self, source: Path, *, overwrite: bool = False) -> Path:
        if source.is_symlink() or not source.is_file():
            raise ProfileError("import source must be a regular file")
        if source.stat().st_size > self.MAX_MANIFEST_BYTES:
            raise ProfileError("manifest is too large")
        return self.save(self.parse(source.read_text(encoding="utf-8")), overwrite=overwrite)
