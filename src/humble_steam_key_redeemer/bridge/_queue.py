"""A request queue between a terminal invocation and the browser.

Chrome starts a native host itself and owns both ends of its pipes, so a second
``hskr`` process running in a terminal has no way to write down that pipe. This
is the missing link: the terminal process leaves a request in the state
directory, the host Chrome already started picks it up and instructs the
extension, and the reply comes back the same way.

Files rather than a socket, because a socket would mean a listening port and a
second thing to secure. These files live in the state directory, which is
already ``0700``, and each one exists for the length of a single command.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

# How often each side looks for the other's file. Fast enough that a command
# feels immediate, slow enough that an idle host is not spinning.
POLL_SECONDS = 0.2

# A request nobody claimed is stale rather than pending: the host is not
# running, or Chrome closed it. Anything older is swept rather than answered.
_STALE_SECONDS = 300


def queue_directory(state_dir: Path) -> Path:
    """Return the directory requests are exchanged through, creating it.

    Args:
        state_dir: The tool's state directory.

    Returns:
        The queue directory.
    """
    directory = state_dir / "requests"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.stat().st_mode & 0o077:
        directory.chmod(0o700)
    return directory


def _write_private(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON to a file only this user can read.

    The write goes to a temporary name and is then renamed, so a reader never
    sees a half-written request.

    Args:
        path: Final path to write.
        payload: JSON-serializable content.
    """
    temporary = path.with_suffix(".partial")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    temporary.replace(path)


def _read(path: Path) -> dict[str, Any] | None:
    """Read a queued JSON file, tolerating one that is being written."""
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return content if isinstance(content, dict) else None


def submit(state_dir: Path, request: dict[str, Any]) -> str:
    """Queue a request for the running host to pick up.

    Args:
        state_dir: The tool's state directory.
        request: The instruction to hand the extension.

    Returns:
        The identifier the reply will carry.
    """
    directory = queue_directory(state_dir)
    request_id = str(uuid.uuid4())
    _write_private(directory / f"{request_id}.request", {"requestId": request_id, **request})
    return request_id


def claim(state_dir: Path) -> dict[str, Any] | None:
    """Take the oldest pending request, if there is one.

    The file is removed as it is claimed, so two hosts cannot serve the same
    request twice.

    Args:
        state_dir: The tool's state directory.

    Returns:
        The request, or ``None`` when nothing is pending.
    """
    directory = queue_directory(state_dir)
    now = time.time()

    for path in sorted(directory.glob("*.request"), key=lambda item: item.stat().st_mtime):
        if now - path.stat().st_mtime > _STALE_SECONDS:
            path.unlink(missing_ok=True)
            continue
        request = _read(path)
        path.unlink(missing_ok=True)
        if request is not None:
            return request
    return None


def respond(state_dir: Path, request_id: str, reply: dict[str, Any]) -> None:
    """Leave the reply for whoever submitted the request.

    Args:
        state_dir: The tool's state directory.
        request_id: Identifier from the request.
        reply: The extension's answer.
    """
    _write_private(queue_directory(state_dir) / f"{request_id}.reply", reply)


def collect(state_dir: Path, request_id: str, timeout: float) -> dict[str, Any] | None:
    """Wait for the reply to a submitted request.

    Args:
        state_dir: The tool's state directory.
        request_id: Identifier returned by :func:`submit`.
        timeout: Seconds to wait before giving up.

    Returns:
        The reply, or ``None`` if none arrived in time.
    """
    directory = queue_directory(state_dir)
    path = directory / f"{request_id}.reply"
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if path.exists():
            reply = _read(path)
            if reply is not None:
                path.unlink(missing_ok=True)
                return reply
        time.sleep(POLL_SECONDS)

    # Nothing answered, so drop the request rather than leaving it to be served
    # long after the caller stopped waiting.
    (directory / f"{request_id}.request").unlink(missing_ok=True)
    return None


__all__ = ["POLL_SECONDS", "claim", "collect", "queue_directory", "respond", "submit"]
