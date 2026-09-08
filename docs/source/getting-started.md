# Getting started

## Requirements

- Python 3.11 or newer
- A Humble Bundle account and a Steam account
- One Playwright browser (installed in the second step below)

## Install

```bash
pip install humble-steam-key-redeemer
playwright install chromium
```

The second command downloads a browser Playwright manages itself. There is no
separate webdriver to install or keep version-matched with your system browser.

:::{tip}
Prefer an isolated install for a command-line tool:

```bash
uv tool install humble-steam-key-redeemer
uv tool run --from humble-steam-key-redeemer playwright install chromium
```
:::

## First run

### 1. Sign in to Humble

```bash
hskr login
```

A browser window opens on Humble's login page. Complete the sign-in there,
including Humble Guard or two-factor if your account uses them, then return to
the terminal and press Enter.

Your Humble password goes into Humble's own form. The tool never reads it, and
only the resulting session is saved.

### 2. Import your library

```bash
hskr sync
```

This reads your orders and records every key in a local database. Nothing is
revealed and nothing is redeemed.

```bash
hskr status
```

### 3. Preview

```bash
hskr redeem --dry-run
```

You are prompted for your Steam credentials, because ownership cannot be
checked without signing in. Nothing is redeemed. The output lists what would be
attempted, what would be skipped, and any matches the tool was not confident
about.

Review the uncertain matches. Each one is a game the tool believes you already
own but is not sure about; if it is wrong, it is skipping a key you could have
redeemed.

### 4. Redeem

```bash
hskr redeem
```

Add `--reveal` to also reveal keys Humble has not released yet.

:::{warning}
`--reveal` is irreversible. Revealing a key forfeits your ability to turn it
into a gift link.
:::

## Where your data lives

Everything is stored under one directory:

| Platform | Location |
| --- | --- |
| Linux / BSD | `~/.local/state/humble-steam-key-redeemer/` |
| macOS | `~/.local/state/humble-steam-key-redeemer/` |
| Windows | `%APPDATA%\humble-steam-key-redeemer\` |

It holds `redeemer.db` plus the saved Humble and Steam sessions. The directory
is created `0700` and the files `0600`, because the sessions are bearer
credentials — a copied Steam session bypasses Steam Guard.

Override it with `--state-dir` or `HSKR_STATE_DIR`.

To sign out and delete both sessions:

```bash
hskr logout
```
