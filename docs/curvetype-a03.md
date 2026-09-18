# curveType A03: the gap that eats 10 % of your prices

ENTSO-E does not send you every interval. When consecutive quarter hours clear
at the same price it sends the first one and drops the rest, and nothing in the
response says so. We found it in our own published dataset, where it had
quietly removed 324 394 rows.

*Measured 18–19 September 2026 against live ENTSO-E responses, 1 725 days of
our own dataset, and energy-charts and OTE as independent references.*

---

## The symptom

You request a day of French day-ahead prices. You get 85 quarter hours instead
of 96. No error, no warning, no flag — the document validates, the timestamps
look plausible, and the prices in it are correct. Compute a daily average and
it comes out at **132.8 EUR/MWh when the real answer is 119.7**. That is 11 %
high, and nothing in the response tells you why.

The missing intervals were not scattered. They sat in one block from 14:00 to
16:15 — the cheap midday solar hours — plus a single quarter at 20:15. Dropping
the cheapest part of the day is what pushed the average up. Had the gap fallen
in the evening peak, the average would have come out too low instead, and you
would be equally unaware.

> **This is not a rare edge case.** On one ordinary day, checked across six
> markets: France 85 of 96 quarter hours, Italy North 91, Spain 95, Poland 95.
> Czechia and Germany were complete — not because they behave differently, but
> because on that day no two consecutive quarter hours happened to clear at the
> same price.

## What curveType A03 actually is

ENTSO-E documents carry a `curveType`. A01 is the ordinary one: every interval
is a point, positions run 1, 2, 3 and so on. A03 is *variable sized block*, and
it is a compression scheme. When a run of consecutive intervals clears at the
same price, only the first interval of the run is sent. Its value holds until
the position of the next point.

So a jump in `position` is not a hole. It is an instruction: repeat the
previous value until here. Read the points one at a time and write them into a
dict keyed by timestamp, and every repeated interval simply never gets written.

```xml
<!-- French day-ahead, 18 September 2026, abbreviated -->
<TimeSeries>
  <curveType>A03</curveType>
  <Period>
    <timeInterval><start>2026-09-17T22:00Z</start>
                  <end>2026-09-18T22:00Z</end></timeInterval>
    <resolution>PT15M</resolution>
    <Point><position>56</position><price.amount>21.05</price.amount></Point>
    <Point><position>67</position><price.amount>34.90</price.amount></Point>
    ...
  </Period>
</TimeSeries>
```

Positions 57 to 66 are not missing data. They are ten quarter hours that all
cleared at 21.05 EUR/MWh. The document says so by omitting them, and it expects
you to know that.

The catch is that the same response will often contain complete runs as well,
so a spot check on a volatile day shows 96 points and you conclude the parser
is fine. It only fails on the days where prices flatten — which are exactly the
days with a lot of solar, and the ones most people are interested in.

## How much it actually removes

We publish [a dataset of European day-ahead prices](https://github.com/whipeeer-creator/european-power-prices)
back to 2022. It was built with the naive parser. When we measured it against
what the documents actually contain:

| | Before | After |
|---|---|---|
| Days with at least one gap | 1 718 of 1 725 | 21 of 1 725 |
| Missing rows | 324 394 | 28 330 |
| Share of the dataset | 10.8 % | 1.0 % |

The 21 days that remain are quarter boundaries of our own fetch window, not
anything ENTSO-E withheld. The 10.8 % was ours, and for months the README
blamed the source for it — *"a missing hour is almost always missing at the
source, not lost here"*. That sentence was wrong, and it is the reason this
document exists.

> **Check your own history before you trust this page.** If you have a stored
> series, count the intervals per delivery day and compare against what the
> resolution implies: 96 for PT15M, 48 for PT30M, 24 for PT60M. A day that is
> short by a few intervals with no DST change in it is this bug, not the market.

## The second trap in the same response

While fixing the first one we found a second, and it is worse because it
produces numbers that look entirely reasonable. A single A44 response can carry
several price series at once, and merging them into one dict lets the last one
silently overwrite the others.

Spain returned six series for one day. Germany returned four. They are told
apart by two fields:

| Field | Value | Meaning |
|---|---|---|
| `contract_MarketAgreement.type` | A01 | day-ahead auction |
| `contract_MarketAgreement.type` | A07 | intraday auction |
| `classificationSequence…position` | 1 | the day-ahead product itself |
| `classificationSequence…position` | 2 | the other product of the same market |

For Spain on 18 September 2026, the day-ahead series averaged 124.8 EUR/MWh.
Merging it with the intraday auctions gave 131.5 — a number that is plausible,
sits in the right range, and is not the price of anything.

Germany is the instructive one, because all four of its series were marked A01.
They differ only by classification sequence: position 1 averaged 120.5,
position 2 averaged 128.7. Both are real prices of real auctions, and only the
first is what everyone means by the German day-ahead price.

This distinction survives the move to 15-minute market time units. On 10 May
2022, German sequence 1 was the hourly product — 24 points, 183.32 EUR/MWh —
while sequence 2 was the quarter-hourly auction at 183.71. Today both arrive as
PT15M and the resolution no longer tells them apart, but sequence 1 is still
the day-ahead. We verified both eras against energy-charts, which matched
sequence 1 to the cent in each.

## Doing it correctly

Two rules. Pick the series before you read any points, then fill each point
forward to the position of the next one.

```python
def parse_a44(root, ns):
    out = {}

    def kind(ts):
        agreement = ts.find("n:contract_MarketAgreement.type", ns)
        seq = ts.find("n:classificationSequence_AttributeInstanceComponent.position", ns)
        return (agreement.text if agreement is not None else "A01",
                seq.text if seq is not None else "1")

    # 1. one series: day-ahead, first classification sequence
    series = root.findall(".//n:TimeSeries", ns)
    day_ahead = [t for t in series if kind(t)[0] == "A01"] or series
    chosen = [t for t in day_ahead if kind(t)[1] == "1"] or day_ahead

    for ts in chosen:
        for period in ts.findall("n:Period", ns):
            start = _utc(period.find("n:timeInterval/n:start", ns).text)
            end = _utc(period.find("n:timeInterval/n:end", ns).text)
            step = RESOLUTIONS[period.find("n:resolution", ns).text]
            total = int((end - start).total_seconds() // 60 // step)

            points = sorted(
                (int(p.find("n:position", ns).text),
                 float(p.find("n:price.amount", ns).text))
                for p in period.findall("n:Point", ns)
            )
            # 2. hold each value until the next position
            for i, (pos, price) in enumerate(points):
                nxt = points[i + 1][0] if i + 1 < len(points) else total + 1
                for k in range(pos, nxt):
                    out[start + timedelta(minutes=step * (k - 1))] = price
    return out
```

The `total` line matters. Without the period end you do not know how far the
last point extends, and the final run — often the quiet hours after midnight —
stays missing even after you fix everything else.

This is the parser in [`entsoe_quickstart.py`](../entsoe_quickstart.py), a
single file with no dependencies. It had the bug too until we found it, which
is the honest reason we are writing this down rather than quietly patching it.

## Checking a parser you already have

Do not take our word for any of this. The check is cheap and does not need our
code:

1. Pick a day with a lot of solar — a sunny weekend in May or June, when midday
   prices flatten or go negative.
2. Fetch it for France, Spain or Italy, the markets that compress most.
3. Count the intervals in the delivery day. If the resolution is PT15M and you
   have fewer than 96, you have the bug.
4. Compare the daily mean against an independent publisher.
   [energy-charts](https://api.energy-charts.info/price?bzn=FR) is free, needs
   no key, and returns JSON.

We use two references rather than one, and neither of them is ENTSO-E:
energy-charts for the coupled European zones, and OTE directly for Czechia. For
18 September 2026 all three agreed on 111.5 EUR/MWh for the Czech day to the
tenth. An independent source is the only thing that catches a parser that is
confidently wrong.

> **Recomputing with your own code proves nothing.** Our prices matched our own
> recomputation exactly while being 11 % wrong. Both sides of the comparison
> shared the same parser, so both were wrong in the same direction.

## Why this is not in the documentation

It is, in a sense. curveType is in the ENTSO-E data model, and A03 is described
there as a variable sized block. What is missing is any signal at the point of
use: the response does not flag a compressed series, and the failure is silent
by construction — you get fewer rows than you asked for and every one of them
is correct.

The established clients do handle it. [`entsoe-py`](https://github.com/EnergieID/entsoe-py),
the most widely used Python wrapper, reindexes the period and forward-fills
whenever `curveType` is A03, which is the right answer:

```python
if soup.find('curvetype').text == 'A03':
    S = S.reindex(pd.date_range(start, end - delta, freq=delta_text)).ffill()
```

So this is not a warning about libraries. It is a warning about the parser
people write themselves, because reading an XML document point by point is the
obvious thing to do and it is wrong here. Ours was hand-rolled, and that is
exactly why it broke.

The result is a class of bug where two people pull the same day from the same
platform and get different daily averages, and neither can see why. If you have
ever reconciled a price series against a counterparty and given up on a
difference of a few percent, this is worth ten minutes of your time.

---

## Who wrote this

We are [progrunners](https://progrunners.com/) — we build market data pipelines
and trading dashboards for European electricity, and we publish the parts that
are useful on their own.

Everything on this page came out of checking our own production prices against
an independent source and not liking the answer. If you want the live numbers
rather than the code, they are at
[progrunners.com/european-electricity-prices](https://progrunners.com/european-electricity-prices/)
for 38 bidding zones, updated through the day.

**More of the same kind of thing:**

- [A practical guide to the ENTSO-E API](https://progrunners.com/entso-e-api/) —
  document types, publication delays, what breaks and why
- [EIC codes for every bidding zone](https://github.com/whipeeer-creator/eic-codes) —
  the lookup table every query needs
- [European day-ahead prices as plain CSV](https://github.com/whipeeer-creator/european-power-prices) —
  39 zones back to 2022, no key required
- [What the imbalance price actually does](https://github.com/whipeeer-creator/imbalance-price-anatomy) —
  measured on 92 018 quarter hours

If you are wrestling with a price series that does not reconcile, write to
`info@progrunners.com` and tell us what it should say.
