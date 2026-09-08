"""Browser session management for Humble Bundle.

Humble exposes no public API, so its half of the workflow runs through a real
browser. Playwright is used rather than Selenium for three reasons that matter
here: it bundles its own browser and driver (no separate webdriver to install
or version-match), it has real timeout semantics on every operation, and
:meth:`Page.evaluate` passes arguments over a structured channel instead of
string-formatting them into a script.

That last point is a security property, not a convenience. Building JavaScript
by interpolating values into a template makes any value that can contain a
quote a script-injection vector; passing arguments makes injection
unrepresentable rather than merely unlikely.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

if TYPE_CHECKING:
    from playwright.sync_api import Playwright

    from humble_steam_key_redeemer.settings import Settings


HUMBLE_LOGIN_PAGE = "https://www.humblebundle.com/login"
HUMBLE_LIBRARY_PAGE = "https://www.humblebundle.com/home/library"
HUMBLE_SUBSCRIPTION_PAGE = "https://www.humblebundle.com/subscription/"


class HumbleBrowserError(RuntimeError):
    """Raised when the browser cannot be started or driven."""


class HumbleBrowser:
    """A Playwright browser session scoped to Humble Bundle.

    Args:
        settings: Runtime configuration.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # ------------------------------------------------------------ lifecycle

    def start(self) -> Self:
        """Start the browser session, restoring a saved session when present.

        When ``cdp_endpoint`` is configured, attaches to that already-running
        browser instead of launching a new one. That lets the tool reuse a
        browser a person is already signed into — including one an agent is
        driving — rather than requiring a separate sign-in in an isolated
        profile.

        Returns:
            This browser session.

        Raises:
            HumbleBrowserError: If the browser cannot be started or reached.
        """
        self._settings.ensure_state_dir()
        try:
            self._playwright = sync_playwright().start()
            if self._settings.cdp_endpoint:
                self._start_over_cdp()
            else:
                self._start_launched()
        except HumbleBrowserError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise HumbleBrowserError(
                f"Could not start the {self._settings.browser} browser: {exc}\n"
                "If this is a first run, install the browser with:\n"
                "    playwright install chromium"
            ) from exc
        return self

    def _start_launched(self) -> None:
        """Launch a browser Playwright manages itself."""
        if self._playwright is None:  # pragma: no cover - start() sets this
            raise HumbleBrowserError("Playwright is not running")
        launcher = getattr(self._playwright, self._settings.browser)
        self._browser = launcher.launch(headless=self._settings.headless)
        self._context = self._browser.new_context(
            storage_state=self._storage_state(),
            locale=self._settings.locale,
        )
        self._context.set_default_timeout(self._settings.browser_timeout_ms)
        self._page = self._context.new_page()

    def _start_over_cdp(self) -> None:
        """Attach to a browser already running with remote debugging enabled.

        The existing browser owns its profile and cookies, so no saved session
        is injected: whatever it is signed into is what the tool sees.

        Raises:
            HumbleBrowserError: If the endpoint cannot be reached.
        """
        if self._playwright is None:  # pragma: no cover - start() sets this
            raise HumbleBrowserError("Playwright is not running")
        endpoint = self._settings.cdp_endpoint or ""
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(endpoint)
        except Exception as exc:
            raise HumbleBrowserError(
                f"Could not attach to a browser at {endpoint}: {exc}\n"
                "Start one with remote debugging enabled, for example:\n"
                "    /Applications/Google Chrome.app/Contents/MacOS/Google Chrome \\\n"
                "      --remote-debugging-port=9222 --user-data-dir=/tmp/hskr-chrome"
            ) from exc

        # An attached browser already has a context; reuse it so its cookies
        # apply, rather than creating an isolated one.
        self._context = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
        self._context.set_default_timeout(self._settings.browser_timeout_ms)
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

    @property
    def is_attached(self) -> bool:
        """Whether this session attached to an existing browser."""
        return bool(self._settings.cdp_endpoint)

    def _storage_state(self) -> str | None:
        """Return the saved session path, when one exists and is usable."""
        path = self._settings.humble_session_path
        if not path.exists():
            return None
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A corrupt session file should mean "sign in again", not a crash.
            return None
        return str(path)

    def save_session(self) -> Path:
        """Persist the browser session for reuse.

        Session cookies are bearer credentials, so the file is written with
        owner-only permissions.

        Returns:
            The path written.
        """
        path = self._settings.humble_session_path
        self._require_context().storage_state(path=str(path))
        path.chmod(0o600)
        return path

    def clear_session(self) -> None:
        """Delete any saved Humble session."""
        self._settings.humble_session_path.unlink(missing_ok=True)

    def close(self) -> None:
        """Close the browser and release Playwright resources."""
        # Teardown also runs on error paths; a failure to release one resource
        # must not mask the exception that triggered it. Innermost first.
        if self._context is not None:
            with contextlib.suppress(Exception):
                self._context.close()
        # Only close a browser this session launched. Closing one we merely
        # attached to would shut down the user's own browser.
        if self._browser is not None and not self._settings.cdp_endpoint:
            with contextlib.suppress(Exception):
                self._browser.close()
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                self._playwright.stop()
        self._context = self._browser = self._playwright = self._page = None

    def __enter__(self) -> Self:
        """Start the browser on context entry."""
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the browser on context exit."""
        self.close()

    # --------------------------------------------------------------- access

    @property
    def page(self) -> Page:
        """The active page."""
        return self._require_page()

    def _require_page(self) -> Page:
        """Return the active page or raise."""
        if self._page is None:
            raise HumbleBrowserError("Browser is not started; call start() first")
        return self._page

    def _require_context(self) -> BrowserContext:
        """Return the active context or raise."""
        if self._context is None:
            raise HumbleBrowserError("Browser is not started; call start() first")
        return self._context

    def goto(self, url: str) -> None:
        """Navigate to a URL.

        Args:
            url: Destination URL.
        """
        self._require_page().goto(url, wait_until="domcontentloaded")

    def evaluate(self, script: str, argument: Any = None) -> Any:
        """Run JavaScript in the page with an argument passed as data.

        The argument crosses into the page over Playwright's structured
        channel, so its contents are never parsed as code regardless of what
        characters it contains.

        Args:
            script: A JavaScript function expression taking one argument.
            argument: Value passed to that function.

        Returns:
            The script's return value.
        """
        return self._require_page().evaluate(script, argument)

    def cookie(self, name: str) -> str | None:
        """Return the value of a cookie by name.

        Args:
            name: Cookie name.

        Returns:
            The cookie value, or ``None`` when absent.
        """
        for entry in self._require_context().cookies():
            if entry.get("name") == name:
                value = entry.get("value")
                return str(value) if value is not None else None
        return None


__all__ = [
    "HUMBLE_LIBRARY_PAGE",
    "HUMBLE_LOGIN_PAGE",
    "HUMBLE_SUBSCRIPTION_PAGE",
    "HumbleBrowser",
    "HumbleBrowserError",
]
