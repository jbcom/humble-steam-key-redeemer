"""Chrome native messaging bridge.

Lets the browser extension hand this tool the Humble session from the browser
the user is already signed into, so there is no second sign-in in an isolated
profile and no debug port left open.

The extension only reads cookies and relays commands. Ownership matching,
storage, rate-limit handling, and redemption stay here, so there is one
implementation rather than a JavaScript copy to keep in sync.
"""

from __future__ import annotations

from humble_steam_key_redeemer.bridge._host import (
    NATIVE_HOST_NAME,
    BridgeError,
    handle_message,
    install_manifest,
    read_message,
    run_host,
    write_message,
)

__all__ = [
    "NATIVE_HOST_NAME",
    "BridgeError",
    "handle_message",
    "install_manifest",
    "read_message",
    "run_host",
    "write_message",
]
