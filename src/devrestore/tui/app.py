"""Responsive Textual shell over the same scanner and profile services as the CLI."""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from typing import ClassVar

from textual.app import App, ComposeResult, SuspendNotSupported
from textual.containers import Container, Horizontal, VerticalScroll
from textual.events import Key
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Button, Footer, Header, Input, Label, OptionList, Static

from devrestore.core.models import ScanResult
from devrestore.profiles.store import ProfileStore
from devrestore.scanner.system import detect_system
from devrestore.scanner.tools import scan_environment

SECTIONS = (
    "Scan Environment",
    "My Profiles",
    "Restore Environment",
    "GitHub Sync",
    "Export / Import",
    "System Status",
    "Set Up This Computer",
)

LOGO = r""" ___  _____   _____ ___ ___ _____ ___  ___ ___
|   \| __\ \ / / _ \ __/ __|_   _/ _ \| _ \ __|
| |) | _| \ V /|   / _|\__ \ | || (_) |   / _|
|___/|___| \_/ |_|_\___|___/ |_| \___/|_|_\___|"""


class HomeScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="main"):
            yield Static("DEVRESTORE  /  LINUX ENVIRONMENT MANAGER", id="eyebrow")
            yield Static(LOGO, id="brand")
            yield Label("SCAN ONCE  ·  SAVE YOUR SETUP  ·  RESTORE WITH CONFIDENCE", id="tagline")
            yield Static("", id="summary")
            yield Static("CHOOSE A WORKFLOW", id="menu-label")
            yield OptionList(
                "1   Scan environment    Discover installed tools",
                "2   My profiles         Browse saved setups",
                "3   Restore             Preview an install plan",
                "4   GitHub sync         Upload or download profiles",
                "5   Export / import     Move YAML profiles",
                "6   System status       Check support",
                "7   Set up this computer  Restore from GitHub",
                id="menu",
            )
            yield Static("↑ ↓ MOVE     ENTER SELECT     1–7 SHORTCUTS     Q QUIT", id="hint")
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.open_section(event.option_index)

    def on_key(self, event: Key) -> None:
        if event.key in "1234567" and len(event.key) == 1:
            self.open_section(int(event.key) - 1)
            event.stop()

    def open_section(self, index: int) -> None:
        self.app.push_screen(DetailScreen(SECTIONS[index]))

    def on_mount(self) -> None:
        self.refresh_summary()
        self.query_one("#menu", OptionList).focus()

    def on_screen_resume(self) -> None:
        self.refresh_summary()

    def refresh_summary(self) -> None:
        system = detect_system()
        count = len(ProfileStore().list_names())
        support = (
            "Restore ready"
            if system.distro in {"ubuntu", "debian", "fedora"}
            else "Restore unsupported"
        )
        self.query_one("#summary", Static).update(
            f"{system.distro.upper()} {system.version}  ·  {count} profile{'s' if count != 1 else ''}  ·  {support}"
        )


class DetailScreen(Screen):
    BINDINGS: ClassVar = [("escape", "app.pop_screen", "Back")]

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title_text = title
        self._scan_pool: ThreadPoolExecutor | None = None
        self._scan_future: Future | None = None
        self._scan_timer: Timer | None = None
        self._scan_result: ScanResult | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="detail-main"):
            yield Label(self.title_text, classes="heading")
            with VerticalScroll(id="detail-scroll"):
                yield Static("Loading…", id="details")
            with Horizontal(id="detail-actions"):
                if self.title_text == "Scan Environment":
                    yield Input(placeholder="Profile name (e.g. work)", id="profile-name")
                    yield Button(
                        "Save profile", id="save-profile", variant="primary", disabled=True
                    )
                if self.title_text == "GitHub Sync":
                    yield Button("Connect", id="github-connect", variant="primary")
                    yield Button("Back up", id="github-push")
                    yield Button("Download", id="github-pull")
                if self.title_text == "Set Up This Computer":
                    yield Button("Start setup", id="start-setup", variant="primary")
                yield Button("Back", id="back")
            if self.title_text == "Scan Environment":
                yield Static("", id="save-feedback")
        yield Footer()

    def on_mount(self) -> None:
        if self.title_text == "Scan Environment":
            self._scan_pool = ThreadPoolExecutor(max_workers=1)
            self._scan_future = self._scan_pool.submit(scan_environment)
            self._scan_timer = self.set_interval(0.1, self.poll_scan)
        elif self.title_text == "My Profiles":
            self.load_profiles()
        elif self.title_text == "Restore Environment":
            names = ProfileStore().list_names()
            content = (
                "Saved profiles:\n" + "\n".join(f"  {name}" for name in names) + "\n\n"
                if names
                else "No profiles saved yet. Scan and save one first.\n\n"
            )
            content += "Preview safely: devrestore restore --profile NAME --dry-run"
            self.query_one("#details", Static).update(content)
        elif self.title_text == "GitHub Sync":
            self.show_github_status()
        elif self.title_text == "Set Up This Computer":
            self.show_setup_status()
        elif self.title_text == "Export / Import":
            self.query_one("#details", Static).update(
                "Export: devrestore export NAME --output profile.yaml\n"
                "Import: devrestore import profile.yaml\n\n"
                "Existing files are not replaced automatically."
            )
        elif self.title_text == "System Status":
            system = detect_system()
            self.query_one("#details", Static).update(
                f"Distribution: {system.distro} {system.version}\n"
                f"Architecture: {system.architecture}\n"
                f"Shell: {system.shell}\n"
                f"Package managers: {', '.join(system.package_managers) or 'none'}\n"
                f"Version managers: {', '.join(system.version_managers) or 'none'}\n\n"
                "Run devrestore doctor for a full compatibility check."
            )
        else:
            self.query_one("#details", Static).update(
                "Run devrestore --help for available commands."
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "save-profile":
            self.save_profile()
        elif event.button.id == "start-setup":
            self.run_github_command(("setup",))
        elif event.button.id in {"github-connect", "github-push", "github-pull"}:
            commands = {
                "github-connect": ("connect",),
                "github-push": ("sync",),
                "github-pull": ("sync", "--direction", "pull"),
            }
            self.run_github_command(commands[event.button.id])

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "profile-name":
            self.save_profile()

    def save_profile(self) -> None:
        if self._scan_result is None:
            return
        name = self.query_one("#profile-name", Input).value.strip()
        feedback = self.query_one("#save-feedback", Static)
        if not name:
            feedback.update("Enter a profile name before saving.")
            self.query_one("#profile-name", Input).focus()
            return
        try:
            store = ProfileStore()
            path = store.save(store.create(name, self._scan_result))
        except (OSError, ValueError) as exc:
            feedback.update(f"Could not save profile: {exc}")
            return
        feedback.update(f"Saved {name} to {path}. Next: GitHub Sync → Connect, then Back up.")
        self.query_one("#save-profile", Button).disabled = True

    def show_setup_status(self, message: str = "") -> None:
        from devrestore.sync.github import GitHubError, saved_repository

        try:
            repository = saved_repository()
        except (GitHubError, OSError):
            repository = None
        content = (
            f"Connected repository: {repository}\n\n"
            if repository
            else "No repository connected yet. Setup will ask for its OWNER/NAME.\n\n"
        )
        content += (
            "Start setup to sign in, download profiles, choose one, and review the restore plan.\n"
            "Supported packages are installed only after you confirm."
        )
        if message:
            content += f"\n\n{message}"
        self.query_one("#details", Static).update(content)

    def show_github_status(self, message: str = "") -> None:
        from devrestore.sync.github import GitHubError, saved_repository

        try:
            repository = saved_repository()
        except (GitHubError, OSError):
            repository = None
        connection = (
            f"Connected repository: {repository}" if repository else "No repository connected yet."
        )
        content = (
            f"{connection}\n\n"
            "Connect: sign in and create a private repository.\n"
            "Back up: upload your saved profiles.\n"
            "Download: retrieve profiles on this computer.\n\n"
            "Profile conflicts are shown and never overwritten."
        )
        if message:
            content += f"\n\n{message}"
        self.query_one("#details", Static).update(content)

    def run_github_command(self, command: tuple[str, ...]) -> None:
        """Give the CLI the terminal for browser sign in and guided prompts."""
        try:
            with self.app.suspend():
                result = subprocess.run([sys.executable, "-m", "devrestore", *command], check=False)
                try:
                    input("\nPress Enter to return to DevRestore...")
                except (EOFError, KeyboardInterrupt):
                    pass
        except (OSError, SuspendNotSupported) as exc:
            message = f"Could not open guided command: {exc}"
            if self.title_text == "Set Up This Computer":
                self.show_setup_status(message)
            else:
                self.show_github_status(message)
            return
        message = (
            "Action finished."
            if result.returncode == 0
            else "Action failed. Review the message shown in the terminal."
        )
        if self.title_text == "Set Up This Computer":
            self.show_setup_status(message)
        else:
            self.show_github_status(message)

    def poll_scan(self) -> None:
        if self._scan_future is None or not self._scan_future.done():
            return
        try:
            result = self._scan_future.result()
            self._scan_result = result
            lines = [
                f"{result.system.distro} {result.system.version} · {result.system.architecture}",
                "",
                f"SDK installations ({len(result.sdks)}):",
            ]
            if result.sdks:
                lines.extend(
                    f"{sdk.id:14} {sdk.version or '—':16} {len(sdk.components)} components"
                    for sdk in result.sdks
                )
            else:
                lines.append("None found")
            lines.extend(("", f"Tools ({len(result.tools)}):"))
            lines.extend(
                f"{tool.id:14} {tool.version or 'unknown':16} {tool.category}"
                for tool in result.tools
            )
            lines.append(
                f"\n{len(result.tools)} tools found. Enter a name below to save this scan."
            )
            content = "\n".join(lines)
            self.query_one("#save-profile", Button).disabled = False
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            content = f"Scan failed: {exc}"
        self.query_one("#details", Static).update(content)
        self.query_one("#detail-scroll", VerticalScroll).focus()
        self._scan_future = None
        if self._scan_timer:
            self._scan_timer.stop()
            self._scan_timer = None
        if self._scan_pool:
            self._scan_pool.shutdown(wait=False)
            self._scan_pool = None

    def on_unmount(self) -> None:
        if self._scan_timer:
            self._scan_timer.stop()
        if self._scan_pool:
            self._scan_pool.shutdown(wait=False, cancel_futures=True)

    def load_profiles(self) -> None:
        def rows() -> tuple[list[str], list[str]]:
            store = ProfileStore()
            names = store.list_names()
            entries = []
            for name in names:
                try:
                    manifest = store.load(name)
                    entries.append(
                        f"{name:24} {len(manifest.tools):3} tools  ·  {len(manifest.sdks):3} SDKs  ·  {manifest.source.distro}"
                    )
                except (OSError, ValueError):
                    entries.append(f"{name:24} invalid profile")
            return names, entries

        names, entries = rows()
        lines = ["Saved local profiles", ""]
        lines.extend(entries)
        if not names:
            lines.append("No profiles yet. Run devrestore save --profile NAME.")
        self.query_one("#details", Static).update("\n".join(lines))


class DevRestoreApp(App):
    TITLE = "DevRestore"
    SUB_TITLE = "Portable Linux environments"
    CSS = """
    Screen { background: #071310; color: #d5f0e5; align: center top; }
    #main { width: 90%; max-width: 86; margin: 0; padding: 0 1; border: round #288c70; background: #10231d; }
    #detail-main { width: 90%; max-width: 86; height: 1fr; margin: 0; padding: 0 1; border: round #288c70; background: #10231d; }
    #detail-scroll { height: 1fr; overflow-y: auto; }
    #detail-actions { height: auto; }
    #detail-actions Button { min-width: 12; }
    #eyebrow { color: #78a998; text-style: bold; }
    #brand { color: #4de0aa; text-style: bold; height: auto; }
    #tagline { color: #c4e8d8; text-style: bold; }
    #summary { color: #9ac8b7; background: #17372d; padding: 0 1; margin: 1 0; }
    #menu-label { color: #5ad3a6; text-style: bold; }
    #menu { height: 9; border: round #28634f; background: #10231d; }
    #menu > .option-list--option-highlighted { background: #19765b; color: white; text-style: bold; }
    #hint { color: #a4c8b8; text-align: center; }
    .heading { color: #4de0aa; text-style: bold; margin-bottom: 1; }
    #details { height: auto; }
    #profile-name { width: 1fr; margin-top: 1; }
    #save-feedback { color: #9ac8b7; height: auto; }
    Button { margin-top: 1; }
    """
    BINDINGS: ClassVar = [("q", "quit", "Quit")]

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())
