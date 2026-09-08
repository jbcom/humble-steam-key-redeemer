# humble-steam-key-redeemer

Redeem Humble Bundle keys on Steam, skipping the games your account already owns.

The skipping is the point. Steam allows roughly **50 successful activations per
hour, but only about 10 failed ones** — and a key for a game you already own
counts as a *failure*. A large Humble library redeemed blindly stalls within
minutes, having spent its whole budget on games you already had. This tool
checks ownership first, so the attempts it makes are the ones that can succeed.

## Install

```bash
pip install humble-steam-key-redeemer
playwright install chromium
```

## Use

```bash
hskr login              # sign in to Humble in a browser window
hskr sync               # import your library
hskr redeem --dry-run   # see what would happen
hskr redeem             # redeem for real
```

Every command takes flags as well as prompts, so runs can be scripted:

```bash
hskr redeem --limit 20 --yes
hskr export library.csv --steam-only
```

> [!WARNING]
> Revealing a Humble key forfeits your ability to generate a gift link for it,
> permanently. The tool never reveals anything unless you pass `--reveal`, and
> even then only for keys it is about to redeem.

## How it works

**Humble** publishes no API for library access, so that half drives a real
browser through [Playwright](https://playwright.dev/python/) and issues
Humble's own requests from inside the authenticated page. Your Humble password
goes into Humble's own login form — this tool never sees or stores it.

**Steam**'s storefront APIs are plain HTTPS, so that half is a pure HTTP
client: the [vendor-fabric](https://github.com/jbcom/vendor-fabric) Steam
connector, which implements Steam's current `IAuthenticationService` login flow
directly.

**Deciding what to redeem** is fuzzy, because Humble and Steam spell titles
differently — "The Witcher 3: Wild Hunt" against "The Witcher 3 Wild Hunt",
"Game GOTY" against "Game: Game of the Year Edition". Humble's own Steam app id
wins when present; otherwise titles are compared, and matches the tool is not
confident about are shown to you rather than silently skipped.

## Where your data lives

One directory holds the database and your saved sessions:

| Platform | Location |
| --- | --- |
| Linux / macOS | `~/.local/state/humble-steam-key-redeemer/` |
| Windows | `%APPDATA%\humble-steam-key-redeemer\` |

Sessions are bearer credentials — a copied Steam session bypasses Steam Guard —
so the directory is created `0700` and the files `0600`. Override the location
with `--state-dir` or `HSKR_STATE_DIR`, and clear it with `hskr logout`.

## Documentation

Full documentation, including configuration, design notes, and the API
reference: <https://jbcom.github.io/humble-steam-key-redeemer/>

## Development

```bash
uv sync
tox -e lint,typecheck        # ruff + mypy strict
tox -e py311,py312,py313,py314
tox -e docs                  # warnings are errors
```

## About this fork

This is a substantially rewritten fork of
[FailSpy/humble-steam-key-redeemer](https://github.com/FailSpy/humble-steam-key-redeemer).
The original was a single script for its author's own use; this version is a
packaged, tested project. The notable changes:

- **Playwright instead of Selenium.** No separate webdriver to install, real
  timeouts, and — because `page.evaluate` passes arguments as data rather than
  interpolating them into script text — script injection through a title or
  cookie value becomes unrepresentable rather than merely unlikely.
- **Steam auth is owned, not vendored from an unpinned fork.** The original
  depended on a personal fork of the `steam` library at `@master`, re-installed
  on every launch, which handled the user's password and 2FA code. Steam's
  login API turned out to be plain JSON, so it is now implemented directly in
  vendor-fabric's Steam connector.
- **SQLite instead of CSV as state.** CSV was both report and database, which
  meant titles containing commas, quotes, or newlines corrupted it, and values
  starting with `=` executed as formulas on open. CSV is now an export only,
  with escaping.
- **A CLI with flags**, so runs can be scripted and previewed with `--dry-run`.
- **Correctness fixes**, including a rate-limit code that made every unexpected
  failure look like a cooldown and retry forever, and a Steam session id read
  from the wrong cookie domain.

## License

The upstream project ships no license file, so no license is asserted here yet.
See [#licensing](https://github.com/jbcom/humble-steam-key-redeemer/issues) —
this needs resolving with the original author before publishing.
