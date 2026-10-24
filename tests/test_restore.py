from unittest.mock import patch

from devrestore.core.models import Manifest, ProfileInfo, SavedTool, SystemInfo, Tool
from devrestore.resolver.engine import Action, execute_plan, plan_restore


def manifest(*tools: SavedTool) -> Manifest:
    return Manifest(
        profile=ProfileInfo(name="work"),
        source=SystemInfo(
            distro="ubuntu", version="24.04", family="debian", architecture="x86_64", shell="bash"
        ),
        tools=list(tools),
    )


def test_cross_distro_mapping_and_duplicates() -> None:
    profile = manifest(SavedTool(id="vim"), SavedTool(id="vim"), SavedTool(id="docker"))
    actions = plan_restore(profile, "fedora", [])
    assert [(a.tool_id, a.state, a.package) for a in actions] == [
        ("vim", "install", "vim-enhanced"),
        ("docker", "unsupported", None),
    ]


def test_installed_and_exact_version_conflict() -> None:
    profile = manifest(SavedTool(id="git", version="2.43", version_policy="exact"))
    installed = [Tool(id="git", version="2.42", executable="git", path="/bin/git", category="core")]
    assert plan_restore(profile, "ubuntu", installed)[0].state == "version_conflict"
    assert plan_restore(manifest(SavedTool(id="git")), "ubuntu", installed)[0].state == "installed"


def test_install_failure_is_reported_without_running_another_command() -> None:
    with (
        patch("devrestore.resolver.engine.shutil.which", return_value="/usr/bin/apt-get"),
        patch("devrestore.resolver.engine.os.geteuid", return_value=0),
        patch("devrestore.resolver.engine.subprocess.run") as run,
    ):
        run.return_value.returncode = 1
        results = execute_plan([Action("git", "install", "install git", "apt", "git")])
    assert results[0].success is False
    run.assert_called_once_with(["/usr/bin/apt-get", "install", "-y", "git"], check=False)
