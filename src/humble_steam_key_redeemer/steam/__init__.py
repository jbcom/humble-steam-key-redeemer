"""Steam access, adapted from vendor-fabric's Steam connector.

The connector itself lives in ``vendor_fabric.steam``; this module adapts it
to the engine's :class:`~humble_steam_key_redeemer.core.engine.SteamGateway`
protocol and adds session persistence between runs.
"""

from __future__ import annotations

from humble_steam_key_redeemer.steam._gateway import (
    SteamCredentials,
    VendorFabricSteamGateway,
    load_session,
    save_session,
)

__all__ = [
    "SteamCredentials",
    "VendorFabricSteamGateway",
    "load_session",
    "save_session",
]
