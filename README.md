# entsoe-quickstart

A **single file, zero dependencies** Python client for the ENTSO-E Transparency
Platform. Copy `entsoe_quickstart.py` into your project and you are done.

```python
from entsoe_quickstart import Entsoe

api = Entsoe("your-security-token")
prices = api.day_ahead_prices("10Y1001A1001A82H")   # Germany–Luxembourg

for t, price in sorted(prices.items())[:4]:
    print(f"{t:%H:%M} UTC  {price:7.2f} EUR/MWh")
```

```
00:00 UTC   152.31 EUR/MWh
00:15 UTC   148.90 EUR/MWh
00:30 UTC   145.02 EUR/MWh
00:45 UTC   141.77 EUR/MWh
```

Or straight from the shell:

```bash
export ENTSOE_TOKEN=...
python3 entsoe_quickstart.py 10YCZ-CEPS-----N
```

## Why another one

The established libraries pull in pandas and a dependency tree, which is the
right trade when you are doing analysis and the wrong one when you want a
scheduled job to fetch prices and write them to a database. This is standard
library only: `urllib` and `ElementTree`.

It deliberately does not cover every document type. `get()` and `series()` are
public, so anything not wrapped is still one line:

```python
# A80 — generation unit outages, the source of price spikes
root = api.get(documentType="A80", biddingZone_Domain="10YCZ-CEPS-----N",
               periodStart="202601010000", periodEnd="202601310000")
```

> ### Read this first
>
> ENTSO-E omits repeated intervals instead of sending them. A French day came
> back with **85 of 96 quarter hours** and a daily average **11 % too high**,
> with no error anywhere. It had removed 10.8 % of our own published dataset
> before we noticed.
>
> **[curveType A03: the gap that eats 10 % of your prices](docs/curvetype-a03.md)**
> — what it is, the second trap in the same response, and
> [a 90-line script](docs/check_gaps.py) that tells you in one command whether
> your own parser has it.
>
> ### And this, if you are building features for a model
>
> No document on the platform says when it was published, only what it is
> about. We measured it: the imbalance price is out **under 3 minutes** after
> the quarter ends, actual load arrives in hourly blocks, and a **forced outage
> reaches `A80` a median of 8 minutes _after_ the unit is already down**.
>
> **[When ENTSO-E data actually arrives](docs/publication-delay.md)** — measured
> on 2 900 outage messages across 52 weeks, with
> [a script](docs/check_delay.py) that runs the same probe on your zone.

## What it handles that a naive script does not

- **Compressed curves (`curveType` A03).** When consecutive intervals clear at
  the same price, ENTSO-E sends the first one and omits the rest — the value
  holds until the next `position`. Read the points one by one and those
  intervals vanish without a trace. A French day comes back with 85 of 96
  quarter-hours, the holes sit in the cheap midday solar block, and the daily
  average lands 11 % too high. Nothing in the response says anything is
  missing, which is what makes it the most common mistake with this API.
- **Several series in one response.** Day-ahead (`contract_MarketAgreement.type`
  A01) and intraday auctions (A07) arrive together, and since the 15-minute MTU
  go-live the 60-minute and 15-minute publications do too, separated only by
  `classificationSequence_AttributeInstanceComponent.position`. Merge them into
  one dict and the last one silently overwrites the others. Spain returns six
  such series for a single day.
- **Variable resolution.** Resolution is read per `Period`, not assumed. The
  continental day-ahead auction moved to 15-minute products in 2025, Great
  Britain settles in half-hours, and some documents are daily. Code that
  assumes 24 hourly points per day mis-aligns silently — the timestamps look
  plausible and the values are wrong.
- **Multi-day responses.** The platform returns whole delivery days that
  overlap your window, so asking for "today" often yields two days. You get a
  dict keyed by UTC datetime; filter it yourself and you will not double-count.
- **Errors that are not HTTP errors.** A bad zone code or an empty window comes
  back as an `Acknowledgement_MarketDocument` — sometimes with HTTP 200. This
  raises `EntsoeError` carrying the platform's own reason text:

  ```
  EntsoeError: [999] No matching data found for Data item ENERGY_PRICES
  [12.1.D] (NESMYSL, NESMYSL) and interval 2026-09-15T00:00:00Z/...
  ```

- **Prices and quantities in one path.** Price documents carry
  `price.amount`, volume documents carry `quantity`. `series()` takes
  whichever is present.

## Covered out of the box

| method | document | what you get |
|---|---|---|
| `day_ahead_prices(zone)` | A44 | auction results, EUR/MWh |
| `load(zone, actual=True)` | A65 | actual load, or the day-ahead forecast |
| `wind_solar_forecast(zone, intraday=False)` | A69 | wind and solar forecast; `intraday=True` is the fresher A18 update |
| `generation(zone)` | A75 | actual generation per production type |

All take optional `start` and `end` — `datetime` objects, or the API's own
`yyyyMMddHHmm` strings. Default is today, UTC.

## Getting a token

1. Register at [transparency.entsoe.eu](https://transparency.entsoe.eu).
2. E-mail `transparency@entsoe.eu`, subject **"Restful API access"**, with the
   address you registered. The token arrives within a few days.

There is no self-service button; the e-mail step is mandatory.

## Limits worth knowing

- Roughly **400 requests per minute**; over that you get HTTP 429. Fetch by
  month rather than by day.
- Some document types cap the period length. An empty response is far more
  often too wide a window than a broken query — shorten the interval before you
  start debugging anything else.
- **Forecasts are versioned.** The API returns the current version, not what
  was published at the time. If you are building features for a model, using
  today's forecast for a past timestamp is look-ahead bias.
- Timestamps are UTC. Bidding zones live in local time, and the two disagree
  twice a year.

## Bidding zone codes

45 of them, as CSV and JSON, in
[whipeeer-creator/eic-codes](https://github.com/whipeeer-creator/eic-codes).

## Licence

[MIT](LICENSE).

## Related

- [A practical guide to the ENTSO-E API](https://progrunners.com/entso-e-api/) —
  the longer version of this README: document types, resolutions, publication
  delays and the undocumented errors
- [Live European prices](https://progrunners.com/european-electricity-prices/) —
  today's numbers for 38 zones, with a national page per market:
  [Spain](https://progrunners.com/es/precio-luz-hoy/) ·
  [Germany](https://progrunners.com/de/strompreis-boerse/) ·
  [Austria](https://progrunners.com/at/strompreis-oesterreich/) ·
  [Estonia](https://progrunners.com/et/elektri-hind/) ·
  [Finland](https://progrunners.com/fi/sahkon-hinta/) ·
  [Sweden](https://progrunners.com/sv/elpriser-idag/) ·
  [Norway](https://progrunners.com/no/strompriser-i-dag/) ·
  [Denmark](https://progrunners.com/da/elpriser-i-dag/) ·
  [Lithuania](https://progrunners.com/lt/elektros-kaina/) ·
  [Latvia](https://progrunners.com/lv/elektribas-cena/) ·
  [Netherlands](https://progrunners.com/nl/stroomprijs/) ·
  [Poland](https://progrunners.com/pl/ceny-pradu/) ·
  [France](https://progrunners.com/fr/prix-electricite/) ·
  [Italy](https://progrunners.com/it/prezzi-zonali/) ·
  [Slovenia](https://progrunners.com/sl/cena-elektrike/) ·
  [Czechia](https://progrunners.com/cs/spotova-cena-elektriny/)

Maintained by [progrunners](https://progrunners.com/open-source/) — we build
trading dashboards and market data pipelines for European power markets, and
publish the parts that are useful on their own.

**All of it in one place:** [progrunners.com/open-source](https://progrunners.com/open-source/)
— six repositories, what each one is for, and the one mistake worth reading
about before you trust any price series, ours included.
