"""Command-line interface.

Every command works both interactively and non-interactively. Supplying the
relevant flags (and ``--yes``) makes a run scriptable; omitting them falls back
to prompts.
"""

from __future__ import annotations

from humble_steam_key_redeemer.cli._app import app, main

__all__ = ["app", "main"]
