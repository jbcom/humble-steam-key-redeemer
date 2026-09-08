# Security

This tool handles two sets of account credentials and a library of redeemable
keys, so its security properties are part of its contract.

## Credentials

### Your Humble password is never seen by this tool

Signing in happens in Humble's own login form inside the browser window. The
tool does not read the field, does not proxy the request, and does not store
the password. Humble Guard and two-factor prompts are handled by Humble.

Only the resulting browser session is saved.

### Steam credentials are used once

Your Steam account name and password are sent directly to Steam to obtain a
session, and the password is RSA-encrypted with Steam's per-account public key
before transmission — as Steam's own client does. Nothing but the session is
retained.

### Sessions are stored as restricted files

Saved sessions are bearer credentials: a copied Steam session bypasses Steam
Guard entirely. They are therefore written `0600` inside a `0700` directory,
rather than inheriting a permissive umask.

Delete them at any time:

```bash
hskr logout
```

## Untrusted input

Everything Humble returns — titles, gamekeys, payloads — is data from a remote
service, and is handled as data rather than as code.

### Browser scripts take arguments, never interpolation

Requests issued inside the page are JavaScript *function expressions* called
with an argument. The CSRF token, target URL, and payload cross the boundary
over Playwright's structured channel:

```python
browser.evaluate("(gamekeys) => fetchDetails(gamekeys)", gamekeys)
```

No value is ever formatted into script text, so a title or gamekey containing a
quote is inert rather than executable. This is what makes script injection
unrepresentable rather than merely unlikely, and it is the main reason the tool
uses Playwright.

### CSV export escapes formulas and quotes

Exported reports are opened in spreadsheets, which execute cells beginning with
`=`, `+`, `-`, or `@`. Such values are prefixed so they are displayed as text.
Quoting is handled by Python's `csv` module, so titles containing commas,
quotes, or newlines round-trip instead of corrupting the file.

### No pickle

State is stored in SQLite and JSON. Nothing deserializes Python objects from
disk, so a file dropped into the state directory cannot execute code.

## Network

Every endpoint is HTTPS with certificate verification left on, and every
request carries a timeout, so a stalled connection fails rather than hanging a
long-running job forever.

## Reporting a vulnerability

Please open a security advisory on
[the repository](https://github.com/jbcom/humble-steam-key-redeemer/security/advisories)
rather than a public issue.
