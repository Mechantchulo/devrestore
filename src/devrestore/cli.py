"""Command-line interface; all operations delegate to reusable services."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from devrestore.profiles.store import ProfileError, ProfileStore
from devrestore.scanner.tools import FILTERS, scan_environment

app = typer.Typer(
    help="Scan, save and restore Linux developer environments.", no_args_is_help=False
)
profile_app = typer.Typer(help="Inspect a saved profile.")
app.add_typer(profile_app, name="profile")
console = Console()
errors = Console(stderr=True)


def fail(message: str) -> None:
    errors.print(f"[red]Error:[/red] {message}")
    raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Launch the interactive terminal interface when no command is given."""
    if ctx.invoked_subcommand is None:
        from devrestore.tui.app import DevRestoreApp

        DevRestoreApp().run()


@app.command()
def scan(
    profile: Annotated[
        str | None, typer.Option(help="Built-in filter: frontend, backend, fullstack, devops.")
    ] = None,
) -> None:
    """Discover supported development tools on this computer."""
    if profile is not None and profile not in FILTERS:
        fail(f"unknown filter {profile!r}; choose from {', '.join(FILTERS)}")
    result = scan_environment(profile)
    console.print(
        f"[bold teal]DevRestore[/bold teal]  {result.system.distro} {result.system.version} · {result.system.architecture}"
    )
    table = Table("Tool", "Version", "Category", "Executable")
    for tool in result.tools:
        table.add_row(tool.id, tool.version or "unknown", tool.category, tool.path)
    console.print(table)
    console.print(f"{len(result.tools)} tools discovered")
    if result.sdks:
        sdk_table = Table("SDK", "Version", "Components", "Location")
        for sdk in result.sdks:
            sdk_table.add_row(sdk.id, sdk.version or "—", str(len(sdk.components)), sdk.path)
        console.print(sdk_table)
        for sdk in result.sdks:
            if sdk.components:
                console.print(f"[teal]{sdk.id} components:[/teal]")
                for component in sdk.components:
                    console.print(f"  {component.id}  {component.version or 'version unknown'}")
    console.print(f"{len(result.sdks)} SDK installations discovered")


@app.command()
def save(
    profile: Annotated[str, typer.Option(help="Name of the new local profile.")],
    filter_name: Annotated[
        str | None, typer.Option("--filter", help="Built-in scan filter.")
    ] = None,
    include: Annotated[
        list[str] | None, typer.Option(help="Include only these detected tool IDs; repeatable.")
    ] = None,
    exclude: Annotated[
        list[str] | None, typer.Option(help="Exclude these detected tool IDs; repeatable.")
    ] = None,
    include_sdk: Annotated[
        list[str] | None, typer.Option(help="Include only these detected SDK IDs; repeatable.")
    ] = None,
    exclude_sdk: Annotated[
        list[str] | None, typer.Option(help="Exclude these detected SDK IDs; repeatable.")
    ] = None,
    description: Annotated[str, typer.Option(help="Short profile description.")] = "",
) -> None:
    """Scan and save a named local profile."""
    if filter_name is not None and filter_name not in FILTERS:
        fail(f"unknown filter {filter_name!r}")
    try:
        result = scan_environment(filter_name)
        discovered = {tool.id for tool in result.tools}
        if include:
            missing = set(include) - discovered
            if missing:
                fail(f"tools not detected: {', '.join(sorted(missing))}")
            result.tools = [tool for tool in result.tools if tool.id in include]
        if exclude:
            result.tools = [tool for tool in result.tools if tool.id not in exclude]
        if include_sdk:
            missing_sdks = set(include_sdk) - {sdk.id for sdk in result.sdks}
            if missing_sdks:
                fail(f"SDKs not detected: {', '.join(sorted(missing_sdks))}")
            result.sdks = [sdk for sdk in result.sdks if sdk.id in include_sdk]
        if exclude_sdk:
            result.sdks = [sdk for sdk in result.sdks if sdk.id not in exclude_sdk]
        store = ProfileStore()
        manifest = store.create(profile, result, description)
        path = store.save(manifest)
        console.print(
            f"Saved [bold]{len(manifest.tools)}[/bold] tools and [bold]{len(manifest.sdks)}[/bold] SDKs to {path}"
        )
    except (ProfileError, ValidationError, OSError) as exc:
        fail(str(exc))


@app.command()
def profiles() -> None:
    """List local profiles."""
    store = ProfileStore()
    names = store.list_names()
    if not names:
        console.print("No local profiles. Run [bold]devrestore save --profile NAME[/bold].")
        return
    table = Table("Profile", "Tools", "SDKs", "Source", "Created")
    for name in names:
        try:
            manifest = store.load(name)
            table.add_row(
                name,
                str(len(manifest.tools)),
                str(len(manifest.sdks)),
                manifest.source.distro,
                manifest.created_at.strftime("%Y-%m-%d"),
            )
        except ProfileError:
            table.add_row(name, "invalid", "—", "—", "—")
    console.print(table)


@profile_app.command("show")
def profile_show(name: str) -> None:
    """Inspect one local profile."""
    try:
        manifest = ProfileStore().load(name)
    except (ProfileError, ValidationError, OSError) as exc:
        fail(str(exc))
    console.print(
        f"[bold teal]{manifest.profile.name}[/bold teal] — {manifest.profile.description}"
    )
    console.print(f"Source: {manifest.source.distro} {manifest.source.version}")
    table = Table("Tool", "Version preference", "Original provider")
    for tool in manifest.tools:
        table.add_row(tool.id, tool.version or "any", tool.source_provider or "unknown")
    console.print(table)
    if manifest.sdks:
        sdk_table = Table("SDK", "Version", "Components")
        for sdk in manifest.sdks:
            sdk_table.add_row(sdk.id, sdk.version or "—", str(len(sdk.components)))
        console.print(sdk_table)
        for sdk in manifest.sdks:
            for component in sdk.components:
                console.print(f"  {component.id}  {component.version or 'version unknown'}")


@app.command("export")
def export_profile(
    name: str, output: Annotated[Path, typer.Option(help="Destination YAML file.")]
) -> None:
    """Export a local profile as YAML without replacing existing files."""
    import yaml

    try:
        manifest = ProfileStore().load(name)
        with output.open("x", encoding="utf-8") as stream:
            yaml.safe_dump(
                manifest.model_dump(mode="json", exclude_none=True), stream, sort_keys=False
            )
    except (ProfileError, ValidationError, OSError) as exc:
        fail(str(exc))
    console.print(f"Exported {name} to {output}")


@app.command("import")
def import_profile(source: Path) -> None:
    """Validate and import a YAML profile without replacing a local profile."""
    try:
        path = ProfileStore().import_file(source)
    except (ProfileError, ValidationError, OSError) as exc:
        fail(str(exc))
    console.print(f"Imported {path.stem}")


@app.command()
def status(profile: Annotated[str, typer.Option(help="Saved profile name.")]) -> None:
    """Compare a saved profile with detected tools."""
    from devrestore.scanner.sdks import sdk_status

    try:
        manifest = ProfileStore().load(profile)
    except (ProfileError, ValidationError, OSError) as exc:
        fail(str(exc))
    current_scan = scan_environment()
    installed = {tool.id: tool for tool in current_scan.tools}
    table = Table("Tool", "Current", "Saved preference", "Status")
    for tool in manifest.tools:
        current = installed.get(tool.id)
        state = "missing"
        if current:
            state = (
                "version differs"
                if tool.version_policy == "exact" and current.version != tool.version
                else "installed"
            )
        table.add_row(
            tool.id,
            current.version or "unknown" if current else "—",
            tool.version or "any",
            state,
        )
    console.print(table)
    if manifest.sdks:
        sdk_table = Table("SDK", "Saved version", "Status")
        for sdk in manifest.sdks:
            sdk_table.add_row(sdk.id, sdk.version or "—", sdk_status(sdk, current_scan.sdks))
        console.print(sdk_table)


@app.command()
def doctor() -> None:
    """Check platform support and optional dependencies."""
    import shutil

    from devrestore.scanner.system import detect_system

    system = detect_system()
    console.print(f"System: {system.distro} {system.version} ({system.architecture})")
    console.print(
        f"Restore support: {'yes' if system.distro in {'ubuntu', 'debian', 'fedora'} else 'no'}"
    )
    console.print(f"Package managers: {', '.join(system.package_managers) or 'none'}")
    console.print(f"GitHub CLI: {'available' if shutil.which('gh') else 'missing (optional)'}")


@app.command()
def restore(
    profile: Annotated[str, typer.Option(help="Saved profile name.")],
    dry_run: Annotated[bool, typer.Option(help="Show the plan; no installation.")] = False,
    apply: Annotated[
        bool, typer.Option(help="Explicitly approve the planned package installations.")
    ] = False,
    non_interactive: Annotated[
        bool, typer.Option(help="Never prompt. Requires --apply for changes.")
    ] = False,
) -> None:
    """Plan or apply supported APT/DNF package installations."""
    from devrestore.resolver.engine import execute_plan, plan_restore

    try:
        manifest = ProfileStore().load(profile)
    except (ProfileError, ValidationError, OSError) as exc:
        fail(str(exc))
    actions = plan_restore(manifest)
    table = Table("Tool", "Plan", "Detail")
    for action in actions:
        table.add_row(action.tool_id, action.state, action.detail)
    console.print(table)
    pending = [action for action in actions if action.state == "install"]
    if not pending or dry_run:
        return
    if not apply:
        if non_interactive:
            fail("use --apply to approve installation in non-interactive mode")
        console.print(
            "Review the plan, then rerun with [bold]--apply[/bold] to install supported packages."
        )
        return
    results = execute_plan(pending)
    failed = False
    for result in results:
        console.print(
            f"{result.tool_id}: {'OK' if result.success else 'FAILED'} — {result.message}"
        )
        failed |= not result.success
    if failed:
        raise typer.Exit(1)


@app.command()
def login(
    github: Annotated[
        bool, typer.Option("--github", help="Authenticate using the GitHub CLI.")
    ] = False,
    non_interactive: Annotated[
        bool, typer.Option(help="Check existing authentication only.")
    ] = False,
) -> None:
    """Authenticate with GitHub through gh; credentials stay with gh."""
    from devrestore.sync.github import GitHubError, check_auth, login_interactive

    if not github:
        fail("specify --github")
    try:
        if non_interactive:
            check_auth()
        else:
            login_interactive()
        console.print("GitHub CLI authentication is available.")
    except GitHubError as exc:
        fail(str(exc))


@app.command()
def logout(
    yes: Annotated[
        bool, typer.Option(help="Confirm removal of the GitHub CLI authentication.")
    ] = False,
) -> None:
    """Log out of GitHub CLI; this also affects other applications using gh."""
    from devrestore.sync.github import GitHubError, gh

    if not yes:
        fail("logout changes the shared gh authentication; rerun with --yes")
    try:
        gh("auth", "logout")
        console.print("GitHub CLI authentication removed.")
    except GitHubError as exc:
        fail(str(exc))


@app.command()
def connect(
    repository: Annotated[
        str | None, typer.Option(help="Use an existing private repository (OWNER/NAME).")
    ] = None,
) -> None:
    """Sign in and remember a private GitHub repository for profile backup."""
    import shutil

    from devrestore.sync.github import (
        GitHubError,
        GitHubSync,
        check_auth,
        create_private_repository,
        login_interactive,
        save_repository,
        saved_repository,
        validate_repository,
    )

    if not shutil.which("gh"):
        fail(
            "GitHub CLI (gh) is missing. Install it from https://cli.github.com/, then run devrestore connect again"
        )
    try:
        try:
            check_auth()
        except GitHubError:
            console.print("GitHub sign in will open in your browser.")
            if not typer.confirm("Sign in to GitHub now?", default=True):
                return
            login_interactive()
            check_auth()

        if repository is None:
            repository = saved_repository()
            if repository is None:
                name = typer.prompt(
                    "New private repository name", default="devrestore-profiles"
                ).strip()
                # Validate before asking GitHub to create anything.
                validate_repository(f"owner/{name}")
                if not typer.confirm(f"Create private GitHub repository {name!r}?", default=True):
                    return
                repository = create_private_repository(name)

        repository = validate_repository(repository)
        GitHubSync(repository).check_repository(write=True)
        save_repository(repository)
    except (GitHubError, OSError, ValueError) as exc:
        fail(str(exc))
    console.print(f"Connected to [bold]{repository}[/bold].")
    console.print("Back up: [bold]devrestore sync[/bold]")
    console.print("Download: [bold]devrestore sync --direction pull[/bold]")


@app.command()
def sync(
    repository: Annotated[
        str | None,
        typer.Option(
            help="Private GitHub repository OWNER/NAME; defaults to the connected repository."
        ),
    ] = None,
    direction: Annotated[
        str, typer.Option(help="push or pull; changes are never overwritten.")
    ] = "push",
) -> None:
    """Synchronize local profiles with the connected private repository."""
    from devrestore.sync.github import GitHubError, GitHubSync, saved_repository

    if direction not in {"push", "pull"}:
        fail("direction must be push or pull")
    try:
        repository = repository or saved_repository()
        if repository is None:
            fail("no GitHub repository connected; run devrestore connect first")
        service = GitHubSync(repository)
        results = service.push() if direction == "push" else service.pull()
    except (GitHubError, ProfileError, OSError, ValueError) as exc:
        fail(str(exc))
    for result in results:
        console.print(result)
    if not results:
        console.print("No profiles to synchronize.")


@app.command()
def setup(
    repository: Annotated[
        str | None, typer.Option(help="Existing private GitHub repository (OWNER/NAME).")
    ] = None,
    profile: Annotated[
        str | None, typer.Option(help="Profile to restore; prompts if multiple are available.")
    ] = None,
) -> None:
    """Download a GitHub profile and guide the restore on a new computer."""
    import shutil

    from devrestore.resolver.engine import execute_plan, plan_restore
    from devrestore.sync.github import (
        GitHubError,
        GitHubSync,
        check_auth,
        login_interactive,
        save_repository,
        saved_repository,
        validate_repository,
    )

    if not shutil.which("gh"):
        fail("GitHub CLI (gh) is missing. Install it from https://cli.github.com/")
    try:
        try:
            check_auth()
        except GitHubError:
            if not typer.confirm("Sign in to GitHub now?", default=True):
                return
            login_interactive()
            check_auth()

        repository = repository or saved_repository()
        if repository is None:
            repository = typer.prompt("Private GitHub repository (OWNER/NAME)").strip()
        repository = validate_repository(repository)
        service = GitHubSync(repository)
        service.check_repository()
        save_repository(repository)

        console.print(f"Downloading profiles from [bold]{repository}[/bold]...")
        results = service.pull()
        for result in results:
            console.print(result)
        available = [
            name
            for result in results
            for name, separator, state in [result.partition(": ")]
            if separator and state in {"downloaded", "unchanged"}
        ]
        if not available:
            fail("no usable profiles were downloaded from this repository")
        if profile is None:
            if len(available) == 1:
                profile = available[0]
            else:
                console.print(f"Available profiles: {', '.join(available)}")
                profile = typer.prompt("Profile to restore").strip()
        if profile not in available:
            fail(f"profile {profile!r} is unavailable or has a sync conflict")

        manifest = service.store.load(profile)
        current = scan_environment()
        installed = {tool.id: tool for tool in current.tools}
        console.print(f"\n[bold]Current status for {profile}[/bold]")
        status_table = Table("Tool", "Current", "Saved preference", "Status")
        for tool in manifest.tools:
            found = installed.get(tool.id)
            state = "missing"
            if found:
                state = (
                    "version differs"
                    if tool.version_policy == "exact" and found.version != tool.version
                    else "installed"
                )
            status_table.add_row(
                tool.id,
                found.version or "unknown" if found else "—",
                tool.version or "any",
                state,
            )
        console.print(status_table)
        if manifest.sdks:
            from devrestore.scanner.sdks import sdk_status

            sdk_table = Table("SDK", "Saved version", "Status")
            for sdk in manifest.sdks:
                sdk_table.add_row(sdk.id, sdk.version or "—", sdk_status(sdk, current.sdks))
            console.print(sdk_table)

        actions = plan_restore(manifest, distro=current.system.distro, installed=current.tools)
        plan_table = Table("Tool", "Plan", "Detail")
        for action in actions:
            plan_table.add_row(action.tool_id, action.state, action.detail)
        console.print("[bold]Restore plan[/bold]")
        console.print(plan_table)
        pending = [action for action in actions if action.state == "install"]
        if not pending:
            console.print("No supported packages need installation.")
            return
        if not typer.confirm(f"Install {len(pending)} supported package(s)?", default=False):
            console.print("No packages installed.")
            return
        failed = False
        for result in execute_plan(pending):
            console.print(
                f"{result.tool_id}: {'OK' if result.success else 'FAILED'} — {result.message}"
            )
            failed |= not result.success
        if failed:
            raise typer.Exit(1)
    except (GitHubError, ProfileError, ValidationError, OSError) as exc:
        fail(str(exc))
