"""Chrome native messaging bridge.

Lets the extension drive Humble and Steam in the tabs the user is already
signed into, so there is no second sign-in in an isolated profile and no debug
port left open.

Traffic runs both ways. The extension asks this process what to do with what it
read; and an agent running ``hskr browser <action>`` in a terminal queues an
instruction that travels out to the extension, so a run needs nobody to open
the popup and click.

The extension fetches and posts. Ownership matching, storage, rate-limit
handling, and the decision of what is worth redeeming stay here, so there is
one implementation rather than a JavaScript copy to keep in sync.
"""

from __future__ import annotations

from humble_steam_key_redeemer.bridge._host import (
    BROWSER_ACTIONS,
    NATIVE_HOST_NAME,
    BridgeError,
    handle_message,
    install_manifest,
    read_message,
    run_command,
    run_host,
    write_message,
)

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
