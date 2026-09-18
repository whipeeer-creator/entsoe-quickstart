# -*- coding: utf-8 -*-
"""Check whether an ENTSO-E day is missing intervals to curveType A03.

Fetches one delivery day twice — once the naive way, once filling compressed
runs forward — and prints both. If the two disagree, the naive parser in your
own code is losing data the same way.

    python3 check_gaps.py YOUR_TOKEN 10YFR-RTE------C 2026-09-18 Europe/Paris

Standard library only. Read the whole thing before running it; it is 90 lines
and it makes exactly one request.

Background: https://github.com/whipeeer-creator/entsoe-quickstart/blob/main/docs/curvetype-a03.md
"""
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

RESOLUTIONS = {"PT15M": 15, "PT30M": 30, "PT60M": 60}


def fetch(token, zone, day):
    start = day.strftime("%Y%m%d0000")
    end = (day + timedelta(days=1)).strftime("%Y%m%d0000")
    url = (f"https://web-api.tp.entsoe.eu/api?securityToken={token}"
           f"&documentType=A44&in_Domain={zone}&out_Domain={zone}"
           f"&periodStart={start}&periodEnd={end}")
    with urllib.request.urlopen(url, timeout=60) as r:
        return ET.fromstring(r.read())


def _utc(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)


def parse(root, fill):
    """fill=False is the common mistake; fill=True is correct."""
    ns = {"n": root.tag.split("}")[0].strip("{")}
    out = {}

    def kind(ts):
        agreement = ts.find("n:contract_MarketAgreement.type", ns)
        seq = ts.find("n:classificationSequence_AttributeInstanceComponent.position", ns)
        return (agreement.text if agreement is not None else "A01",
                seq.text if seq is not None else "1")

    series = root.findall(".//n:TimeSeries", ns)
    if fill:                                  # one series, not all of them merged
        day_ahead = [t for t in series if kind(t)[0] == "A01"] or series
        series = [t for t in day_ahead if kind(t)[1] == "1"] or day_ahead

    for ts in series:
        for period in ts.findall("n:Period", ns):
            start = _utc(period.find("n:timeInterval/n:start", ns).text)
            end = _utc(period.find("n:timeInterval/n:end", ns).text)
            step = RESOLUTIONS.get(period.find("n:resolution", ns).text, 60)
            total = max(1, int((end - start).total_seconds() // 60 // step))
            points = sorted((int(p.find("n:position", ns).text),
                             float(p.find("n:price.amount", ns).text))
                            for p in period.findall("n:Point", ns))
            for i, (pos, price) in enumerate(points):
                last = (points[i + 1][0] if i + 1 < len(points) else total + 1) if fill else pos + 1
                for k in range(pos, last):
                    out[start + timedelta(minutes=step * (k - 1))] = price
    return out


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        return 1
    token, zone, den, pasmo = sys.argv[1:5]
    day = datetime.strptime(den, "%Y-%m-%d").date()
    tz = ZoneInfo(pasmo)
    root = fetch(token, zone, day)

    print(f"{zone}  {den}  ({pasmo})\n")
    for label, fill in (("read point by point", False), ("runs filled forward", True)):
        d = parse(root, fill)
        v = [p for t, p in d.items() if t.astimezone(tz).date() == day]
        if not v:
            print(f"  {label:22} no data")
            continue
        print(f"  {label:22} {len(v):3} intervals · mean {sum(v)/len(v):8.2f} "
              f"· min {min(v):8.2f} · max {max(v):8.2f}")

    a = [p for t, p in parse(root, False).items() if t.astimezone(tz).date() == day]
    b = [p for t, p in parse(root, True).items() if t.astimezone(tz).date() == day]
    if a and b and len(a) != len(b):
        rozdil = (sum(a) / len(a) - sum(b) / len(b)) / (sum(b) / len(b)) * 100
        print(f"\n  {len(b) - len(a)} intervals are compressed on this day.")
        print(f"  Reading them point by point puts the daily mean {rozdil:+.1f} % out.")
    elif a and b:
        print("\n  Nothing compressed on this day — try a sunny weekend in May or June.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
