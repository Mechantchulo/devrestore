from unittest.mock import patch

from devrestore.core.models import Tool
from devrestore.scanner.tools import extract_version, scan_environment, scan_tools


def test_version_extraction() -> None:
    assert extract_version("git version 2.43.0\n") == "2.43.0"
    assert extract_version("nothing useful") is None


def test_only_discovered_allowlisted_executables_are_run() -> None:
    with (
        patch(
            "devrestore.scanner.tools.shutil.which",
            side_effect=lambda name: "/usr/bin/git" if name == "git" else None,
        ),
        patch("devrestore.scanner.tools.subprocess.run") as run,
    ):
        run.return_value.stdout = "git version 2.43.0"
        run.return_value.stderr = ""
        tools = scan_tools()
    assert [tool.id for tool in tools] == ["git"]
    run.assert_called_once()
    assert run.call_args.args[0] == ["/usr/bin/git", "--version"]


def test_filter_only_keeps_detected_tools() -> None:
    available = [
        Tool(id="git", executable="git", path="/bin/git", category="core"),
        Tool(id="docker", executable="docker", path="/bin/docker", category="devops"),
    ]
    with patch("devrestore.scanner.tools.scan_tools", return_value=available):
        result = scan_environment("frontend")
    assert [tool.id for tool in result.tools] == ["git"]
