# Design

The principles this tool is built on, and why each one exists.

## Pillars

### 1. A failed activation is the scarce resource

Steam permits roughly 50 successful activations per hour but only about **10
failures**, and a key for an already-owned game counts as a failure. Every
design decision follows from that asymmetry:

- Ownership is checked before anything is redeemed.
- Duplicate titles within a run are collapsed.
- Keys that already received a verdict are never retried.
- A rate limit stops the run instead of deepening the cooldown.

### 2. Irreversible actions require an explicit request

Revealing a Humble key forfeits the gift link for it, permanently. Revealing
therefore never happens implicitly: it needs `--reveal`, and even then only for
keys about to be redeemed.

### 3. Data from a vendor is untrusted input

Titles, gamekeys, and payloads come from a remote service. They are treated as
data everywhere — passed as arguments into the browser, escaped on the way into
a CSV, and never interpolated into code.

### 4. Credentials stay where they belong

The Humble password is typed into Humble's own login form; the tool never sees
it. Steam credentials are used once to obtain a session. Sessions live in files
created `0600` inside a `0700` directory.

### 5. State is a database, not a spreadsheet

Redemption history determines whether a key is worth attempting, so it is kept
in SQLite. CSV is a *report* produced on request, not the source of truth.

### 6. The core is testable without credentials

Matching, planning, and storage know nothing about browsers or networks, so
they are tested directly. Steam is reached through a `SteamGateway` protocol
that a fake satisfies.

## Architecture

```text
                    ┌──────────────┐
                    │  Typer CLI   │
                    └──┬────────┬──┘
                       │        │
         ┌─────────────┘        └──────────────┐
         ▼                                      ▼
┌────────────────────┐               ┌────────────────────┐
│ RedemptionEngine   │               │   HumbleClient     │
│  · plan()          │               │  · order_details() │
│  · redeem()        │               │  · reveal_key()    │
└──┬───────┬──────┬──┘               └─────────┬──────────┘
   │       │      │                            │
   ▼       ▼      ▼                            ▼
┌──────┐ ┌────────────────┐          ┌────────────────────┐
│SQLite│ │OwnershipMatcher│          │ Playwright browser │
└──────┘ └────────────────┘          └────────────────────┘
             │
             ▼
   ┌────────────────────┐      ┌──────────────────────────┐
   │   SteamGateway     │─────▶│ vendor-fabric            │
   │   (protocol)       │      │ Steam connector (HTTPS)  │
   └────────────────────┘      └──────────────────────────┘
```

| Package | Responsibility |
| --- | --- |
| `core` | Models, matching, storage, and the redemption engine. No I/O beyond SQLite. |
| `humble` | Browser session and Humble's own API, driven from inside the page. |
| `steam` | Adapter over vendor-fabric's Steam connector, plus session persistence. |
| `cli` | Typer commands and console rendering. |

## Why Playwright rather than Selenium

Three properties, in order of importance:

1. **Arguments are data.** `page.evaluate(fn, arg)` passes values over a
   structured channel. Building a script by string interpolation makes any
   value containing a quote a potential injection; passing arguments makes that
   unrepresentable.
2. **No separate driver.** Playwright ships and manages its own browser, so
   there is no geckodriver or chromedriver to install and keep matched.
3. **Real timeouts.** Every operation has one, so a hung page fails rather than
   blocking forever.

## Why ownership matching is fuzzy

Humble and Steam do not agree on titles. "The Witcher 3: Wild Hunt" appears as
"The Witcher 3 Wild Hunt"; "Game GOTY" as "Game: Game of the Year Edition".
Exact comparison misses most of them.

Matching therefore proceeds in three steps:

1. If Humble reports a Steam app id and you own it, that is decisive.
2. Otherwise, candidates are gathered with a token-set score, which is
   insensitive to word order and extra words.
3. The winner among candidates is chosen with a token-*sort* score, which
   penalizes extra words.

Step 3 exists because a token-set score treats a subset as a perfect match:
"Portal" scores 100 against "Portal 2". Ranking on it alone would attribute a
Portal key to Portal 2. Re-ranking picks the closer title when you own both.

Matches below the confirmation threshold are reported rather than silently
applied, because a wrong skip costs a redeemable key.
