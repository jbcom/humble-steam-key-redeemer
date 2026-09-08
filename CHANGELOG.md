# Changelog

## [2.0.0](https://github.com/jbcom/humble-steam-key-redeemer/compare/humble-steam-key-redeemer-v1.0.0...humble-steam-key-redeemer-v2.0.0) (2026-09-08)


### ⚠ BREAKING CHANGES

* the entry point is now the `hskr` command rather than running humblesteamkeysredeemer.py directly. Existing .humblecookies and .steamcookies files are not migrated; sign in once with `hskr login`.

### Features

* rewrite as a packaged project on Playwright, SQLite, and Typer ([e2ac664](https://github.com/jbcom/humble-steam-key-redeemer/commit/e2ac664657de78a9588f27e17733d3c44743679d))


### Bug Fixes

* 35 ([12cd58e](https://github.com/jbcom/humble-steam-key-redeemer/commit/12cd58ec38faad6eab93468bcbcb731a8f036441))
* address review findings in reveal, matching, and planning ([ea2999e](https://github.com/jbcom/humble-steam-key-redeemer/commit/ea2999e3a4ae3c131690a611726ace07051423f2))
* anchor release-please on the corrected 1.0.0 baseline ([3e7f4c6](https://github.com/jbcom/humble-steam-key-redeemer/commit/3e7f4c6113aee545c3975da5db5ebab5fac0df13))
* anchor release-please on the corrected 1.0.0 baseline ([4a34cb1](https://github.com/jbcom/humble-steam-key-redeemer/commit/4a34cb14ac440bb07e3d16b004fadff1b037e99b))
* correct the first release to 1.0.0 ([6a8308f](https://github.com/jbcom/humble-steam-key-redeemer/commit/6a8308ff311a5bcb5b7851465ee22bab5afe23d6))
* correct the first release to 1.0.0 ([d4db51a](https://github.com/jbcom/humble-steam-key-redeemer/commit/d4db51a7ea83acf47aa4e03096f639ec5e3afd18))
* guard non-key values, account mismatch, and export permissions ([448e6d8](https://github.com/jbcom/humble-steam-key-redeemer/commit/448e6d8c2d756099b9feee7d04507bfdb7788eb8))
* protect session credentials and interrupted activations ([574908d](https://github.com/jbcom/humble-steam-key-redeemer/commit/574908d204d0c23b9d01f11172936dbcaa77da05))
* wire --reveal through to the redemption engine ([578642e](https://github.com/jbcom/humble-steam-key-redeemer/commit/578642ed5ba4de543d479de91500c0d2a2b734fa))


### Documentation

* add MIT license ([ded6bd8](https://github.com/jbcom/humble-steam-key-redeemer/commit/ded6bd8778c245a8263b0fb53e7e6ea687f1bf82))
* drop the unused static path ([35640c0](https://github.com/jbcom/humble-steam-key-redeemer/commit/35640c0c21f9f668a3cac5c0503566d67fbb76a6))
* point the documentation links at the live domain ([2a25777](https://github.com/jbcom/humble-steam-key-redeemer/commit/2a25777d48a87a4d6bce4f3a94357f289dd2e8bb))


### Build System

* depend on the released vendor-fabric 2.5 ([b35bddb](https://github.com/jbcom/humble-steam-key-redeemer/commit/b35bddb72c89a7d520678138781c351f6050d1c7))
* resolve vendor-fabric from source until 2.5 is released ([d4cb2a5](https://github.com/jbcom/humble-steam-key-redeemer/commit/d4cb2a53b3082a8b1fd7a56f1a365c485286242f))

## 1.0.0 (2026-09-08)

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
- Gift links and other non-key values are never sent to Steam, so they cannot
  consume the scarce failed-activation budget.
- Nothing is deserialized from disk with `pickle`.
