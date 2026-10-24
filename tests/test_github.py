import base64
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from devrestore.cli import app
from devrestore.core.models import SavedTool, ScanResult, SystemInfo
from devrestore.profiles.store import ProfileStore
from devrestore.resolver.engine import Action, InstallResult
from devrestore.sync.github import (
    GitHubError,
    GitHubSync,
    create_private_repository,
    gh,
    save_repository,
    saved_repository,
    validate_repository,
)


def test_missing_auth_is_reported_without_credentials() -> None:
    with (
        patch("devrestore.sync.github.shutil.which", return_value="/usr/bin/gh"),
        patch("devrestore.sync.github.subprocess.run") as run,
    ):
        run.return_value.returncode = 1
        run.return_value.stderr = "not logged in"
        with pytest.raises(GitHubError, match="GitHub CLI command failed"):
            gh("auth", "status")


def test_repository_validation() -> None:
    assert validate_repository("owner/devrestore-profiles") == "owner/devrestore-profiles"
    with pytest.raises(GitHubError):
        validate_repository("owner/../other")


def test_repository_creation_is_private() -> None:
    with patch("devrestore.sync.github.gh", side_effect=["owner\n", ""]) as run:
        assert create_private_repository("devrestore-profiles") == "owner/devrestore-profiles"
    assert run.call_args_list[1].args[:4] == (
        "repo",
        "create",
        "devrestore-profiles",
        "--private",
    )


def test_push_reports_conflict_without_writing(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "profiles")
    scan = ScanResult(
        system=SystemInfo(
            distro="ubuntu", version="24.04", family="debian", architecture="x86_64", shell="bash"
        ),
        tools=[],
    )
    store.save(store.create("work", scan))
    service = GitHubSync("owner/private", store)
    remote = base64.b64encode(b"schema_version: 1\nprofile: {name: other}\n").decode()

    def api(*args: str) -> str:
        if args[1] == "repos/owner/private":
            return json.dumps({"private": True, "permissions": {"push": True}})
        return json.dumps({"type": "file", "encoding": "base64", "content": remote, "sha": "abc"})

    with (
        patch("devrestore.sync.github.check_auth"),
        patch("devrestore.sync.github.gh", side_effect=api) as call,
    ):
        assert service.push() == ["work: conflict (remote differs)"]
    assert not any("PUT" in item.args for item in call.call_args_list)


def test_public_repository_is_rejected(tmp_path: Path) -> None:
    service = GitHubSync("owner/repo", ProfileStore(tmp_path))
    with (
        patch("devrestore.sync.github.check_auth"),
        patch("devrestore.sync.github.gh", return_value=json.dumps({"private": False})),
        pytest.raises(GitHubError, match="public repository"),
    ):
        service.check_repository()


def test_connected_repository_is_saved_locally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert saved_repository() is None
    path = save_repository("owner/private")
    assert saved_repository() == "owner/private"
    assert path.stat().st_mode & 0o777 == 0o600


def test_connect_creates_private_repository_after_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    with (
        patch("shutil.which", return_value="/usr/bin/gh"),
        patch("devrestore.sync.github.check_auth", side_effect=[GitHubError("login"), None]),
        patch("devrestore.sync.github.login_interactive") as login,
        patch(
            "devrestore.sync.github.create_private_repository",
            return_value="owner/devrestore-profiles",
        ) as create,
        patch("devrestore.sync.github.GitHubSync.check_repository") as check,
    ):
        result = CliRunner().invoke(app, ["connect"], input="\n\n\n")
    assert result.exit_code == 0, result.output
    assert saved_repository() == "owner/devrestore-profiles"
    login.assert_called_once_with()
    create.assert_called_once_with("devrestore-profiles")
    check.assert_called_once_with(write=True)


def test_connect_does_not_create_repository_without_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    with (
        patch("shutil.which", return_value="/usr/bin/gh"),
        patch("devrestore.sync.github.check_auth"),
        patch("devrestore.sync.github.create_private_repository") as create,
    ):
        result = CliRunner().invoke(app, ["connect"], input="\nn\n")
    assert result.exit_code == 0, result.output
    assert saved_repository() is None
    create.assert_not_called()


def test_connect_can_link_existing_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    with (
        patch("shutil.which", return_value="/usr/bin/gh"),
        patch("devrestore.sync.github.check_auth"),
        patch("devrestore.sync.github.create_private_repository") as create,
        patch("devrestore.sync.github.GitHubSync.check_repository") as check,
    ):
        result = CliRunner().invoke(app, ["connect", "--repository", "owner/private"])
    assert result.exit_code == 0, result.output
    assert saved_repository() == "owner/private"
    create.assert_not_called()
    check.assert_called_once_with(write=True)


def test_sync_uses_connected_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_repository("owner/private")
    with patch("devrestore.sync.github.GitHubSync.push", return_value=["work: uploaded"]) as push:
        result = CliRunner().invoke(app, ["sync"])
    assert result.exit_code == 0, result.output
    assert "work: uploaded" in result.output
    push.assert_called_once_with()


def test_setup_downloads_previews_and_requires_install_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    store = ProfileStore()
    scan = ScanResult(
        system=SystemInfo(
            distro="ubuntu", version="24.04", family="debian", architecture="x86_64", shell="bash"
        ),
        tools=[],
    )
    saved = store.create("work", scan)
    saved.tools = [SavedTool(id="git")]
    store.save(saved)
    action = Action("git", "install", "install git using apt", "apt", "git")

    with (
        patch("shutil.which", return_value="/usr/bin/gh"),
        patch("devrestore.sync.github.check_auth"),
        patch("devrestore.sync.github.GitHubSync.check_repository") as check,
        patch("devrestore.sync.github.GitHubSync.pull", return_value=["work: downloaded"]),
        patch("devrestore.cli.scan_environment", return_value=scan),
        patch("devrestore.resolver.engine.plan_restore", return_value=[action]) as plan,
        patch("devrestore.resolver.engine.execute_plan") as execute,
    ):
        result = CliRunner().invoke(app, ["setup", "--repository", "owner/private"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Restore plan" in result.output
    assert "No packages installed" in result.output
    check.assert_called_once_with()
    plan.assert_called_once_with(saved, distro="ubuntu", installed=[])
    execute.assert_not_called()
    assert saved_repository() == "owner/private"


def test_setup_installs_only_after_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    scan = ScanResult(
        system=SystemInfo(
            distro="ubuntu", version="24.04", family="debian", architecture="x86_64", shell="bash"
        ),
        tools=[],
    )
    ProfileStore().save(ProfileStore().create("work", scan))
    action = Action("git", "install", "install git using apt", "apt", "git")
    with (
        patch("shutil.which", return_value="/usr/bin/gh"),
        patch("devrestore.sync.github.check_auth"),
        patch("devrestore.sync.github.GitHubSync.check_repository"),
        patch("devrestore.sync.github.GitHubSync.pull", return_value=["work: downloaded"]),
        patch("devrestore.cli.scan_environment", return_value=scan),
        patch("devrestore.resolver.engine.plan_restore", return_value=[action]),
        patch(
            "devrestore.resolver.engine.execute_plan",
            return_value=[InstallResult("git", True, "verified")],
        ) as execute,
    ):
        result = CliRunner().invoke(app, ["setup", "--repository", "owner/private"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "git: OK" in result.output
    execute.assert_called_once_with([action])


def test_setup_rejects_conflicted_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    with (
        patch("shutil.which", return_value="/usr/bin/gh"),
        patch("devrestore.sync.github.check_auth"),
        patch("devrestore.sync.github.GitHubSync.check_repository"),
        patch(
            "devrestore.sync.github.GitHubSync.pull",
            return_value=["work: conflict (local differs)"],
        ),
        patch("devrestore.resolver.engine.execute_plan") as execute,
    ):
        result = CliRunner().invoke(
            app, ["setup", "--repository", "owner/private", "--profile", "work"]
        )
    assert result.exit_code == 1
    assert "no usable profiles" in result.output
    execute.assert_not_called()
