"""Typer application definition."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from humble_steam_key_redeemer import __version__
from humble_steam_key_redeemer.core import KeyRecord, RedeemerStore, RedemptionEngine
from humble_steam_key_redeemer.humble import (
    HUMBLE_LOGIN_PAGE,
    HumbleAPIError,
    HumbleBrowser,
    HumbleBrowserError,
    HumbleClient,
    to_key_records,
)
from humble_steam_key_redeemer.settings import Settings
from humble_steam_key_redeemer.steam import SteamCredentials, VendorFabricSteamGateway

app = typer.Typer(
    name="hskr",
    help="Redeem Humble Bundle keys on Steam, skipping games you already own.",
    no_args_is_help=True,
    add_completion=True,
)
console = Console()
error_console = Console(stderr=True)


def _version(value: bool) -> None:
    """Print the version and exit."""
    if value:
        console.print(f"humble-steam-key-redeemer {__version__}")
        raise typer.Exit


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True, help="Show the version and exit."),
    ] = False,
) -> None:
    """Redeem Humble Bundle keys on Steam."""


def _settings(state_dir: Path | None, headless: bool | None) -> Settings:
    """Build settings with CLI overrides applied."""
    overrides: dict[str, object] = {}
    if state_dir is not None:
        overrides["state_dir"] = state_dir
    if headless is not None:
        overrides["headless"] = headless
    settings = Settings(**overrides)  # type: ignore[arg-type]
    settings.ensure_state_dir()
    return settings


StateDirOption = Annotated[
    Path | None,
    typer.Option("--state-dir", help="Directory for the database and saved sessions."),
]
HeadlessOption = Annotated[
    bool | None,
    typer.Option("--headless/--headed", help="Run the browser with or without a window."),
]


@app.command()
def sync(
    state_dir: StateDirOption = None,
    headless: HeadlessOption = None,
) -> None:
    """Import the Humble library into the local database.

    Signing in happens in the browser window, so Humble's own login, Humble
    Guard, and two-factor prompts are handled by Humble rather than being
    re-implemented (and rather than this tool ever seeing the password).
    """
    settings = _settings(state_dir, headless)
    store = RedeemerStore(settings.database_path)

    try:
        with HumbleBrowser(settings) as browser:
            client = HumbleClient(browser)

            if not client.is_logged_in():
                if settings.headless:
                    error_console.print(
                        "[red]Not signed in to Humble.[/red] Run "
                        "[bold]hskr login[/bold] first, or pass [bold]--headed[/bold]."
                    )
                    raise typer.Exit(1)
                console.print(f"Sign in to Humble in the browser window: {HUMBLE_LOGIN_PAGE}")
                browser.goto(HUMBLE_LOGIN_PAGE)
                typer.confirm("Press Enter once you are signed in", default=True, abort=False)
                if not client.is_logged_in():
                    error_console.print("[red]Still not signed in.[/red]")
                    raise typer.Exit(1)

            browser.save_session()
            with console.status("Reading your Humble orders..."):
                orders = client.order_details()
            records = to_key_records(orders)
            written = store.upsert_keys(records)
    except HumbleBrowserError as exc:
        error_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    steam_keys = [record for record in records if record.is_steam]
    revealed = sum(1 for record in steam_keys if record.is_revealed)
    console.print(
        f"Imported [bold]{written}[/bold] entries from [bold]{len(orders)}[/bold] orders "
        f"({len(steam_keys)} Steam keys: {revealed} revealed, {len(steam_keys) - revealed} unrevealed)."
    )


@app.command()
def login(
    state_dir: StateDirOption = None,
) -> None:
    """Sign in to Humble in a visible browser window and save the session."""
    settings = _settings(state_dir, headless=False)
    try:
        with HumbleBrowser(settings) as browser:
            client = HumbleClient(browser)
            browser.goto(HUMBLE_LOGIN_PAGE)
            console.print("Complete the Humble sign-in in the browser window.")
            typer.confirm("Press Enter once you are signed in", default=True, abort=False)
            if not client.is_logged_in():
                error_console.print("[red]Sign-in was not completed.[/red]")
                raise typer.Exit(1)
            path = browser.save_session()
    except HumbleBrowserError as exc:
        error_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"Humble session saved to [bold]{path}[/bold].")


@app.command()
def status(state_dir: StateDirOption = None) -> None:
    """Show what is in the local database."""
    settings = _settings(state_dir, headless=None)
    store = RedeemerStore(settings.database_path)
    keys = list(store.all_keys())

    if not keys:
        console.print("No keys stored yet. Run [bold]hskr sync[/bold] first.")
        return

    counts: dict[str, int] = {}
    for key in keys:
        counts[key.state.value] = counts.get(key.state.value, 0) + 1

    table = Table(title="Humble key library")
    table.add_column("State")
    table.add_column("Count", justify="right")
    for state, count in sorted(counts.items()):
        table.add_row(state, str(count))
    console.print(table)
    console.print(
        f"[dim]{sum(1 for k in keys if k.is_steam)} Steam keys, "
        f"{len(store.pending_keys())} still worth attempting.[/dim]"
    )


@app.command()
def redeem(
    state_dir: StateDirOption = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would be redeemed without contacting Steam.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not prompt for confirmation.")] = False,
    reveal: Annotated[
        bool,
        typer.Option(
            "--reveal/--no-reveal",
            help="Reveal unrevealed Humble keys. This forfeits gift links and cannot be undone.",
        ),
    ] = False,
    limit: Annotated[int, typer.Option("--limit", min=0, help="Maximum keys to attempt (0 = no limit).")] = 0,
    account: Annotated[str | None, typer.Option("--steam-account", help="Steam account name.")] = None,
    headless: HeadlessOption = None,
) -> None:
    """Redeem Steam keys that the account does not already own."""
    settings = _settings(state_dir, headless)
    store = RedeemerStore(settings.database_path)

    pending = store.pending_keys()
    if not pending:
        console.print("Nothing to redeem. Run [bold]hskr sync[/bold] to import your library.")
        return

    gateway = VendorFabricSteamGateway(settings)
    if not gateway.restore():
        if dry_run:
            error_console.print("[red]Steam sign-in required, even for --dry-run (ownership check).[/red]")
            raise typer.Exit(1)
        account_name = account or typer.prompt("Steam account name")
        password = typer.prompt("Steam password", hide_input=True)
        code = typer.prompt("Steam Guard code (blank if none)", default="", show_default=False)
        gateway.authenticate(
            SteamCredentials(account_name=account_name, password=password, steam_guard_code=code or None)
        )

    with gateway:
        engine = RedemptionEngine(store, gateway)
        with console.status("Checking which games you already own on Steam..."):
            plan = engine.plan(
                pending,
                match_threshold=settings.match_threshold,
                confirm_threshold=settings.confirm_threshold,
            )

        _print_plan(plan)

        if dry_run:
            console.print("[yellow]Dry run: nothing was redeemed.[/yellow]")
            return

        attempts = plan.to_attempt
        needing_reveal = [entry for entry in attempts if not entry.record.is_revealed]
        if needing_reveal and not reveal:
            console.print(
                f"[yellow]{len(needing_reveal)} keys are unrevealed and will be skipped."
                " Pass --reveal to reveal them.[/yellow]"
            )

        if not yes and not typer.confirm(f"Attempt {len(attempts)} keys on Steam?", default=False):
            raise typer.Abort

        if reveal and needing_reveal:
            # Revealing goes through Humble, so the browser is only opened when
            # there is actually something to reveal.
            if not yes and not typer.confirm(
                f"Reveal {len(needing_reveal)} keys on Humble? This forfeits their gift "
                "links and cannot be undone.",
                default=False,
            ):
                raise typer.Abort
            with HumbleBrowser(settings) as browser:
                summary = engine.redeem(
                    plan,
                    limit=limit,
                    on_result=_report,
                    reveal=_revealer(HumbleClient(browser)),
                )
        else:
            summary = engine.redeem(plan, limit=limit, on_result=_report)

    console.print(
        f"\n[green]{summary.redeemed} redeemed[/green], "
        f"{summary.already_owned} already owned, "
        f"[red]{summary.failed} failed[/red], {summary.skipped} skipped."
    )
    if summary.rate_limited:
        console.print(
            "[yellow]Steam rate limit reached. It clears about an hour after the first "
            "attempt; rerun then.[/yellow]"
        )


def _revealer(client: HumbleClient) -> Callable[[KeyRecord], str | None]:
    """Build the callback the engine uses to reveal a key on Humble.

    A key that Humble declines to reveal is reported and skipped rather than
    aborting the run, since the remaining keys are still redeemable.

    Args:
        client: An authenticated Humble client.

    Returns:
        A callable returning the revealed key, or ``None`` on failure.
    """

    def reveal(record: KeyRecord) -> str | None:
        try:
            return client.reveal_key(record)
        except HumbleAPIError as exc:
            console.print(f"  [yellow]--[/yellow]  {record.human_name}: {exc}")
            return None

    return reveal


def _print_plan(plan: object) -> None:
    """Render the planned actions."""
    attempts = plan.to_attempt  # type: ignore[attr-defined]
    skipped = plan.skipped  # type: ignore[attr-defined]
    uncertain = plan.uncertain  # type: ignore[attr-defined]

    console.print(f"[bold]{len(attempts)}[/bold] to attempt, [bold]{len(skipped)}[/bold] skipped.")

    if uncertain:
        table = Table(title="Skipped, but not certain you own these")
        table.add_column("Humble title")
        table.add_column("Matched Steam app")
        table.add_column("Score", justify="right")
        for entry in uncertain:
            table.add_row(
                entry.record.human_name,
                entry.decision.app_name or "",
                str(entry.decision.score),
            )
        console.print(table)


def _report(record: object, attempt: object) -> None:
    """Print one redemption outcome as it happens."""
    name = record.human_name  # type: ignore[attr-defined]
    if attempt.succeeded:  # type: ignore[attr-defined]
        console.print(f"  [green]OK[/green]  {name}")
    else:
        console.print(f"  [red]--[/red]  {name}: {attempt.detail}")  # type: ignore[attr-defined]


@app.command()
def export(
    destination: Annotated[Path, typer.Argument(help="Output CSV path.")],
    state_dir: StateDirOption = None,
    steam_only: Annotated[bool, typer.Option("--steam-only", help="Export only Steam keys.")] = False,
) -> None:
    """Export the stored library to a CSV report."""
    settings = _settings(state_dir, headless=None)
    store = RedeemerStore(settings.database_path)
    path = store.export_csv(destination, steam_only=steam_only)
    console.print(f"Exported to [bold]{path}[/bold].")


@app.command()
def logout(state_dir: StateDirOption = None) -> None:
    """Delete saved Humble and Steam sessions."""
    settings = _settings(state_dir, headless=None)
    removed = []
    for path in (settings.humble_session_path, settings.steam_session_path):
        if path.exists():
            path.unlink()
            removed.append(path.name)
    console.print(f"Removed {', '.join(removed)}." if removed else "No saved sessions.")


def main() -> None:
    """Entry point for the console script."""
    app()


__all__ = ["app", "main"]
