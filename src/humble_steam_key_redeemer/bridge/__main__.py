"""Entry point Chrome launches for native messaging."""

from __future__ import annotations

from humble_steam_key_redeemer.bridge._host import run_host

if __name__ == "__main__":
    run_host()
