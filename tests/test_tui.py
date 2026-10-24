import asyncio
from unittest.mock import patch

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Button, Input, Static

from devrestore.core.models import ScanResult, SDKInstallation, SystemInfo, Tool
from devrestore.profiles.store import ProfileStore
from devrestore.tui.app import DetailScreen, DevRestoreApp, HomeScreen


def test_tui_starts() -> None:
    async def check() -> None:
        async with DevRestoreApp().run_test() as pilot:
            await pilot.pause()
            assert isinstance(pilot.app.screen, HomeScreen)
            await pilot.press("end", "enter")
            await pilot.pause()
            assert isinstance(pilot.app.screen, DetailScreen)

    asyncio.run(check())


def test_number_shortcut_opens_section() -> None:
    async def check() -> None:
        async with DevRestoreApp().run_test() as pilot:
            await pilot.press("6")
            await pilot.pause()
            assert isinstance(pilot.app.screen, DetailScreen)
            assert pilot.app.screen.title_text == "System Status"

    asyncio.run(check())


def test_scan_screen() -> None:
    async def check() -> None:
        result = ScanResult(
            system=SystemInfo(
                distro="ubuntu",
                version="24.04",
                family="debian",
                architecture="x86_64",
                shell="bash",
            ),
            tools=[
                Tool(
                    id=f"tool-{index}",
                    version="1.0",
                    executable=f"tool-{index}",
                    path=f"/usr/bin/tool-{index}",
                    category="core",
                )
                for index in range(22)
            ],
            sdks=[SDKInstallation(id="java-jdk", version="21", path="/opt/jdk-21")],
        )
        with patch("devrestore.tui.app.scan_environment", return_value=result):
            async with DevRestoreApp().run_test(size=(80, 24)) as pilot:
                pilot.app.push_screen(DetailScreen("Scan Environment"))
                await asyncio.sleep(0.25)
                await pilot.pause()
                assert isinstance(pilot.app.screen, DetailScreen)
                content = str(pilot.app.screen.query_one("#details", Static).render())
                scroll = pilot.app.screen.query_one("#detail-scroll", VerticalScroll)
                assert "ubuntu 24.04" in content
                assert content.index("java-jdk") < content.index("tool-0")
                assert scroll.max_scroll_y > 0
                assert scroll.has_focus

    asyncio.run(check())


def test_github_buttons_start_guided_commands() -> None:
    async def check() -> None:
        with patch.object(DetailScreen, "run_github_command") as run:
            async with DevRestoreApp().run_test(size=(80, 24)) as pilot:
                pilot.app.push_screen(DetailScreen("GitHub Sync"))
                await pilot.pause()
                await pilot.click("#github-connect")
                await pilot.pause()
                run.assert_called_once_with(("connect",))

    asyncio.run(check())


def test_scan_screen_saves_profile(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    async def check() -> None:
        result = ScanResult(
            system=SystemInfo(
                distro="ubuntu",
                version="24.04",
                family="debian",
                architecture="x86_64",
                shell="bash",
            ),
            tools=[],
        )
        with patch("devrestore.tui.app.scan_environment", return_value=result):
            async with DevRestoreApp().run_test(size=(80, 24)) as pilot:
                pilot.app.push_screen(DetailScreen("Scan Environment"))
                await asyncio.sleep(0.25)
                await pilot.pause()
                assert not pilot.app.screen.query_one("#save-profile", Button).disabled
                pilot.app.screen.query_one("#profile-name", Input).value = "work"
                await pilot.click("#save-profile")
                await pilot.pause()
                assert ProfileStore().load("work").profile.name == "work"
                assert "Saved work" in str(
                    pilot.app.screen.query_one("#save-feedback", Static).render()
                )

    asyncio.run(check())


def test_setup_menu_starts_guided_command() -> None:
    async def check() -> None:
        with patch.object(DetailScreen, "run_github_command") as run:
            async with DevRestoreApp().run_test(size=(80, 24)) as pilot:
                await pilot.press("7")
                await pilot.pause()
                assert isinstance(pilot.app.screen, DetailScreen)
                assert pilot.app.screen.title_text == "Set Up This Computer"
                await pilot.click("#start-setup")
                await pilot.pause()
                run.assert_called_once_with(("setup",))

    asyncio.run(check())
