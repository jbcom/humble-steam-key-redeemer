# Chrome Web Store listing

Everything the Developer Dashboard asks for, kept next to the code so it does
not have to be reconstructed at submission time.

**Last updated:** 2026-09-08 · **Extension version:** 1.0.0 · **Status:** not yet submitted

## Identity

| Field | Value |
| --- | --- |
| Name | Humble Steam Key Redeemer |
| Category | Productivity |
| Language | English (United States) |
| Visibility | Public |

**Extension ID:** assigned at publication. It replaces whatever id an unpacked
load derived from the directory path, so `hskr bridge --extension-id <ID>` has
to be re-run once against the published id, and the docs need updating with it.

## Descriptions

**Summary (132 characters max):**

> Redeem your Humble Bundle keys on Steam without wasting activation attempts on games you already own.

**Full description:**

> Humble Bundle libraries accumulate Steam keys faster than anyone redeems them,
> and redeeming them in bulk does not work: Steam allows roughly 50 successful
> activations an hour but only about 10 failed ones, and a key for a game you
> already own counts as a failure. Work through a large library blindly and it
> stalls within minutes, having spent its whole budget on games you already had.
>
> This extension checks what your Steam account already owns before it activates
> anything, so the attempts it makes are the ones that can succeed.
>
> It works in the tabs you are already signed into. There is no second sign-in,
> no password to hand over, and no separate browser profile that Humble and Steam
> treat as a new device.
>
> What it does:
>
> • Reads your Humble library and finds the Steam keys in it
> • Checks each one against the games your Steam account already has
> • Shows you what it would redeem before it redeems anything
> • Skips duplicates, gift links, and anything that is not a real key
> • Stops on its own when Steam signals a rate limit, rather than deepening it
> • Leaves unrevealed keys alone unless you explicitly ask, because revealing one
>   permanently forfeits your ability to gift it
>
> This extension is the browser half of a free, open-source command-line tool. The
> tool has to be installed separately; the extension does the parts that need your
> browser session, and the tool decides what is worth redeeming.

## Permissions justification

Each of these is asked about individually during review.

| Permission | Justification |
| --- | --- |
| `nativeMessaging` | The extension reports to the `hskr` command-line tool the user installs separately. That tool holds the key database and decides what is worth redeeming; the extension carries out the requests. |
| `scripting` | Humble and Steam requests must run inside their own pages to carry the user's existing session. Running them from the extension's background context does not reliably send those cookies. |
| `tabs` | To find an already-open Humble or Steam tab and act in it, or open one when there is none. |
| `alarms` | Chrome terminates an idle service worker. An alarm restores the connection to the command-line tool so a run started from the terminal is not lost. |
| `https://*.humblebundle.com/*` | Reading the user's own order history and revealing keys they own. |
| `https://store.steampowered.com/*` | Reading which applications the account owns, and activating product keys. |
| `https://steamcommunity.com/*` | Reading the account's own games list for application names, used to match Humble titles against games already owned. |

**Why no remote code:** everything the extension runs ships in the package. It
loads no scripts from any server.

## Privacy and data use

**Data collected: none.** Nothing is transmitted to the developer or to any
third party. The extension talks only to Humble, to Steam, and to the copy of
`hskr` on the user's own machine over Chrome's native messaging, which is local
process I/O rather than a network connection.

The single purpose declaration: *Redeem Humble Bundle product keys on Steam
while skipping games the account already owns.*

Answers to the dashboard's data-use checkboxes:

| Question | Answer |
| --- | --- |
| Personally identifiable information | No |
| Health information | No |
| Financial and payment information | No |
| Authentication information | No — the extension never handles passwords, and uses the session already in the browser |
| Personal communications | No |
| Location | No |
| Web history | No |
| User activity | No |
| Website content | No — page content is read to carry out the user's own requests and is not collected |

All three certifications apply: the data use is disclosed accurately, no data is
sold to third parties, and no data is used for purposes unrelated to the
extension's single purpose.

**Privacy policy URL:** https://jonbogaty.com/humble-steam-key-redeemer/security.html

## Assets still needed

These are the blockers for an actual submission.

- [x] **Icon, 128×128 PNG.** Done — `extension/icons/` carries 16, 32, 48, and
      128px, each drawn at its own size and checked for legibility at 16px.
- [ ] **At least one screenshot, 1280×800 or 640×400.** The popup mid-run is the
      obvious one; a preview result showing what it would skip makes the value
      legible without a paragraph of text.
- [ ] **A developer account.** One-time 5 USD registration fee, which is a
      spending decision rather than something to action here.

## Review risks

Worth pre-empting, because each has rejected extensions before:

- **Broad host permissions.** Three origins, each justified above by a specific
  feature. None is a wildcard beyond Humble's own subdomains.
- **A companion desktop application.** `nativeMessaging` attracts scrutiny.
  The listing should be explicit that the tool is open source, installed
  deliberately by the user, and named in the description.
- **The single purpose rule.** Reading a library, checking ownership, and
  activating keys are one workflow, not three features. Describe them that way.

## Version history

| Version | Date | Notes |
| --- | --- | --- |
| 1.0.0 | unreleased | First listing. Drives Humble and Steam in the user's own tabs; ownership checking, preview, and redemption with explicit opt-in for revealing keys. |
