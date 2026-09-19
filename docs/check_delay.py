# -*- coding: utf-8 -*-
"""How stale is the freshest ENTSO-E data for your zone, right now.

Asks the platform for each document type and reports the end of the newest
interval it actually returns. The answer is what your model could know at this
moment — which is the only version of "publication delay" that matters when you
are deciding whether a feature is look-ahead.

    python3 check_delay.py YOUR_TOKEN 10YCZ-CEPS-----N

Positive minutes mean the data lags behind now; negative means it reaches into
the future, which is what a forecast is supposed to do.

Standard library only, one request per row, a 1.5 s pause between them.

Background: https://github.com/whipeeer-creator/entsoe-quickstart/blob/main/docs/publication-delay.md
"""
import io
import os
import sys
import time
import zipfile
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

API = "https://web-api.tp.entsoe.eu/api"
RESOLUTIONS = {"PT1M": 1, "PT15M": 15, "PT30M": 30, "PT60M": 60, "P1D": 1440}

# (label, extra query parameters, days back, days forward)
DOCUMENTS = [
    ("A44  day-ahead price",      {"documentType": "A44", "_price": 1},           1, 2),
    ("A65  load, actual",         {"documentType": "A65", "processType": "A16",
                                   "_out": 1},                                    1, 1),
    ("A65  load, forecast",       {"documentType": "A65", "processType": "A01",
                                   "_out": 1},                                    1, 2),
    ("A69  wind+solar, D-1",      {"documentType": "A69", "processType": "A01",
                                   "_in": 1},                                     1, 2),
    ("A69  wind+solar, intraday", {"documentType": "A69", "processType": "A18",
                                   "_in": 1},                                     1, 1),
    ("A74  wind+solar, actual",   {"documentType": "A74", "processType": "A16",
                                   "_in": 1},                                     1, 1),
    ("A75  generation per type",  {"documentType": "A75", "processType": "A16",
                                   "_in": 1},                                     1, 1),
    ("A73  generation per unit",  {"documentType": "A73", "processType": "A16",
                                   "_in": 1},                                     1, 0),
    ("A84  activated balancing",  {"documentType": "A84", "processType": "A16",
                                   "_ca": 1},                                     1, 1),
    ("A85  imbalance price",      {"documentType": "A85", "_ca": 1},              1, 1),
    ("A86  imbalance volume",     {"documentType": "A86", "_ca": 1},              1, 1),
]


def fetch(token, params):
    params = dict(params, securityToken=token)
    url = API + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raw = e.read()
    if raw[:2] == b"PK":                       # long windows come back zipped
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            return [z.read(n) for n in z.namelist()]
    return [raw]


def newest(documents):
    """End of the latest interval that is actually populated."""
    latest, note = None, ""
    for raw in documents:
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            note = note or "unparseable"
            continue
        ns = {"n": root.tag.split("}")[0].strip("{")}
        if root.tag.split("}")[-1].startswith("Acknowledgement"):
            code = root.find(".//n:Reason/n:code", ns)
            note = note or f"no data (reason {code.text if code is not None else '?'})"
            continue
        for period in root.findall(".//n:Period", ns):
            start = period.find("n:timeInterval/n:start", ns)
            end = period.find("n:timeInterval/n:end", ns)
            res = period.find("n:resolution", ns)
            positions = [int(p.find("n:position", ns).text)
                         for p in period.findall("n:Point", ns)]
            if start is None or end is None or not positions:
                continue
            step = RESOLUTIONS.get(res.text if res is not None else "", 60)
            begins = datetime.strptime(start.text, "%Y-%m-%dT%H:%MZ")
            ends = datetime.strptime(end.text, "%Y-%m-%dT%H:%MZ")
            reach = min(begins + timedelta(minutes=step * max(positions)), ends)
            reach = reach.replace(tzinfo=timezone.utc)
            latest = reach if latest is None or reach > latest else latest
    return latest, note


def main():
    token = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ENTSOE_TOKEN", "")
    zone = sys.argv[2] if len(sys.argv) > 2 else "10YCZ-CEPS-----N"
    if not token:
        print(__doc__)
        return 1

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    print(f"{zone}   measured {now:%Y-%m-%d %H:%M} UTC\n")
    print(f"  {'document':28} {'newest interval ends':22} {'vs now':>12}")
    print("  " + "-" * 64)

    for label, extra, back, ahead in DOCUMENTS:
        params = {k: v for k, v in extra.items() if not k.startswith("_")}
        if extra.get("_price"):
            params["in_Domain"] = params["out_Domain"] = zone
        elif extra.get("_out"):
            params["outBiddingZone_Domain"] = zone
        elif extra.get("_ca"):
            params["controlArea_Domain"] = zone
        else:
            params["in_Domain"] = zone
        params["periodStart"] = (now - timedelta(days=back)).strftime("%Y%m%d%H00")
        params["periodEnd"] = (now + timedelta(days=ahead)).strftime("%Y%m%d%H00")

        reach, note = newest(fetch(token, params))
        if reach is None:
            print(f"  {label:28} {'—':22} {note:>12}")
        else:
            minutes = (now - reach).total_seconds() / 60
            word = "stale" if minutes > 0 else "ahead"
            print(f"  {label:28} {reach:%Y-%m-%d %H:%M}Z      "
                  f"{abs(minutes):7.0f} min {word}")
        time.sleep(1.5)

    print("\n  A row that is stale by more than the interval it covers is data "
          "\n  your model cannot have had at the start of that interval.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
