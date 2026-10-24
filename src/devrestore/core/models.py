"""Validated data exchanged between scanners, storage and interfaces."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SystemInfo(BaseModel):
    distro: str
    version: str
    family: str
    architecture: str
    shell: str
    package_managers: list[str] = Field(default_factory=list)
    version_managers: list[str] = Field(default_factory=list)


class Tool(BaseModel):
    id: str
    version: str | None = None
    executable: str
    path: str
    category: str
    source_provider: str | None = None


class SDKComponent(BaseModel):
    id: str
    version: str | None = None


class SDKInstallation(BaseModel):
    id: str
    version: str | None = None
    path: str
    components: list[SDKComponent] = Field(default_factory=list)


class ScanResult(BaseModel):
    system: SystemInfo
    tools: list[Tool]
    sdks: list[SDKInstallation] = Field(default_factory=list)


class ProfileInfo(BaseModel):
    name: str
    description: str = ""

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        import re

        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", value) or value in {".", ".."}:
            raise ValueError("profile name must use letters, digits, dots, underscores or hyphens")
        return value


class SavedTool(BaseModel):
    id: str
    version: str | None = None
    version_policy: Literal["preference", "exact"] = "preference"
    source_provider: str | None = None

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        import re

        if not re.fullmatch(r"[a-z][a-z0-9-]*", value):
            raise ValueError("invalid tool identifier")
        return value


class SavedSDK(BaseModel):
    id: Literal["android-sdk", "java-jdk", "dotnet-sdk", "flutter-sdk"]
    version: str | None = None
    components: list[SDKComponent] = Field(default_factory=list)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    profile: ProfileInfo
    source: SystemInfo
    tools: list[SavedTool]
    sdks: list[SavedSDK] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
