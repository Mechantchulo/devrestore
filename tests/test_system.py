from pathlib import Path

from devrestore.scanner.system import detect_system, parse_os_release


def test_ubuntu_detection(tmp_path: Path) -> None:
    release = tmp_path / "os-release"
    release.write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
    system = detect_system(release)
    assert (system.distro, system.version, system.family) == ("ubuntu", "24.04", "debian")


def test_fedora_detection(tmp_path: Path) -> None:
    release = tmp_path / "os-release"
    release.write_text("ID=fedora\nVERSION_ID=42\n")
    assert detect_system(release).family == "fedora"


def test_missing_and_unknown_fields(tmp_path: Path) -> None:
    release = tmp_path / "missing"
    assert detect_system(release).distro == "unknown"
    release.write_text("ID=custom\n")
    assert detect_system(release).family == "unknown"
    assert parse_os_release("# comment\nBROKEN\nID=debian") == {"ID": "debian"}
