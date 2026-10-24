from pathlib import Path

import pytest
from pydantic import ValidationError

from devrestore.core.models import ScanResult, SystemInfo, Tool
from devrestore.profiles.store import ProfileError, ProfileStore


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(tmp_path / "profiles")


@pytest.fixture
def scan() -> ScanResult:
    return ScanResult(
        system=SystemInfo(
            distro="ubuntu",
            version="24.04",
            family="debian",
            architecture="x86_64",
            shell="/bin/bash",
        ),
        tools=[
            Tool(id="git", version="2.43", executable="git", path="/usr/bin/git", category="core")
        ],
    )


def test_save_load_and_conflict(store: ProfileStore, scan: ScanResult) -> None:
    manifest = store.create("workstation", scan)
    path = store.save(manifest)
    assert path.stat().st_mode & 0o777 == 0o600
    assert store.load("workstation") == manifest
    assert store.list_names() == ["workstation"]
    with pytest.raises(ProfileError, match="already exists"):
        store.save(manifest)


def test_traversal_and_invalid_manifest(store: ProfileStore, scan: ScanResult) -> None:
    with pytest.raises(ValidationError):
        store.create("../escape", scan)
    with pytest.raises(ProfileError):
        store.parse("!!python/object/apply:os.system ['echo bad']")
    with pytest.raises(ProfileError):
        store.parse("schema_version: 999\nprofile: {name: test}\nsource: {}\ntools: []")
    with pytest.raises(ProfileError):
        store.parse("- this is not a mapping")


def test_import_rejects_symlink(store: ProfileStore, scan: ScanResult, tmp_path: Path) -> None:
    source = tmp_path / "profile.yaml"
    source.write_text("schema_version: 1")
    link = tmp_path / "link.yaml"
    link.symlink_to(source)
    with pytest.raises(ProfileError, match="regular file"):
        store.import_file(link)
