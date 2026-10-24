"""Optional private GitHub repository sync via an existing GitHub CLI login."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from devrestore.profiles.store import ProfileError, ProfileStore


class GitHubError(RuntimeError):
    """GitHub CLI or repository operation failed."""

    def __init__(self, message: str, *, not_found: bool = False) -> None:
        super().__init__(message)
        self.not_found = not_found


def gh(*args: str) -> str:
    executable = shutil.which("gh")
    if not executable:
        raise GitHubError("GitHub CLI is missing; install gh or keep using local profiles")
    try:
        result = subprocess.run(
            [executable, *args], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitHubError(f"GitHub CLI failed: {exc}") from exc
    if result.returncode:
        # gh output can include sensitive server data; do not echo it.
        raise GitHubError(
            f"GitHub CLI command failed (exit {result.returncode}); check gh auth status and repository access",
            not_found="HTTP 404" in result.stderr or "Not Found (HTTP 404)" in result.stderr,
        )
    return result.stdout


def check_auth() -> None:
    gh("auth", "status", "--hostname", "github.com")


def login_interactive() -> None:
    """Let gh own its interactive device flow and credential storage."""
    executable = shutil.which("gh")
    if not executable:
        raise GitHubError("GitHub CLI is missing; install gh or keep using local profiles")
    try:
        result = subprocess.run([executable, "auth", "login"], check=False)
    except OSError as exc:
        raise GitHubError(f"GitHub CLI failed: {exc}") from exc
    if result.returncode:
        raise GitHubError(f"GitHub CLI login failed (exit {result.returncode})")


def validate_repository(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}", value):
        raise GitHubError("repository must be OWNER/NAME")
    if value.split("/", 1)[1] in {".", ".."}:
        raise GitHubError("repository must be OWNER/NAME")
    return value


def connection_path() -> Path:
    """The selected repository is local configuration, never an auth token."""
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "devrestore/github.json"
    )


def saved_repository() -> str | None:
    path = connection_path()
    if path.is_symlink():
        raise GitHubError("GitHub connection file must not be a symlink")
    try:
        if path.stat().st_size > 4096:
            raise GitHubError("GitHub connection file is too large")
        data = json.loads(path.read_text(encoding="utf-8"))
        return validate_repository(data["repository"])
    except FileNotFoundError:
        return None
    except (ValueError, KeyError, TypeError) as exc:
        raise GitHubError(
            "GitHub connection file is invalid; run devrestore connect again"
        ) from exc


def save_repository(repository: str) -> Path:
    repository = validate_repository(repository)
    path = connection_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise GitHubError("GitHub connection file must not be a symlink")
    fd, temp_name = tempfile.mkstemp(prefix=".devrestore-github-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"repository": repository}, stream)
            stream.write("\n")
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return path


def create_private_repository(name: str) -> str:
    owner = gh("api", "user", "--jq", ".login").strip()
    repository = validate_repository(f"{owner}/{name}")
    gh("repo", "create", name, "--private", "--description", "DevRestore environment profiles")
    return repository


@dataclass(frozen=True)
class RemoteFile:
    content: bytes
    sha: str


class GitHubSync:
    def __init__(self, repository: str, store: ProfileStore | None = None) -> None:
        self.repository = validate_repository(repository)
        self.store = store or ProfileStore()

    def check_repository(self, *, write: bool = False) -> None:
        check_auth()
        data = json.loads(gh("api", f"repos/{self.repository}"))
        if not data.get("private"):
            raise GitHubError(
                "refusing to sync profiles to a public repository; choose a private repository"
            )
        if write and not data.get("permissions", {}).get("push", False):
            raise GitHubError("the authenticated account needs write access to this repository")

    def remote_file(self, name: str) -> RemoteFile | None:
        self.store.path(name)
        try:
            data = json.loads(gh("api", f"repos/{self.repository}/contents/profiles/{name}.yaml"))
        except GitHubError as exc:
            if exc.not_found:
                return None
            raise
        if data.get("type") != "file" or data.get("encoding") != "base64":
            raise GitHubError(f"remote profile {name!r} has an unsupported format")
        try:
            content = base64.b64decode(data["content"].replace("\n", ""), validate=True)
        except (KeyError, ValueError) as exc:
            raise GitHubError(f"remote profile {name!r} has invalid content") from exc
        if len(content) > 1024 * 1024:
            raise GitHubError(f"remote profile {name!r} is too large")
        if not isinstance(data.get("sha"), str):
            raise GitHubError(f"remote profile {name!r} has no revision identifier")
        return RemoteFile(content, data["sha"])

    def list_remote(self) -> list[str]:
        try:
            data = json.loads(gh("api", f"repos/{self.repository}/contents/profiles"))
        except GitHubError as exc:
            if exc.not_found:
                return []
            raise
        if not isinstance(data, list):
            raise GitHubError("remote profiles path is not a directory")
        names: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            filename = item.get("name", "")
            if item.get("type") == "file" and filename.endswith(".yaml"):
                name = filename[:-5]
                try:
                    self.store.path(name)
                except ValueError:
                    continue
                names.append(name)
        return sorted(names)

    def push(self) -> list[str]:
        self.check_repository(write=True)
        results: list[str] = []
        for name in self.store.list_names():
            local = self.store.path(name).read_bytes()
            if len(local) > self.store.MAX_MANIFEST_BYTES:
                raise GitHubError(f"local profile {name!r} is too large")
            self.store.load(name)  # validate local data before sending
            remote = self.remote_file(name)
            if remote:
                try:
                    same = self.store.parse(remote.content.decode("utf-8")) == self.store.parse(
                        local.decode("utf-8")
                    )
                except (UnicodeDecodeError, ProfileError):
                    same = False
                results.append(
                    f"{name}: unchanged" if same else f"{name}: conflict (remote differs)"
                )
                continue
            encoded = base64.b64encode(local).decode("ascii")
            gh(
                "api",
                f"repos/{self.repository}/contents/profiles/{name}.yaml",
                "--method",
                "PUT",
                "-f",
                f"message=Add DevRestore profile {name}",
                "-f",
                f"content={encoded}",
            )
            results.append(f"{name}: uploaded")
        return results

    def pull(self) -> list[str]:
        self.check_repository()
        results: list[str] = []
        for name in self.list_remote():
            remote = self.remote_file(name)
            if remote is None:
                raise GitHubError(f"remote profile {name!r} vanished during sync")
            try:
                document = remote.content.decode("utf-8")
                manifest = self.store.parse(document)
            except (UnicodeDecodeError, ProfileError) as exc:
                raise GitHubError(f"remote profile {name!r} is invalid: {exc}") from exc
            if manifest.profile.name != name:
                raise GitHubError(f"remote profile {name!r} has a mismatched name")
            local_path = self.store.path(name)
            if local_path.exists() or local_path.is_symlink():
                try:
                    same = self.store.parse(local_path.read_text(encoding="utf-8")) == manifest
                except (UnicodeDecodeError, ProfileError):
                    same = False
                results.append(
                    f"{name}: unchanged" if same else f"{name}: conflict (local differs)"
                )
                continue
            self.store.save(manifest)
            results.append(f"{name}: downloaded")
        return results
