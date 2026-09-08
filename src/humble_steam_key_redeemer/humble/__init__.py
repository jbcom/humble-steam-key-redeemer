"""Humble Bundle access.

Humble publishes no API for library or key access, so this half of the tool
drives a real browser and issues Humble's own XHR calls from inside the
authenticated page.

Example::

    from humble_steam_key_redeemer.humble import HumbleBrowser, HumbleClient

    with HumbleBrowser(settings) as browser:
        client = HumbleClient(browser)
        if client.is_logged_in():
            orders = client.order_details()
"""

from __future__ import annotations

from humble_steam_key_redeemer.humble._browser import (
    HUMBLE_LIBRARY_PAGE,
    HUMBLE_LOGIN_PAGE,
    HUMBLE_SUBSCRIPTION_PAGE,
    HumbleBrowser,
    HumbleBrowserError,
)
from humble_steam_key_redeemer.humble._client import (
    HumbleAPIError,
    HumbleClient,
    iter_tpkds,
    to_key_records,
)

__all__ = [
    "HUMBLE_LIBRARY_PAGE",
    "HUMBLE_LOGIN_PAGE",
    "HUMBLE_SUBSCRIPTION_PAGE",
    "HumbleAPIError",
    "HumbleBrowser",
    "HumbleBrowserError",
    "HumbleClient",
    "iter_tpkds",
    "to_key_records",
]
