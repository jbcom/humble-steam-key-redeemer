---
myst:
  html_meta:
    description: Redeem Humble Bundle keys on Steam without wasting activation attempts.
---

# humble-steam-key-redeemer

Redeem Humble Bundle keys on Steam, skipping the games your account already
owns.

The skipping is the point. Steam allows roughly **50 successful activations per
hour, but only about 10 failed ones** — and a key for a game you already own
counts as a *failure*. A large Humble library redeemed blindly therefore stalls
within minutes, having spent its entire budget on games you already had. This
tool checks ownership first, so the attempts it makes are the ones that can
succeed.

```{toctree}
:maxdepth: 2
:hidden:

getting-started
usage
browser
design
security
api/index
```

## Install

```bash
pip install humble-steam-key-redeemer
playwright install chromium
```

## Use

```bash
hskr login                 # sign in to Humble in a browser window
hskr sync                  # import your library
hskr redeem --dry-run      # see what would happen
hskr redeem                # redeem for real
```

:::{admonition} Revealing a key is irreversible
:class: warning

Revealing a Humble key forfeits your ability to generate a gift link for it.
The tool never reveals anything unless you pass `--reveal`, and even then only
for keys it is about to redeem.
:::

## How it works

:::{card} Humble
Humble publishes no API for library access, so this half runs a real browser
via Playwright and issues Humble's own requests from inside the authenticated
page. Your Humble password is typed into Humble's own login form — the tool
never sees or stores it.
:::

:::{card} Steam
Steam's storefront APIs are plain HTTPS, so this half is a pure HTTP client:
the [`vendor-fabric`](https://github.com/jbcom/vendor-fabric) Steam connector,
which implements Steam's current `IAuthenticationService` login flow directly.
:::

:::{card} Deciding what to redeem
Humble and Steam spell titles differently ("Game GOTY" versus "Game: Game of
the Year Edition"), so ownership is decided by fuzzy matching, with Humble's
own Steam app id taking precedence when present. Borderline matches are
surfaced rather than silently skipped.
:::

## Indices

- {ref}`genindex`
- {ref}`modindex`
