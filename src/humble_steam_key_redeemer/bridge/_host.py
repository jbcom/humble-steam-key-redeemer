"""Native messaging host for the browser extension.

Chrome speaks to a native host over stdin and stdout, framing each message as a
32-bit little-endian length followed by that many bytes of UTF-8 JSON. Nothing
listens on a port, so the session never crosses a network boundary.

Messages arrive as ``{"command": ..., "session": {...}}``. The session is
Playwright's ``storage_state`` shape, which means it can be written straight to
the session file the rest of the tool already reads.
"""

from __future__ import annotations

import json
import struct
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO

from humble_steam_key_redeemer.bridge import _queue
from humble_steam_key_redeemer.core import RedeemerStore, RedemptionEngine
from humble_steam_key_redeemer.core.models import KeyState
from humble_steam_key_redeemer.settings import Settings

NATIVE_HOST_NAME = "com.jbcom.hskr"

# Chrome rejects a native message larger than 1 MB, and refuses to send one
# larger than 64 MB. Reading a bogus length would otherwise allocate wildly.
_MAX_MESSAGE_BYTES = 64 * 1024 * 1024

# Chrome frames each message with a 32-bit little-endian length prefix.
_HEADER_BYTES = 4


class BridgeError(RuntimeError):
    """Raised when a native message cannot be read or handled."""


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    """Read one native message.

    Args:
        stream: Binary stream carrying the framed message.

    Returns:
        The decoded message, or ``None`` when the stream has closed.

    Raises:
        BridgeError: If the framing or payload is malformed.
    """
    header = stream.read(_HEADER_BYTES)
    if len(header) < _HEADER_BYTES:
        return None

    (length,) = struct.unpack("<I", header)
    if length > _MAX_MESSAGE_BYTES:
        raise BridgeError(f"Native message of {length} bytes exceeds the maximum")

    payload = stream.read(length)
    if len(payload) < length:
        raise BridgeError("Native message ended early")

    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise BridgeError(f"Native message was not valid JSON: {exc}") from exc

    if not isinstance(message, dict):
        raise BridgeError("Native message must be a JSON object")
    return message


def write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    """Write one native message.

    Args:
        stream: Binary stream to write to.
        message: JSON-serializable reply.
    """
    payload = json.dumps(message).encode("utf-8")
    stream.write(struct.pack("<I", len(payload)))
    stream.write(payload)
    stream.flush()


def handle_message(message: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    """Act on one message from the extension.

    The extension reads Humble and Steam in the tabs the user is signed into and
    sends the raw payloads here. Every decision — what is already owned, what is
    worth an activation, when to stop — is made in this process, so there is one
    implementation rather than a JavaScript copy of it.

    Args:
        message: Decoded native message.
        settings: Runtime configuration; defaults to the environment's.

    Returns:
        A reply describing what happened.
    """
    settings = settings or Settings()
    command = str(message.get("command", ""))

    handlers: dict[str, Callable[[dict[str, Any], Settings], dict[str, Any]]] = {
        "status": _status,
        "sync": _sync,
        "plan": _plan,
        "attempting": _attempting,
        "record": _record,
        "finish": _finish,
    }

    handler = handlers.get(command)
    if handler is None:
        return {"ok": False, "error": f"Unknown command: {command!r}"}

    try:
        return handler(message, settings)
    except BridgeError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _status(_message: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Report what the local database holds."""
    store = RedeemerStore(settings.database_path)
    keys = list(store.all_keys())
    return {
        "ok": True,
        "keys": len(keys),
        "steam_keys": sum(1 for key in keys if key.is_steam),
        "pending": len(store.pending_keys()),
        "database": str(settings.database_path),
    }


def _sync(message: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Store the orders the extension read from Humble.

    Args:
        message: Native message carrying ``orders``.
        settings: Runtime configuration.

    Returns:
        Counts describing what was imported.
    """
    from humble_steam_key_redeemer.humble import to_key_records  # noqa: PLC0415

    orders = message.get("orders")
    if not isinstance(orders, list):
        raise BridgeError("Message carried no orders")

    records = to_key_records(orders)
    store = RedeemerStore(settings.database_path)
    written = store.upsert_keys(records)

    steam_keys = [record for record in records if record.is_steam]
    return {
        "ok": True,
        "orders": len(orders),
        "keys": written,
        "steam_keys": len(steam_keys),
        "revealed": sum(1 for record in steam_keys if record.is_revealed),
    }


def _plan(message: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Decide which keys are worth attempting, given the live Steam library.

    Args:
        message: Native message carrying ``owned`` and optionally ``reveal``.
        settings: Runtime configuration.

    Returns:
        The keys to attempt, in order, plus what is being skipped and why.
    """
    owned_raw = message.get("owned")
    if not isinstance(owned_raw, dict):
        raise BridgeError("Message carried no owned-app list")

    owned = {int(app_id): str(name) for app_id, name in owned_raw.items()}
    reveal = bool(message.get("reveal"))

    store = RedeemerStore(settings.database_path)
    pending = store.pending_keys()
    if not pending:
        return {"ok": True, "attempts": [], "detail": "Nothing pending; import the library first."}

    engine = RedemptionEngine(store, _StaticSteam(owned))
    plan = engine.plan(
        pending,
        match_threshold=settings.match_threshold,
        confirm_threshold=settings.confirm_threshold,
    )

    from vendor_fabric.steam import is_valid_key  # noqa: PLC0415

    attempts = []
    unrevealed = 0
    for entry in plan.to_attempt:
        record = entry.record
        if not record.redeemed_key_val and not reveal:
            # Revealing forfeits the gift link permanently, so it only happens
            # when the caller explicitly asked for it.
            unrevealed += 1
            continue

        # Gift links and placeholder text live in the same field as real keys.
        # Sending one to Steam spends one of about ten failed activations an
        # hour, so the browser never sees it — the same guard the engine
        # applies, because the browser path must not be the lenient one.
        if record.redeemed_key_val and not is_valid_key(record.redeemed_key_val):
            record.state = KeyState.SKIPPED
            store.update_key(record)
            continue

        attempts.append(
            {
                "id": record.id,
                "title": record.human_name,
                "key": record.redeemed_key_val,
                "reveal": None
                if record.redeemed_key_val
                else {
                    "machineName": record.machine_name,
                    "gamekey": record.gamekey,
                    "keyIndex": record.key_index or 0,
                },
            }
        )

    limit = settings.max_redemptions_per_run
    if limit:
        attempts = attempts[:limit]

    return {
        "ok": True,
        "attempts": attempts,
        # Unrevealed keys are dropped above, so a library of nothing but those
        # would otherwise report zero attempts and zero skipped, hiding the
        # fact that --reveal is what it is waiting for.
        "skipped": len(plan.skipped) + unrevealed,
        "unrevealed": unrevealed,
        "uncertain": [
            {"title": entry.record.human_name, "matched": entry.decision.app_name} for entry in plan.uncertain
        ],
    }


def _attempting(message: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Mark one key in flight, immediately before Steam sees it.

    If the browser, the service worker, or this process dies between here and
    the verdict, the key lands in ATTEMPTED rather than staying pending. Steam
    may well have accepted it, so a silent retry would spend a second
    activation — and one of about ten failures an hour — on a game already
    redeemed. A person decides instead.

    Args:
        message: Native message carrying ``id``.
        settings: Runtime configuration.

    Returns:
        Confirmation that the key was marked.

    Raises:
        BridgeError: If no stored key has that id.
    """
    key_id = message.get("id")
    if not isinstance(key_id, int):
        raise BridgeError("Message carried no key id")

    store = RedeemerStore(settings.database_path)
    record = next((key for key in store.all_keys() if key.id == key_id), None)
    if record is None:
        raise BridgeError(f"No stored key with id {key_id}")

    record.state = KeyState.ATTEMPTED
    store.update_key(record)
    return {"ok": True, "id": key_id, "state": record.state.value}


def _record(message: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Record one redemption verdict reported by the extension.

    Args:
        message: Native message carrying ``result``.
        settings: Runtime configuration.

    Returns:
        How the key was classified.
    """
    from humble_steam_key_redeemer.core.engine import (  # noqa: PLC0415
        ALREADY_OWNED_CODES,
        RATE_LIMITED_CODE,
    )
    from humble_steam_key_redeemer.core.models import RedemptionAttempt  # noqa: PLC0415

    result = message.get("result")
    if not isinstance(result, dict):
        raise BridgeError("Message carried no result")

    key_id = result.get("id")
    if not isinstance(key_id, int):
        raise BridgeError("Result carried no key id")

    raw_body = result.get("result")
    body: dict[str, Any] = raw_body if isinstance(raw_body, dict) else {}
    succeeded = body.get("success") == 1

    raw_code = body.get("purchase_result_details")
    if raw_code is None:
        receipt = body.get("purchase_receipt_info")
        raw_code = receipt.get("result_detail") if isinstance(receipt, dict) else None
    code = int(raw_code) if isinstance(raw_code, int) else 0

    store = RedeemerStore(settings.database_path)
    record = next((key for key in store.all_keys() if key.id == key_id), None)
    if record is None:
        raise BridgeError(f"No stored key with id {key_id}")

    if result.get("key") and not record.redeemed_key_val:
        record.redeemed_key_val = str(result["key"])

    if succeeded:
        record.state = KeyState.REDEEMED
    elif code in ALREADY_OWNED_CODES:
        record.state = KeyState.ALREADY_OWNED
    elif code == RATE_LIMITED_CODE:
        # Never reached a verdict, so the key stays eligible for a later run.
        record.state = KeyState.REVEALED if record.redeemed_key_val else KeyState.UNREVEALED
    else:
        record.state = KeyState.FAILED
    store.update_key(record)

    store.record_attempt(
        RedemptionAttempt(
            key_id=key_id,
            result_code=code,
            result_name=record.state.value,
            detail=str(body.get("purchase_result_details", "")),
            succeeded=succeeded,
        )
    )

    return {"ok": True, "id": key_id, "state": record.state.value}


def _finish(message: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Summarize a completed run.

    Args:
        message: Native message carrying ``results``.
        settings: Runtime configuration.

    Returns:
        Counts by outcome, and whether Steam rate-limited the run.
    """
    from humble_steam_key_redeemer.core.engine import RATE_LIMITED_CODE  # noqa: PLC0415

    results = message.get("results")
    if not isinstance(results, list):
        raise BridgeError("Message carried no results")

    store = RedeemerStore(settings.database_path)

    # A key marked in flight that never reached Steam must not stay ATTEMPTED:
    # that state is terminal, and it means "Steam may have taken this". Nothing
    # was spent, so the key goes back to being worth another run.
    failures = message.get("failures")
    failures = failures if isinstance(failures, list) else []
    if failures:
        failed_ids = {entry.get("id") for entry in failures if isinstance(entry, dict)}
        for record in store.all_keys():
            if record.id in failed_ids and record.state is KeyState.ATTEMPTED:
                record.state = KeyState.REVEALED if record.redeemed_key_val else KeyState.UNREVEALED
                store.update_key(record)

    codes: list[tuple[bool, Any]] = []
    for result in results:
        raw_body = result.get("result") if isinstance(result, dict) else None
        if isinstance(raw_body, dict):
            codes.append((raw_body.get("success") == 1, raw_body.get("purchase_result_details")))

    return {
        "ok": True,
        # Steam verdicts only. A reveal Humble refused spent no activation, so
        # counting it here would overstate what the run cost.
        "attempted": len(results),
        "redeemed": sum(1 for ok, _ in codes if ok),
        "failed_before_steam": len(failures),
        "rate_limited": any(code == RATE_LIMITED_CODE for _, code in codes),
        "pending": len(store.pending_keys()),
    }


class _StaticSteam:
    """Steam gateway backed by ownership the extension already read.

    The engine needs a gateway to plan against, but redemption happens in the
    browser, so this only answers the ownership question.
    """

    def __init__(self, owned: dict[int, str]) -> None:
        self._owned = owned

    def list_owned_apps(self) -> dict[int, str]:
        """Return the owned applications supplied by the browser."""
        return self._owned

    def redeem_key(self, key: str) -> dict[str, Any]:
        """Never called: the extension performs redemption in the page."""
        raise BridgeError("Redemption happens in the browser, not here")


# Actions the extension performs in the user's tabs, as opposed to questions it
# asks this process. An agent drives these; a person would click them.
BROWSER_ACTIONS = ("status", "sync", "preview", "redeem")


def run_command(
    action: str,
    settings: Settings | None = None,
    *,
    reveal: bool = False,
    timeout: float = 900.0,
) -> dict[str, Any]:
    """Instruct the extension to perform one action and return its reply.

    An agent runs this from a terminal, where there is no pipe into the browser:
    Chrome starts the native host itself and owns both ends of it. So the
    instruction goes into the request queue, the host Chrome already started
    forwards it to the extension, and the reply comes back the same way. Nobody
    has to open the popup and click.

    Args:
        action: One of :data:`BROWSER_ACTIONS`.
        settings: Runtime configuration; defaults to the environment's.
        reveal: Whether redemption may reveal keys on Humble first.
        timeout: Seconds to wait for the browser to finish.

    Returns:
        The extension's reply.

    Raises:
        BridgeError: If the action is unknown or nothing answered in time.
    """
    if action not in BROWSER_ACTIONS:
        raise BridgeError(f"Unknown browser action: {action!r}")

    settings = settings or Settings()
    state_dir = settings.ensure_state_dir()

    request_id = _queue.submit(state_dir, {"action": action, "reveal": reveal})
    reply = _queue.collect(state_dir, request_id, timeout)
    if reply is None:
        raise BridgeError(
            "The browser did not respond. Check that Chrome is running with the "
            "extension enabled, and that `hskr bridge --extension-id <ID>` has been "
            "run. Chrome derives an unpacked extension's id from the directory it "
            "was loaded from, so moving or re-cloning the repository changes it and "
            "the registration has to be redone."
        )
    return reply


def run_host(
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
    settings: Settings | None = None,
) -> None:
    """Serve the extension until the browser closes the connection.

    Traffic runs both ways over the one pipe Chrome owns. The extension asks
    questions of this process — what is worth redeeming, what a result meant —
    and this process pushes instructions the other way when an agent has queued
    one. Both are multiplexed here because Chrome gives a native host exactly
    one stdio channel, and it is the only channel that reaches the extension.

    Args:
        stdin: Input stream; defaults to the process's.
        stdout: Output stream; defaults to the process's.
        settings: Runtime configuration; defaults to the environment's.
    """
    source = stdin or sys.stdin.buffer
    sink = stdout or sys.stdout.buffer
    settings = settings or Settings()
    state_dir = settings.ensure_state_dir()

    # Reading stdin blocks, so the queue is watched on its own thread. It only
    # ever writes instructions; replies come back through the read loop below.
    stop = threading.Event()
    lock = threading.Lock()

    # Instructions sent to the extension but not yet answered. If the browser
    # goes away mid-run, whoever is waiting on one is told so rather than
    # sitting out a timeout that could be a quarter of an hour.
    outstanding: dict[str, dict[str, Any]] = {}

    def forward_queued_requests() -> None:
        while not stop.wait(_queue.POLL_SECONDS):
            request = _queue.claim(state_dir)
            if request is None:
                continue
            request_id = str(request.get("requestId"))
            outstanding[request_id] = request
            try:
                with lock:
                    write_message(sink, request)
            except OSError as exc:
                # The pipe is gone. Say so to whoever queued this, rather than
                # letting this thread die and leaving every later instruction
                # to expire against a host that looks alive.
                outstanding.pop(request_id, None)
                _queue.respond(
                    state_dir,
                    request_id,
                    {"ok": False, "error": f"Could not reach the browser: {exc}"},
                )
                return

    pump = threading.Thread(target=forward_queued_requests, daemon=True)
    pump.start()

    try:
        while True:
            try:
                message = read_message(source)
            except BridgeError as exc:
                with lock:
                    write_message(sink, {"ok": False, "error": str(exc)})
                return
            if message is None:
                return

            # A message carrying a requestId is the extension answering an
            # instruction an agent queued, so it goes back to whoever is
            # waiting rather than being handled here.
            request_id = message.get("requestId")
            if request_id:
                outstanding.pop(str(request_id), None)
                _queue.respond(state_dir, str(request_id), message)
                continue

            # Questions and instructions share one pipe, so a question's reply
            # carries the id the extension asked under; otherwise the extension
            # cannot tell which of its outstanding calls was answered.
            reply = handle_message(message, settings)
            reply_to = message.get("replyTo")
            framed = {"replyTo": reply_to, "reply": reply} if reply_to else reply
            with lock:
                write_message(sink, framed)
    finally:
        stop.set()
        # Whatever the browser never answered will never be answered now.
        for pending_id in list(outstanding):
            _queue.respond(
                state_dir,
                pending_id,
                {"ok": False, "error": "The browser disconnected before finishing."},
            )


def _manifest_directory() -> Path:
    """Return the directory Chrome reads native host manifests from."""
    home = Path.home()
    # Read through a variable so type checkers do not narrow away the branches
    # for the platforms this is not currently running on.
    platform = sys.platform
    if platform == "darwin":
        return home / "Library/Application Support/Google/Chrome/NativeMessagingHosts"
    if platform.startswith("win"):  # pragma: no cover - registry-based on Windows
        return home / "AppData/Local/Google/Chrome/User Data/NativeMessagingHosts"
    return home / ".config/google-chrome/NativeMessagingHosts"


def _register_with_windows_registry(manifest_path: Path) -> None:
    """Point Chrome at the manifest, on Windows.

    Windows Chrome finds native hosts through the registry rather than by
    scanning a directory, so writing the JSON alone registers nothing there.

    Args:
        manifest_path: The manifest file Chrome should read.
    """
    if sys.platform != "win32":
        return

    # Windows only. Type checkers running elsewhere correctly call the rest of
    # this function unreachable, and `winreg`'s attributes are declared to
    # exist only on Windows, so the block is skipped rather than mis-checked.
    import winreg  # type: ignore[unreachable] # noqa: PLC0415 # pragma: no cover

    key_path = rf"Software\Google\Chrome\NativeMessagingHosts\{NATIVE_HOST_NAME}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))


def install_manifest(
    extension_id: str,
    executable: str | None = None,
    settings: Settings | None = None,
) -> Path:
    """Register this tool as a native messaging host for the extension.

    Chrome will only start a native host that names the calling extension, so
    the manifest has to be written once with the extension's own id.

    Args:
        extension_id: The extension's Chrome id.
        executable: Command Chrome should run; defaults to this interpreter
            invoking the bridge module.
        settings: Configuration the launcher should pin, so a custom state
            directory survives into the host Chrome starts.

    Returns:
        The manifest path written.
    """
    directory = _manifest_directory()
    directory.mkdir(parents=True, exist_ok=True)

    _register_with_windows_registry(directory / f"{NATIVE_HOST_NAME}.json")

    manifest = {
        "name": NATIVE_HOST_NAME,
        "description": "Humble Steam Key Redeemer native host",
        "path": executable or _default_executable(settings),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{extension_id}/"],
    }

    path = directory / f"{NATIVE_HOST_NAME}.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def _default_executable(settings: Settings | None = None) -> str:
    """Return a launcher script path, creating it when needed.

    Chrome executes the manifest's ``path`` directly with no arguments, so a
    bare interpreter will not do; a small shell wrapper is written instead.

    The wrapper pins the state directory it was registered with. Chrome starts
    the host with no arguments and none of the shell's environment, so a host
    that rebuilt settings from defaults would read a different database than
    the one the user chose — and report an empty library after a successful
    import into the directory they asked for.

    Args:
        settings: Configuration to pin; defaults to the environment's.

    Returns:
        The launcher's path.
    """
    settings = settings or Settings()
    settings.ensure_state_dir()

    if sys.platform == "win32":  # pragma: no cover - Windows only
        # Chrome runs this directly, and Windows cannot execute a shell script.
        launcher = settings.state_dir / "hskr-native-host.bat"
        launcher.write_text(
            "@echo off\r\n"
            f'set "HSKR_STATE_DIR={settings.state_dir}"\r\n'
            f'"{sys.executable}" -m humble_steam_key_redeemer.bridge %*\r\n',
            encoding="utf-8",
        )
        return str(launcher)

    launcher = settings.state_dir / "hskr-native-host"
    launcher.write_text(
        "#!/bin/sh\n"
        f'HSKR_STATE_DIR="{settings.state_dir}"\n'
        "export HSKR_STATE_DIR\n"
        f'exec "{sys.executable}" -m humble_steam_key_redeemer.bridge "$@"\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return str(launcher)


__all__ = [
    "BROWSER_ACTIONS",
    "NATIVE_HOST_NAME",
    "BridgeError",
    "handle_message",
    "install_manifest",
    "read_message",
    "run_command",
    "run_host",
    "write_message",
]
