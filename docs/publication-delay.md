# When ENTSO-E data actually arrives

Every document on the Transparency Platform carries the timestamp the data is
*about*. None of them carries the timestamp the data was *published*. If you are
building features for a model, that second one is the only one that decides
whether a feature is legitimate or look-ahead — and you have to measure it
yourself.

So we did. This page is the measurement.

*Czech bidding zone `10YCZ-CEPS-----N`, probed live on 19 September 2026, plus
2 900 outage messages covering 52 weeks. Method and caveats at the bottom;
[the script](check_delay.py) runs the same probe against your own zone.*

---

## The short version

| Document | What it is | Available after the interval ends | How we know |
|---|---|---|---|
| `A85` | imbalance price | **2.4 and 2.7 minutes** | timed at two quarter-hour boundaries |
| `A86` | imbalance volume | within 5 minutes | upper bound from a probe |
| `A84` | activated balancing energy | 4–14 minutes, in batches | bracketed by two probes |
| `A65` `A16` | actual load | 5–12 minutes, **hourly blocks** | bracketed by two probes |
| `A80` forced | unplanned outage, first message | **median 8 minutes _after_ it starts** | 378 messages over 52 weeks |

The ordering is the part worth keeping. Balancing data — the thing everyone
assumes is slow because it settles late — is the **fastest** series on the
platform. Actual load, the most-used series in every load model, is slower than
the balancing feed and does not arrive smoothly.

Two rows are deliberately missing. Generation per production type (`A75`,
`A74`) gave us an upper bound of 20 minutes for one quarter hour and then left
a later quarter unpublished for more than 30, which means it batches in a way
we have not pinned down. Generation per individual unit (`A73`) was roughly 16
hours stale on a single probe, which is a staleness reading and not a
publication delay. Neither is measured well enough to put a number on, so
neither gets one — [the script](check_delay.py) will tell you what they look
like on your zone today.

## Why "delay" is the wrong word

A single probe tells you how stale the newest data is, not how long it took to
publish. Those differ by up to one publication cycle, and the gap is where the
mistakes live.

Actual load makes this concrete. Two probes eight minutes apart:

```
13:04 UTC   A65 actual   newest interval ends 12:00Z    64 minutes stale
13:12 UTC   A65 actual   newest interval ends 13:00Z    12 minutes stale
```

Nothing about the platform changed between those two moments except that the
hour turned over. Load arrives in **hourly blocks**, so its staleness sawtooths
between about 5 and about 65 minutes depending on when you ask. Quote "the
publication delay of actual load" as one number and you are wrong for fifty
minutes out of every sixty.

The honest form is a bracket. The block covering 12:00–13:00 was absent at
13:05 and present at 13:12, so it was published somewhere in that window: **5
to 12 minutes after the hour it describes ended**. Every figure in the table
above is a bracket of that kind, not a point estimate.

For a feature this distinction is not academic. A model deciding at 13:10 for
delivery at 13:15 can have the load figure for the hour to 13:00 — sometimes.
Whether it can depends on a seven-minute window, and a backtest built from
stored history will happily give it to you every time.

## Balancing data is the fast one

This surprised us enough that we watched a quarter-hour boundary directly
rather than trusting a single probe — a probe cannot tell a genuinely short
delay from a batch that happened to land just before you looked, and our first
suspicion was that we had caught an hourly batch at a lucky moment.

We had not. The imbalance price jumped to the next quarter while we watched,
twice, from two independently started polls:

```
13:13:32Z   A85   newest quarter ends 13:00Z
13:17:39Z   A85   newest quarter ends 13:15Z    published 2.7 min after it ended

13:16:43Z   A85   newest quarter ends 13:00Z
13:17:23Z   A85   newest quarter ends 13:15Z    published 2.4 min after it ended
```

Generation per production type, for that same quarter, was still not there
half an hour later. Imbalance volume (`A86`) had the quarter ending 13:00 when
probed at 13:04, so it is within five minutes, but we did not catch it crossing
a boundary and will not claim a tighter figure than we measured.

Activated balancing (`A84`) is the one to be careful with. It looks like a
member of the same fast family and is not: at 13:04 its newest quarter still
ended 12:30, and by 13:13 it had jumped forward two quarters at once. It
arrives in batches within about a quarter of an hour, not point by point within
three minutes. We had it in the same row as `A85` in the first draft of this
page, which was wrong.

If your mental model is "prices first, physical data next, balancing last
because settlement takes months", it is backwards for the near-real-time feed.
Settlement is slow; the *publication* of activation and imbalance is not.

Two practical consequences. First, an imbalance-state feature is usable inside
the next quarter hour, which is normally the horizon people assume is out of
reach. Second, if you are reconciling against a TSO's own feed and the numbers
disagree, the ENTSO-E value is not the stale one and the difference is real
rather than a timing artefact.

## Outages: the message arrives after the event

This is the one we cared about most, because sudden unit outages are what
produce the price spikes that dominate any imbalance P&L, and the standard
advice is to watch `A80` urgent market messages for them.

We pulled every `A80` message for the Czech zone over 52 weeks — 2 900 unique
messages, outage start dates from February 2025 to September 2026 — and
compared each message's `createdDateTime` against the start of the outage it
describes.

| | Planned (`businessType` A53) | Forced (`A54`) |
|---|---|---|
| Messages | 2 522 | 378 |
| Published before the outage starts | 68.6 % | **17.7 %** |
| Median timing | 28 hours **before** | 54 minutes **after** |
| Within 15 min of the start | 69.6 % | 36.0 % |
| Within 60 min of the start | 71.4 % | 50.5 % |

Planned outages behave as you would hope: two thirds are announced, median a
day ahead. Forced outages do not. **Four out of five forced-outage messages are
created after the unit is already down**, and half of them are more than an
hour late.

Restricting to messages that were never revised — where `createdDateTime` is
genuinely the first publication, 183 cases — moves it, but not to where you
would want it:

| Forced outages, first publication only | |
|---|---|
| Published before the outage starts | 35.0 % |
| Median timing | **8 minutes after** |
| Within 15 minutes of the start | 68.3 % |
| Within 60 minutes of the start | 80.3 % |

So the realistic reading: a forced outage is on the platform within a quarter
of an hour about two thirds of the time, and the median message lands eight
minutes into the event. That is fast enough to *react* to a spike and far too
slow to *anticipate* one. Anyone selling you a model that trades ahead of
outage-driven price spikes using `A80` is selling you a backtest.

### The revision trap underneath it

Of the 2 900 messages, **only 980 are at revision 1**. Two thirds have been
revised at least once, one of them six times.

The API serves the current revision and only that one. We checked rather than
assumed: across 736 documents covering 612 distinct `mRID`s, **not one `mRID`
came back in more than a single revision**, and revision numbers run as high as
20. When you download a past outage you get the message as it reads today —
corrected start time, corrected capacity, sometimes withdrawn entirely
(`docStatus` A09) — and its `createdDateTime` is the date of that revision, not
of the original alert. There is no parameter that asks for "the version that
existed at 14:00 on the day", and the earlier versions are not reachable.

This is the same versioning problem the platform has with forecasts, and it is
worse here because nothing flags it. A backtest that reads outage history from
the API is trained on a tidied-up version of events that nobody had at the
time.

**There are two honest options and no third one:** archive the messages
yourself as they are published and backtest against your archive, or treat
outage data as explanatory only. We learned this the expensive way on
forecasts, then found the same shape here.

## Four traps we hit while measuring

**The German domain code depends on the document.** `10Y1001A1001A83F` ("DE")
works for load and generation and returns reason 999 for prices; day-ahead
prices need `10Y1001A1001A82H` (DE-LU). The error text says "no matching data
found", which reads like an empty period rather than a wrong code.

**The intraday wind and solar forecast does not exist everywhere.** `A69` with
`processType=A18` returns data for Germany and reason 999 for Czechia on the
same call. Absence of an intraday update is not a bug to debug; some zones
simply publish only the day-ahead run, and if your feature assumes the fresher
forecast you have silently built a model that only works in some markets.

**`A80` caps at 200 documents per request**, and says so plainly — *"The number
of instances (222) exceeds the allowed maximum (200)"*. A month of a mid-sized
zone exceeds it. Fetch outages weekly, not monthly, and deduplicate on
`mRID` plus `revisionNumber`.

**Balancing documents come back zipped.** `A85`, `A86` and the unavailability
documents return a ZIP archive with one XML per message and no obvious signal
other than the content type. Check for the `PK` magic bytes and unzip.

## How we measured it

Two separate measurements, both reproducible.

**The boundary watch.** Poll one document every 30 seconds across a quarter-hour
boundary and record the moment the newest interval jumps. This is what separates
a genuine short delay from a batch that happened to land just before you looked,
and it is the only way to get a number rather than a bracket.

**The staleness probe.** For each document type, ask for a window spanning
yesterday to tomorrow and find the end of the newest interval that actually
contains a point. Compare against the clock. Repeat at a different minute of
the hour to catch the block boundary. That is [`check_delay.py`](check_delay.py)
— standard library, one request per row:

```
python3 check_delay.py YOUR_TOKEN 10YCZ-CEPS-----N
```

```
10YCZ-CEPS-----N   measured 2026-09-19 13:12 UTC

  document                     newest interval ends         vs now
  ----------------------------------------------------------------
  A44  day-ahead price         2026-09-20 22:00Z         1968 min ahead
  A65  load, actual            2026-09-19 13:00Z           12 min stale
  A65  load, forecast          2026-09-20 22:00Z         1968 min ahead
  A69  wind+solar, D-1         2026-09-20 18:15Z         1743 min ahead
  A69  wind+solar, intraday    —                      no data (reason 999)
  A74  wind+solar, actual      2026-09-19 12:45Z           27 min stale
  A75  generation per type     2026-09-19 12:45Z           27 min stale
  A73  generation per unit     2026-09-18 21:15Z          957 min stale
  A84  activated balancing     2026-09-19 13:00Z           12 min stale
  A85  imbalance price         2026-09-19 13:00Z           12 min stale
  A86  imbalance volume        2026-09-19 13:00Z           12 min stale
```

**The outage timing.** Fetch `A80` for the zone week by week across a year,
deduplicate on `mRID` and `revisionNumber`, and take
`createdDateTime` minus the start of the unavailability. Split by
`businessType`: A53 is planned maintenance, A54 is a forced outage.

Two things in that paragraph are assumptions, so we tested both rather than
trusting them.

*Which field is the start of the outage.* There are three candidates in the
document — `start_DateAndOrTime`, the `Available_Period` time interval, and the
document-level `unavailability_Time_Period` — and reading the wrong one would
shift every number on this page. Across all 2 900 messages they disagree
**zero** times, so the question turns out not to matter here. It might in
another zone; check before you rely on it.

*Whether A54 really means a forced outage.* Rather than take the code list's
word for it, we cross-tabulated `businessType` against the `Reason` each
message carries. A54 is 352-of-378 `B18` *Failure*. A53 is dominated by `B19`
*Maintenance* and `B20` *Outage*. The split does what the name says, confirmed
from the data itself.

### What this does not tell you

- **A snapshot is a snapshot.** These brackets come from one afternoon. A
  platform incident, a market holiday or a different zone can move them. The
  script exists so you can check your own zone on your own day rather than
  trusting a table written by someone else — which is the whole point.
- **`createdDateTime` is the document's creation, not its arrival in your
  system.** Anything between the platform writing the file and your job seeing
  it is yours to measure.
- **The never-revised subset is a subset.** Messages that were never revised
  skew toward short, uncomplicated events. The true first-publication figure
  for the messy ones is unknowable from the API, which is the argument for
  archiving.
- **Resolutions differ by document**, so "the newest interval" means different
  things per row. A 15-minute series and an hourly one that are both "12
  minutes stale" are not equally fresh.

---

## The full guide

This page is the measurement. The rest of how this API behaves — which document
types exist, what the four query parameters do, the errors that arrive as XML
with HTTP 200, why a response can contain two delivery days, and where ENTSO-E
stops being the right source at all — is written up on the site:

**[A practical guide to the ENTSO-E API →](https://progrunners.com/entso-e-api/)**

Also worth your time before you trust a price series:

- [curveType A03: the gap that eats 10 % of your prices](curvetype-a03.md) —
  the platform omits repeated intervals; a French day came back with 85 of 96
  quarter hours and an average 11 % too high
- [`entsoe_quickstart.py`](../entsoe_quickstart.py) — the client, one file, no
  dependencies
- [Live prices for 38 bidding zones](https://progrunners.com/european-electricity-prices/)
  if you want today's numbers rather than the plumbing

Everything we publish openly is listed at
[progrunners.com/open-source](https://progrunners.com/open-source/).

We build market data pipelines and trading dashboards for European power
markets. If you are trying to work out whether a feature in your model is
look-ahead and the publication times are not written down anywhere, that is
exactly the problem we spend our days on — `info@progrunners.com`.
