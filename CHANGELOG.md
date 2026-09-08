# Changelog

## 1.0.0

First release as a packaged project. The predecessor was a single script; this
is an installable, tested tool with a documented command-line interface.

### Features

- `hskr` command with `login`, `sync`, `status`, `redeem`, `export`, and
  `logout`. Every command takes flags as well as prompts, so runs can be
  scripted and previewed with `--dry-run`.
- Ownership is checked against the Steam library before anything is redeemed,
  so activations are not spent on games the account already owns. Steam allows
  roughly 50 activations per hour but only about 10 failures, and a duplicate
  counts as a failure.
- Keys and redemption attempts are kept in SQLite, so a rerun knows what was
  already tried and what verdict Steam gave.
- Humble is driven through Playwright, which bundles its own browser; there is
  no separate webdriver to install. Steam access comes from vendor-fabric's
  Steam connector.

### Security

- Values are passed into the browser as arguments rather than interpolated into
  scripts, so a title or cookie containing a quote cannot become executable.
- Sessions are stored `0600` inside a `0700` state directory, and CSV exports
  containing revealed keys are created `0600`.
- CSV output escapes values a spreadsheet would evaluate as a formula.
- Nothing is deserialized from disk with `pickle`.
