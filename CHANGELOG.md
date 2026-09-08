# Changelog

## [1.2.0](https://github.com/jbcom/humble-steam-key-redeemer/compare/humble-steam-key-redeemer-v1.1.0...humble-steam-key-redeemer-v1.2.0) (2026-09-08)


### Features

* add hskr recheck, so a wrongly settled key is not lost forever ([fec5b04](https://github.com/jbcom/humble-steam-key-redeemer/commit/fec5b044d2329a7fb534a0b0a6c30091c320605a))
* add hskr recheck, so a wrongly settled key is not lost forever ([746d04f](https://github.com/jbcom/humble-steam-key-redeemer/commit/746d04f83d463b82862bddbfd33359eb5a31d256))


### Bug Fixes

* recheck only ever returns Steam keys ([7fe82ae](https://github.com/jbcom/humble-steam-key-redeemer/commit/7fe82aede07f9a0131bb5874fd6226fbaf903cc4))

## [1.1.0](https://github.com/jbcom/humble-steam-key-redeemer/compare/humble-steam-key-redeemer-v1.0.0...humble-steam-key-redeemer-v1.1.0) (2026-09-08)


### Features

* drive Humble and Steam from the browser you are signed into ([c6b1dcd](https://github.com/jbcom/humble-steam-key-redeemer/commit/c6b1dcd24b4e4bba7652a5286542ba1c88a0c358))
* drive Humble and Steam from the browser you are signed into ([3471bac](https://github.com/jbcom/humble-steam-key-redeemer/commit/3471bacdd152e7b6197b6c24593649c45a144c85))
* drive the extension from the command line, with no popup ([6fc77aa](https://github.com/jbcom/humble-steam-key-redeemer/commit/6fc77aaa2268f8f2af42fd24b36a985acde91228))
* give the extension an icon, and write the store listing ([bd44535](https://github.com/jbcom/humble-steam-key-redeemer/commit/bd44535ef45c03487d1aea0879670113ec20fe37))
* screenshot the popup, and stop a match wrapping into a new entry ([a1f4e79](https://github.com/jbcom/humble-steam-key-redeemer/commit/a1f4e79b1833361b30cbec7ee9c20a05f06dc368))


### Bug Fixes

* a reveal that fails in transit skips one key, not the run ([be71c06](https://github.com/jbcom/humble-steam-key-redeemer/commit/be71c064ce8a049b5e90988e31ca4189ed204b74))
* address review findings on the bridge and login paths ([e201c1f](https://github.com/jbcom/humble-steam-key-redeemer/commit/e201c1fc161d3fe897b2278dd79e0f3bb4ee5fa6))
* claim a queued request atomically ([c6ca0a5](https://github.com/jbcom/humble-steam-key-redeemer/commit/c6ca0a5168499fbcc29058c004b9bed1ce211dde))
* dead Steam endpoint, missed rate limit, and Windows registration ([7be6c36](https://github.com/jbcom/humble-steam-key-redeemer/commit/7be6c3621640d45ff6297ceadb5a12a4f743739b))
* do not let a branch name bypass the only required check ([523aa12](https://github.com/jbcom/humble-steam-key-redeemer/commit/523aa12c6b1e134c036fdbb4b0102141db0dd691))
* do not strand an agent when the browser goes away ([a5ff6eb](https://github.com/jbcom/humble-steam-key-redeemer/commit/a5ff6eb7ca709ee53d69c241d0428fb9340785de))
* judge Humble by host, not by substring ([577a91c](https://github.com/jbcom/humble-steam-key-redeemer/commit/577a91c40fc7b16d1bfc47fe94680d50f76cb715))
* keep product keys out of the page's own JavaScript ([96b7c40](https://github.com/jbcom/humble-steam-key-redeemer/commit/96b7c404c9ddbca8b2c521ab912697fb67641493))
* message limits, a missing verdict, CDP scope, and the popup's redeem ([2131a7e](https://github.com/jbcom/humble-steam-key-redeemer/commit/2131a7e3a8b763fd8f8dc9125a35b1cae87c0800))
* one failed key must not abandon the whole redemption run ([64aa6ca](https://github.com/jbcom/humble-steam-key-redeemer/commit/64aa6ca84d5c9ffd33e050b70b2bac08ea1510d8))
* report the counts that explain why a browser run did nothing ([af769a3](https://github.com/jbcom/humble-steam-key-redeemer/commit/af769a31690eba7790ee6c2769335a7d78a6fbd1))
* revive the native port after the service worker is terminated ([fb84cbe](https://github.com/jbcom/humble-steam-key-redeemer/commit/fb84cbe7fc6a32f63cf4b9cf1c7b7f72c3ba953e))
* run sign-in checks in the page, and drop unused permissions ([6ad50c7](https://github.com/jbcom/humble-steam-key-redeemer/commit/6ad50c7582f130c577c88de6225c4056b0abb35f))
* the manifest test modelled the bug it exists to prevent ([3989390](https://github.com/jbcom/humble-steam-key-redeemer/commit/39893900b22bf411156ba7bde57fdaa8ce63ded4))


### Documentation

* describe driving the browser from the command line ([1e441cb](https://github.com/jbcom/humble-steam-key-redeemer/commit/1e441cb6d4667067146f9a32f1535c54301d9e0e))
* say why the extension id changes, where people hit it ([abb26a2](https://github.com/jbcom/humble-steam-key-redeemer/commit/abb26a24112cab6ab6e959fabb94154290842cf8))
* state the safety guarantees the browser path now carries ([7efcc1a](https://github.com/jbcom/humble-steam-key-redeemer/commit/7efcc1a0ad36b3a6e19586358121d661634b4646))

## [1.0.0](https://github.com/jbcom/humble-steam-key-redeemer/compare/humble-steam-key-redeemer-v1.0.0...humble-steam-key-redeemer-v1.0.0) (2026-09-08)


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
* state the first release version directly ([2f72b51](https://github.com/jbcom/humble-steam-key-redeemer/commit/2f72b51b36de019811aca61c6daac3ccbcdbeae7))
* state the first release version directly ([58e1fde](https://github.com/jbcom/humble-steam-key-redeemer/commit/58e1fdea2b89ad00c09fb66795a2155b985d6a9a))
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
