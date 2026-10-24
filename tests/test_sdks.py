from pathlib import Path
from unittest.mock import patch

from devrestore.core.models import SavedSDK, ScanResult, SDKComponent, SDKInstallation, SystemInfo
from devrestore.profiles.store import ProfileStore
from devrestore.resolver.engine import plan_restore
from devrestore.scanner.sdks import (
    parse_dotnet_sdks,
    scan_android_root,
    scan_dotnet,
    scan_flutter,
    scan_jdks,
    sdk_status,
)
from devrestore.scanner.tools import scan_environment


def test_android_components_are_read_from_known_directories(tmp_path: Path) -> None:
    root = tmp_path / "Android" / "Sdk"
    platform = root / "platforms" / "android-35"
    platform.mkdir(parents=True)
    (platform / "source.properties").write_text("Pkg.Revision=2\n")
    build_tools = root / "build-tools" / "35.0.0"
    build_tools.mkdir(parents=True)
    (build_tools / "source.properties").write_text("Pkg.Revision=35.0.0\n")
    (root / "platform-tools").mkdir()
    result = scan_android_root(root)
    assert result is not None
    assert result.id == "android-sdk"
    assert [(part.id, part.version) for part in result.components] == [
        ("platform-tools", None),
        ("build-tools/35.0.0", "35.0.0"),
        ("platforms/android-35", "2"),
    ]


def test_multiple_jdks_and_jre_exclusion(tmp_path: Path) -> None:
    root = tmp_path / "jvm"
    for name, version in (("jdk-17", "17.0.11"), ("jdk-21", "21.0.3")):
        install = root / name
        (install / "bin").mkdir(parents=True)
        (install / "bin/javac").write_text("")
        (install / "release").write_text(f'JAVA_VERSION="{version}"\n')
    jre = root / "jre-17"
    jre.mkdir()
    (jre / "release").write_text('JAVA_VERSION="17"\n')
    found = scan_jdks(env={"JAVA_HOME": str(root / "jdk-17")}, home=tmp_path, system_root=root)
    assert [item.version for item in found] == ["17.0.11", "21.0.3"]


def test_dotnet_sdks_use_trusted_list_command() -> None:
    output = "8.0.408 [/usr/share/dotnet/sdk]\n9.0.100 [/usr/share/dotnet/sdk]\nnoise\n"
    assert [item.version for item in parse_dotnet_sdks(output)] == ["8.0.408", "9.0.100"]
    with (
        patch("devrestore.scanner.sdks.shutil.which", return_value="/usr/bin/dotnet"),
        patch("devrestore.scanner.sdks.subprocess.run") as run,
    ):
        run.return_value.returncode = 0
        run.return_value.stdout = output
        found = scan_dotnet()
    assert len(found) == 2
    assert run.call_args.args[0] == ["/usr/bin/dotnet", "--list-sdks"]


def test_flutter_uses_local_metadata_without_running_flutter(tmp_path: Path) -> None:
    root = tmp_path / "flutter"
    (root / "bin").mkdir(parents=True)
    (root / "bin/flutter").write_text("")
    (root / "version").write_text("3.24.5\n")
    with patch("devrestore.scanner.sdks.shutil.which", return_value=str(root / "bin/flutter")):
        found = scan_flutter()
    assert [(item.id, item.version) for item in found] == [("flutter-sdk", "3.24.5")]


def test_sdk_filter_profile_roundtrip_and_restore_notice(tmp_path: Path) -> None:
    sdk = SDKInstallation(id="java-jdk", version="21.0.3", path="/opt/jdk-21")
    with (
        patch("devrestore.scanner.tools.scan_tools", return_value=[]),
        patch("devrestore.scanner.tools.scan_sdks", return_value=[sdk]),
    ):
        result = scan_environment("backend")
        frontend = scan_environment("frontend")
    assert [item.id for item in result.sdks] == ["java-jdk"]
    assert frontend.sdks == []
    store = ProfileStore(tmp_path / "profiles")
    saved = store.create("with-sdk", result)
    store.save(saved)
    loaded = store.load("with-sdk")
    assert loaded.sdks[0].version == "21.0.3"
    actions = plan_restore(loaded, "fedora", installed=[])
    assert [(item.state, item.tool_id) for item in actions] == [("unsupported", "java-jdk 21.0.3")]


def test_status_matches_correct_android_installation() -> None:
    saved = SavedSDK(
        id="android-sdk",
        components=[SDKComponent(id="platforms/android-36", version="2")],
    )
    installations = [
        SDKInstallation(id="android-sdk", path="/sdk/old", components=[]),
        SDKInstallation(id="android-sdk", path="/sdk/new", components=saved.components),
    ]
    assert sdk_status(saved, installations) == "present"


def test_old_profile_without_sdk_field_still_loads(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    manifest = store.create(
        "legacy",
        ScanResult(
            system=SystemInfo(
                distro="ubuntu",
                version="24.04",
                family="debian",
                architecture="x86_64",
                shell="bash",
            ),
            tools=[],
        ),
    )
    data = manifest.model_dump(mode="json")
    data.pop("sdks")
    import yaml

    assert store.parse(yaml.safe_dump(data)).sdks == []
