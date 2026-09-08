# Usage

Every command takes flags as well as prompts, so a run can be scripted.

## Commands

### `hskr login`

Opens a browser window on Humble's login page and saves the session once you
have signed in.

### `hskr sync`

Imports your Humble library into the local database. Re-running it updates
existing entries rather than duplicating them, so your redemption history
survives.

```bash
hskr sync --headed     # watch it work
```

### `hskr status`

Prints a breakdown of stored keys by state and how many are still worth
attempting.

### `hskr redeem`

Redeems Steam keys the account does not already own.

| Flag | Effect |
| --- | --- |
| `--dry-run` | Check ownership and print the plan; redeem nothing. |
| `--yes`, `-y` | Skip the confirmation prompt. |
| `--reveal` | Reveal unrevealed Humble keys. Irreversible. |
| `--limit N` | Attempt at most `N` keys. |
| `--steam-account NAME` | Supply the Steam account name non-interactively. |

```bash
hskr redeem --dry-run
hskr redeem --limit 20 --yes
hskr redeem --reveal --yes
```

### `hskr export`

Writes the stored library to a CSV report.

```bash
hskr export library.csv
hskr export steam-only.csv --steam-only
```

Values that a spreadsheet would treat as formulas are escaped, and titles
containing commas, quotes, or newlines are quoted correctly.

### `hskr logout`

Deletes the saved Humble and Steam sessions.

## Configuration

Settings resolve from command-line flags, then `HSKR_`-prefixed environment
variables, then a `.env` file, then the defaults.

| Variable | Default | Meaning |
| --- | --- | --- |
| `HSKR_STATE_DIR` | platform state dir | Where the database and sessions live. |
| `HSKR_MATCH_THRESHOLD` | `70` | Score above which a title counts as owned. |
| `HSKR_CONFIRM_THRESHOLD` | `95` | Score at or above which no review is needed. |
| `HSKR_HEADLESS` | `true` | Run the browser without a window. |
| `HSKR_BROWSER` | `chromium` | `chromium`, `firefox`, or `webkit`. |
| `HSKR_BROWSER_TIMEOUT_MS` | `60000` | Per-operation browser timeout. |
| `HSKR_REQUEST_TIMEOUT` | `30.0` | HTTP timeout in seconds. |
| `HSKR_LOCALE` | `en-US` | Browser locale. |

### Tuning the match thresholds

Lowering `HSKR_MATCH_THRESHOLD` skips more games as already-owned; raising it
attempts more. Because a wrong skip wastes a redeemable key and a wrong attempt
wastes one of ten hourly failures, the default is deliberately cautious and
surfaces borderline cases instead of guessing.

```bash
HSKR_MATCH_THRESHOLD=80 hskr redeem --dry-run
```

## Rate limits

Steam permits roughly 50 activations per hour, and only about 10 failures.
Duplicates count as failures.

The tool stops as soon as Steam reports a rate limit, because further attempts
during a cooldown extend it. Rerun about an hour later; keys that were only
rate-limited stay eligible, while keys that got a real verdict are not retried.

A key interrupted mid-activation — the process died after Steam saw the key but
before the result was recorded — is left in the `attempted` state and is *not*
retried automatically, because Steam may well have accepted it and a retry
would spend one of the scarce failures. `hskr status` shows these; check the
game in your Steam library before deciding.

```bash
hskr redeem --yes   # later, to pick up where it stopped
```
