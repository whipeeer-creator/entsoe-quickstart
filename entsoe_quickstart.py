# -*- coding: utf-8 -*-
"""A minimal ENTSO-E Transparency Platform client — one file, no dependencies.

Standard library only. Handles the things that trip people up:

* **curveType A03.** When consecutive intervals share a price, ENTSO-E sends
  only the first one and omits the rest. Read position-by-position and those
  intervals vanish — a French day can come back with 85 of 96 quarter-hours
  and a daily average 11 % too high.
* **Several series in one response.** Day-ahead (A01) and intraday auctions
  (A07) arrive together, as do the 60-minute and 15-minute MTU publications.
  Merge them and one silently overwrites the other.
* variable resolution (PT15M / PT30M / PT60M) and multi-day responses
* errors come back as XML with a Reason element, not an HTTP status

    from entsoe_quickstart import Entsoe

    api = Entsoe("your-security-token")
    for t, price in api.day_ahead_prices("10Y1001A1001A82H").items():
        print(t, price)

Get a token: register at https://transparency.entsoe.eu, then e-mail
transparency@entsoe.eu with the subject "Restful API access" and the address
you registered with. It arrives within a few days.
"""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

__all__ = ["Entsoe", "EntsoeError"]
__version__ = "1.0.0"

ENDPOINT = "https://web-api.tp.entsoe.eu/api"

# Minutes per point for each resolution ENTSO-E actually returns.
RESOLUTIONS = {"PT15M": 15, "PT30M": 30, "PT60M": 60, "P1D": 1440}


class EntsoeError(RuntimeError):
    """Raised when the platform answers with a Reason instead of data."""


class Entsoe:
    def __init__(self, token: str, timeout: int = 60):
        if not token:
            raise ValueError("a security token is required")
        self.token = token
        self.timeout = timeout

    # ---------------------------------------------------------------- core

    def get(self, **params) -> ET.Element:
        """One raw query. Returns the parsed root element.

        Every documented endpoint is this call with a different documentType,
        so anything missing from the helpers below is still one line away.
        """
        params["securityToken"] = self.token
        url = ENDPOINT + "?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            # The useful message is in the body, not the status line.
            raise EntsoeError(_reason(e.read()) or f"HTTP {e.code}") from None
        root = ET.fromstring(body)
        if root.tag.endswith("Acknowledgement_MarketDocument"):
            raise EntsoeError(_reason(body) or "request acknowledged, no data")
        return root

    def series(self, **params) -> dict[datetime, float]:
        """A query whose payload is a time series. Keys are UTC datetimes.

        Resolution is read per Period, so a response that mixes hourly and
        quarter-hourly days lands on the right timestamps. Values are taken
        from whichever of price.amount or quantity the document carries.
        """
        root = self.get(**params)
        ns = {"n": root.tag.split("}")[0].strip("{")}
        out: dict[datetime, float] = {}

        def _kind(ts):
            # A01 = day-ahead contract, A07 = intraday auction. The sequence position
            # separates the 60-minute and 15-minute MTU publications that now run
            # side by side. One response can carry several of these at once, and
            # merging them silently overwrites one series with another.
            agreement = ts.find("n:contract_MarketAgreement.type", ns)
            seq = ts.find("n:classificationSequence_AttributeInstanceComponent.position", ns)
            return (agreement.text if agreement is not None else "A01",
                    seq.text if seq is not None else "1")

        series = root.findall(".//n:TimeSeries", ns)
        day_ahead = [t for t in series if _kind(t)[0] == "A01"] or series
        first_seq = [t for t in day_ahead if _kind(t)[1] == "1"] or day_ahead
        periods = [p for t in first_seq for p in t.findall("n:Period", ns)]

        for period in (periods or root.findall(".//n:Period", ns)):
            start = _utc(period.find("n:timeInterval/n:start", ns).text)
            end = _utc(period.find("n:timeInterval/n:end", ns).text)
            step = RESOLUTIONS.get(period.find("n:resolution", ns).text, 60)
            total = max(1, int((end - start).total_seconds() // 60 // step))
            # curveType A03 ("variable sized block"): when consecutive intervals share
            # a price, ENTSO-E sends only the first one and skips the rest. The value
            # holds until the next position, so the gaps have to be filled in. Read
            # position-by-position and you silently lose those intervals — which is the
            # single most common mistake people make with this API.
            points = sorted(
                (int(p.find("n:position", ns).text), p)
                for p in period.findall("n:Point", ns)
            )
            for i, (pos, point) in enumerate(points):
                value = point.find("n:price.amount", ns)
                if value is None:
                    value = point.find("n:quantity", ns)
                if value is None:
                    continue
                nxt = points[i + 1][0] if i + 1 < len(points) else total + 1
                for k in range(pos, nxt):
                    out[start + timedelta(minutes=step * (k - 1))] = float(value.text)
        return out

    # ------------------------------------------------------------- helpers

    def day_ahead_prices(self, zone, start=None, end=None):
        """A44 — day-ahead auction results, EUR/MWh."""
        s, e = _window(start, end)
        return self.series(documentType="A44", in_Domain=zone, out_Domain=zone,
                           periodStart=s, periodEnd=e)

    def load(self, zone, start=None, end=None, actual=True):
        """A65 — total load. actual=False gives the day-ahead forecast."""
        s, e = _window(start, end)
        return self.series(documentType="A65", outBiddingZone_Domain=zone,
                           processType="A16" if actual else "A01",
                           periodStart=s, periodEnd=e)

    def wind_solar_forecast(self, zone, start=None, end=None, intraday=False):
        """A69 — wind and solar forecast.

        intraday=True asks for the intraday update (processType A18), which is
        fresher than the day-ahead one and much less used.
        """
        s, e = _window(start, end)
        return self.series(documentType="A69", in_Domain=zone,
                           processType="A18" if intraday else "A01",
                           periodStart=s, periodEnd=e)

    def generation(self, zone, start=None, end=None):
        """A75 — actual generation per production type."""
        s, e = _window(start, end)
        return self.series(documentType="A75", in_Domain=zone,
                           processType="A16", periodStart=s, periodEnd=e)


# ------------------------------------------------------------------ private

def _utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)


def _stamp(t: datetime) -> str:
    """The API wants yyyyMMddHHmm in UTC. Naive input is assumed to be UTC."""
    if t.tzinfo is not None:
        t = t.astimezone(timezone.utc)
    return t.strftime("%Y%m%d%H%M")


def _window(start, end):
    """Defaults to today in UTC. Accepts datetimes or ready-made strings."""
    if start is None:
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                                   microsecond=0)
    if end is None:
        end = (start if isinstance(start, datetime)
               else datetime.now(timezone.utc)) + timedelta(days=1)
    return (start if isinstance(start, str) else _stamp(start),
            end if isinstance(end, str) else _stamp(end))


def _reason(body: bytes) -> str:
    """Pull the human-readable text out of an error document."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return ""
    ns = {"n": root.tag.split("}")[0].strip("{")}
    bits = [e.text for e in root.findall(".//n:Reason/n:text", ns) if e.text]
    code = root.find(".//n:Reason/n:code", ns)
    if code is not None and code.text:
        bits.insert(0, f"[{code.text}]")
    return " ".join(bits)


if __name__ == "__main__":
    import os
    import sys

    tok = os.environ.get("ENTSOE_TOKEN")
    if not tok:
        sys.exit("set ENTSOE_TOKEN first")
    zone = sys.argv[1] if len(sys.argv) > 1 else "10Y1001A1001A82H"
    prices = Entsoe(tok).day_ahead_prices(zone)
    if not prices:
        sys.exit("no data returned — check the zone code and the date window")
    for t, p in sorted(prices.items()):
        print(f"{t:%Y-%m-%d %H:%M} UTC  {p:8.2f} EUR/MWh")
    values = list(prices.values())
    print(f"\n{len(values)} points · mean {sum(values)/len(values):.2f} "
          f"· min {min(values):.2f} · max {max(values):.2f}")
