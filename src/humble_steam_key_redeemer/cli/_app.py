"""Typer application definition."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from humble_steam_key_redeemer import __version__
from humble_steam_key_redeemer.bridge import (
    BROWSER_ACTIONS,
    BridgeError,
    install_manifest,
    run_command,
    run_host,
)
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

# How often to re-check whether a browser sign-in has completed.
_LOGIN_POLL_SECONDS = 3


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


def _await_login(client: HumbleClient, timeout: int = 600) -> bool:
    """Wait until the Humble session is valid.

    Polling rather than prompting means this works with no terminal attached.

    Args:
        client: Client whose session is checked.
        timeout: Seconds to wait; ``0`` waits indefinitely.

    Returns:
        ``True`` once signed in, ``False`` on timeout.
    """
    deadline = time.monotonic() + timeout if timeout else None
    while True:
        if client.is_logged_in():
            return True
        if deadline is not None and time.monotonic() > deadline:
            return False
        time.sleep(_LOGIN_POLL_SECONDS)


def _settings(
    state_dir: Path | None,
    headless: bool | None,
    cdp_endpoint: str | None = None,
) -> Settings:
    """Build settings with CLI overrides applied."""
    overrides: dict[str, object] = {}
    if state_dir is not None:
        overrides["state_dir"] = state_dir
    if headless is not None:
        overrides["headless"] = headless
    if cdp_endpoint is not None:
        overrides["cdp_endpoint"] = cdp_endpoint
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
            client = HumbleClient(browser, int(settings.request_timeout * 1000))

            if not client.is_logged_in():
                if settings.headless:
                    error_console.print(
                        "[red]Not signed in to Humble.[/red] Run "
                        "[bold]hskr login[/bold] first, or pass [bold]--headed[/bold]."
                    )
                    raise typer.Exit(1)
                console.print(f"Sign in to Humble in the browser window: {HUMBLE_LOGIN_PAGE}")
                browser.goto(HUMBLE_LOGIN_PAGE)
                if not _await_login(client):
                    error_console.print("[red]Still not signed in.[/red]")
                    raise typer.Exit(1)

            browser.save_session()
            with console.status("Reading your Humble orders..."):
                orders = client.order_details()
            records = to_key_records(orders)
            written = store.upsert_keys(records)
    except (HumbleBrowserError, HumbleAPIError) as exc:
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
    timeout: Annotated[
        int, typer.Option("--timeout", min=0, help="Seconds to wait for sign-in (0 waits forever).")
    ] = 600,
    cdp: Annotated[
        str | None,
        typer.Option("--cdp", help="Attach to a browser already running at this CDP endpoint."),
    ] = None,
) -> None:
    """Sign in to Humble in a browser window and save the session.

    The command polls until the session is valid rather than waiting on a
    keypress, so it works unattended — under an agent, in a script, or with no
    terminal attached — as well as interactively.
    """
    settings = _settings(state_dir, headless=False, cdp_endpoint=cdp)
    try:
        with HumbleBrowser(settings) as browser:
            client = HumbleClient(browser, int(settings.request_timeout * 1000))
            browser.goto(HUMBLE_LOGIN_PAGE)

            if client.is_logged_in():
                path = browser.save_session()
                console.print(f"Already signed in. Session saved to [bold]{path}[/bold].")
                return

            console.print("Complete the Humble sign-in in the browser window.")
            console.print("[dim]Waiting for sign-in; no keypress needed.[/dim]")

            deadline = time.monotonic() + timeout if timeout else None
            with console.status("Waiting for Humble sign-in..."):
                while True:
                    if client.is_logged_in():
                        break
                    if deadline is not None and time.monotonic() > deadline:
                        error_console.print(f"[red]Sign-in was not completed within {timeout}s.[/red]")
                        raise typer.Exit(1)
                    time.sleep(_LOGIN_POLL_SECONDS)

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
    # Restoring a session for a different account would run irreversible
    # activations against the wrong library, so an explicit --steam-account
    # must match the saved session before it is reused.
    if not gateway.restore(account_name=account):
        if dry_run:
            error_console.print("[red]Steam sign-in required, even for --dry-run (ownership check).[/red]")
            raise typer.Exit(1)
        account_name = account or typer.prompt("Steam account name")
        password = typer.prompt("Steam password", hide_input=True)
        code = typer.prompt("Steam Guard code (blank if none)", default="", show_default=False)
        gateway.authenticate(
            SteamCredentials(account_name=account_name, password=password, steam_guard_code=code or None)
        )

    # --limit overrides the configured safety cap; otherwise the cap applies.
    effective_limit = limit or settings.max_redemptions_per_run

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
                humble = HumbleClient(browser, int(settings.request_timeout * 1000))
                # A fresh page sits on about:blank. Revealing issues fetches
                # that must run from the Humble origin to carry its session
                # cookies, so navigate and confirm the session before starting.
                if not humble.is_logged_in():
                    error_console.print(
                        "[red]Not signed in to Humble, so keys cannot be revealed.[/red] "
                        "Run [bold]hskr login[/bold] first."
                    )
                    raise typer.Exit(1)
                summary = engine.redeem(
                    plan,
                    limit=effective_limit,
                    on_result=_report,
                    reveal=_revealer(humble),
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
        table = Table(title="Attempted anyway — a possible match we are not sure about")
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
def bridge(
    extension_id: Annotated[
        str | None,
        typer.Option("--extension-id", help="Chrome extension id to authorize."),
    ] = None,
    serve: Annotated[
        bool, typer.Option("--serve", hidden=True, help="Run as the native messaging host.")
    ] = False,
    state_dir: StateDirOption = None,
) -> None:
    """Set up the Chrome extension bridge, or serve it.

    Without arguments this prints the steps to install the extension. With
    `--extension-id` it registers the native messaging host so Chrome will let
    that extension talk to this tool.
    """
    if serve:
        run_host()
        return

    settings = _settings(state_dir, headless=None)
    settings.ensure_state_dir()
    source = Path(__file__).resolve().parents[3] / "extension"

    if extension_id is None:
        console.print("[bold]Install the Chrome extension[/bold]\n")
        console.print("1. Open [bold]chrome://extensions[/bold]")
        console.print("2. Turn on [bold]Developer mode[/bold] (top right)")
        console.print("3. Click [bold]Load unpacked[/bold] and choose:")
        console.print(f"   [bold]{source}[/bold]")
        console.print("4. Copy the extension's ID from its card, then run:\n")
        console.print("   [bold]hskr bridge --extension-id <ID>[/bold]\n")
        console.print(
            "[dim]Chrome only starts a native host that names the calling extension, "
            "so the ID has to be registered before the extension can reach this tool.[/dim]"
        )
        return

    manifest = install_manifest(extension_id)
    console.print(f"Registered native messaging host at [bold]{manifest}[/bold].")
    console.print("Reload the extension in chrome://extensions, then either:\n")
    console.print("  [bold]hskr browser sync[/bold]   drive it from here, no clicking")
    console.print("  the toolbar button      the same work, with a person driving it")


@app.command()
def browser(
    action: Annotated[
        str,
        typer.Argument(help=f"What the browser should do: {', '.join(BROWSER_ACTIONS)}."),
    ],
    state_dir: StateDirOption = None,
    reveal: Annotated[
        bool,
        typer.Option(
            "--reveal/--no-reveal",
            help="Reveal unrevealed Humble keys. This forfeits gift links and cannot be undone.",
        ),
    ] = False,
    timeout: Annotated[
        float, typer.Option("--timeout", min=1, help="Seconds to wait for the browser to finish.")
    ] = 900.0,
) -> None:
    """Drive the Chrome extension from the command line.

    This is the unattended path: an agent runs it and the work happens in the
    tabs the user is already signed into, with no popup and no clicking. Chrome
    must be running with the extension enabled and `hskr bridge
    --extension-id <ID>` already done.
    """
    settings = _settings(state_dir, headless=None)
    try:
        reply = run_command(action, settings, reveal=reveal, timeout=timeout)
    except BridgeError as exc:
        error_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if not reply.get("ok"):
        error_console.print(f"[red]{reply.get('error', 'The browser reported a failure.')}[/red]")
        raise typer.Exit(1)

    _print_browser_reply(reply.get("reply"))


def _print_browser_reply(reply: object) -> None:
    """Render whatever the extension sent back, preferring a readable summary."""
    if not isinstance(reply, dict):
        console.print(reply if reply is not None else "Done.")
        return

    if isinstance(reply.get("attempts"), list):
        attempts = reply["attempts"]
        skipped = reply.get("skipped", 0)
        console.print(f"[bold]{len(attempts)}[/bold] to attempt, [bold]{skipped}[/bold] skipped.")
        for attempt in attempts:
            console.print(f"  • {attempt.get('title')}")
        for entry in reply.get("uncertain") or []:
            console.print(f"  [yellow]?[/yellow] {entry.get('title')} → {entry.get('matched')}")
        return

    if "attempted" in reply:
        console.print(
            f"[green]{reply.get('redeemed', 0)} redeemed[/green] of "
            f"{reply.get('attempted', 0)} attempted; {reply.get('pending', 0)} still pending."
        )
        if reply.get("rate_limited"):
            console.print("[yellow]Steam rate limit reached; rerun in about an hour.[/yellow]")
        return

    if "keys" in reply:
        console.print(
            f"[bold]{reply['keys']}[/bold] entries from {reply.get('orders', '?')} orders "
            f"({reply.get('steam_keys', 0)} Steam keys, {reply.get('revealed', 0)} revealed)."
        )
        return

    for name, value in reply.items():
        console.print(f"{name}: {value}")


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
