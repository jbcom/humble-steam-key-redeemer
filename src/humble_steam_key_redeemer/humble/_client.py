"""Humble Bundle API access, executed from within the browser session.

Requests run inside the page so they carry Humble's session cookies and
CSRF token without those credentials being copied out of the browser.

Every script below is a JavaScript *function expression* invoked with a single
argument. Values are never interpolated into script text: the CSRF token, the
target URL and the request payload all arrive as data. This is what makes a
title, gamekey or cookie value containing a quote inert rather than executable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from humble_steam_key_redeemer.core.models import KeyRecord, KeyState

if TYPE_CHECKING:
    from humble_steam_key_redeemer.humble._browser import HumbleBrowser


HUMBLE_ORDERS_API = "https://www.humblebundle.com/api/v1/user/order"
HUMBLE_ORDER_DETAILS_API = "https://www.humblebundle.com/api/v1/order/"
HUMBLE_REDEEM_API = "https://www.humblebundle.com/humbler/redeemkey"
HUMBLE_LIBRARY_PAGE = "https://www.humblebundle.com/home/library"

# Humble throttles bursts of order lookups, so details are fetched in batches
# rather than as one unbounded Promise.all over the whole library.
_ORDER_BATCH_SIZE = 20

_HTTP_OK = 200


_IS_LOGGED_IN = """
async () => {
    const response = await fetch('https://www.humblebundle.com/home/library',
                                 { redirect: 'follow' });
    return response.ok && !response.redirected;
}
"""

_FETCH_ORDER_KEYS = """
async () => {
    const response = await fetch('https://www.humblebundle.com/api/v1/user/order');
    if (!response.ok) { throw new Error('Humble returned HTTP ' + response.status); }
    const orders = await response.json();
    return orders.map(order => order.gamekey);
}
"""

_FETCH_ORDER_DETAILS = """
async (gamekeys) => {
    const results = [];
    for (const gamekey of gamekeys) {
        const url = 'https://www.humblebundle.com/api/v1/order/'
                  + encodeURIComponent(gamekey) + '?all_tpkds=true';
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error('Humble returned HTTP ' + response.status
                            + ' for order ' + gamekey);
        }
        results.push(await response.json());
    }
    return results;
}
"""

_POST_FORM = """
async ({ url, payload, csrf, timeoutMs }) => {
    const body = new FormData();
    for (const [key, value] of Object.entries(payload)) {
        body.append(key, value);
    }
    const headers = csrf ? { 'CSRF-Prevention-Token': csrf } : {};
    const response = await fetch(url, {
        method: 'POST', headers, body, signal: AbortSignal.timeout(timeoutMs),
    });
    let parsed = null;
    try { parsed = await response.json(); } catch (error) { parsed = null; }
    return { status: response.status, body: parsed };
}
"""


class HumbleAPIError(RuntimeError):
    """Raised when Humble rejects a request or returns an unusable response."""


class HumbleClient:
    """Reads orders and reveals keys through an authenticated browser session.

    Args:
        browser: A started :class:`~humble_steam_key_redeemer.humble.HumbleBrowser`.
    """

    def __init__(self, browser: HumbleBrowser, timeout_ms: int = 30_000) -> None:
        self._browser = browser
        self._timeout_ms = timeout_ms

    def is_logged_in(self) -> bool:
        """Report whether the session is signed in to Humble.

        Returns:
            ``True`` when the library page loads without redirecting.
        """
        self._browser.goto(HUMBLE_LIBRARY_PAGE)
        return bool(self._browser.evaluate(_IS_LOGGED_IN))

    def order_keys(self) -> list[str]:
        """List the gamekeys of every order on the account.

        Returns:
            Humble order identifiers.

        Raises:
            HumbleAPIError: If the order list cannot be read.
        """
        try:
            keys = self._browser.evaluate(_FETCH_ORDER_KEYS)
        except Exception as exc:
            raise HumbleAPIError(f"Could not list Humble orders: {exc}") from exc
        return [str(key) for key in keys or []]

    def order_details(self, gamekeys: list[str] | None = None) -> list[dict[str, Any]]:
        """Fetch full order details.

        Args:
            gamekeys: Specific orders to fetch. Defaults to every order.

        Returns:
            Raw order payloads as returned by Humble.

        Raises:
            HumbleAPIError: If the details cannot be read.
        """
        keys = list(gamekeys) if gamekeys is not None else self.order_keys()
        details: list[dict[str, Any]] = []
        for start in range(0, len(keys), _ORDER_BATCH_SIZE):
            batch = keys[start : start + _ORDER_BATCH_SIZE]
            try:
                details.extend(self._browser.evaluate(_FETCH_ORDER_DETAILS, batch) or [])
            except Exception as exc:
                raise HumbleAPIError(f"Could not read Humble order details: {exc}") from exc
        return details

    def post(self, url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
        """Send an authenticated form POST from within the page.

        Args:
            url: Target URL.
            payload: Form fields.

        Returns:
            The HTTP status and decoded JSON body, if any.
        """
        result = self._browser.evaluate(
            _POST_FORM,
            {
                "url": url,
                "payload": payload,
                "csrf": self._browser.cookie("csrf_cookie") or "",
                "timeoutMs": self._timeout_ms,
            },
        )
        return int(result["status"]), result["body"]

    def reveal_key(self, record: KeyRecord) -> str | None:
        """Reveal a key on Humble so Steam can redeem it.

        Revealing is irreversible: it forfeits the ability to generate a gift
        link for that entry, which is why callers must confirm first.

        Args:
            record: The key to reveal.

        Returns:
            The revealed key value, or ``None`` if Humble declined.

        Raises:
            HumbleAPIError: If Humble reports an error.
        """
        status, body = self.post(
            HUMBLE_REDEEM_API,
            {
                "keytype": record.machine_name,
                "key": record.gamekey,
                "keyindex": str(record.key_index if record.key_index is not None else 0),
            },
        )
        if status != _HTTP_OK or body is None:
            raise HumbleAPIError(f"Humble returned HTTP {status} revealing {record.human_name}")
        if body.get("error_msg"):
            raise HumbleAPIError(str(body["error_msg"]))
        if not body.get("success"):
            raise HumbleAPIError(f"Humble declined to reveal {record.human_name}")

        value = body.get("key")
        return str(value) if isinstance(value, str) and value else None


def iter_tpkds(order: Any) -> list[dict[str, Any]]:
    """Yield every key entry nested anywhere inside an order payload.

    Humble nests key entries under several differently-named keys depending on
    the bundle's age and type, so the payload is walked rather than indexed.

    Args:
        order: A decoded Humble order payload.

    Returns:
        Every mapping that looks like a key entry.
    """
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if "machine_name" in node and "human_name" in node:
                found.append(node)
            for value in node.values():
                walk(value)

    walk(order)
    return found


def _as_app_id(value: Any) -> int | None:
    """Coerce Humble's steam_app_id to an int, tolerating strings and nulls.

    Args:
        value: The raw field value.

    Returns:
        The app id, or ``None`` when absent or non-numeric.
    """
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    text = str(value)
    return int(text) if text.isdigit() else None


def to_key_records(orders: list[dict[str, Any]]) -> list[KeyRecord]:
    """Convert raw Humble order payloads into key records.

    Args:
        orders: Decoded order payloads.

    Returns:
        Key records, deduplicated on Humble's identifiers.
    """
    records: dict[tuple[str, str], KeyRecord] = {}

    for order in orders:
        gamekey = str(order.get("gamekey", ""))
        for entry in iter_tpkds(order):
            machine_name = str(entry.get("machine_name", ""))
            if not machine_name:
                continue

            raw_value = entry.get("redeemed_key_val")
            # A multi-key entry reports a list. Each code is a separate
            # redeemable product, so each becomes its own record rather than
            # all but the first being discarded.
            if isinstance(raw_value, list):
                key_values: list[str | None] = [str(item) for item in raw_value if item] or [None]
            elif isinstance(raw_value, str) and raw_value:
                key_values = [raw_value]
            else:
                key_values = [None]

            app_id = entry.get("steam_app_id")
            for offset, key_value in enumerate(key_values):
                # Multi-key entries share a machine_name, so the suffix keeps
                # each code a distinct row rather than overwriting the last.
                name = machine_name if offset == 0 else f"{machine_name}#{offset}"
                record = KeyRecord(
                    gamekey=str(entry.get("gamekey") or gamekey),
                    machine_name=name,
                    human_name=str(entry.get("human_name", machine_name)),
                    key_type=str(entry.get("key_type") or "").lower() or None,
                    steam_app_id=_as_app_id(app_id),
                    redeemed_key_val=key_value,
                    key_index=entry.get("keyindex"),
                    is_gift=bool(entry.get("is_gift")),
                    is_expired=bool(entry.get("is_expired")),
                    state=KeyState.REVEALED if key_value else KeyState.UNREVEALED,
                )
                records[(record.gamekey, record.machine_name)] = record

    return list(records.values())


__all__ = [
    "HUMBLE_ORDERS_API",
    "HUMBLE_ORDER_DETAILS_API",
    "HUMBLE_REDEEM_API",
    "HumbleAPIError",
    "HumbleClient",
    "iter_tpkds",
    "to_key_records",
]
