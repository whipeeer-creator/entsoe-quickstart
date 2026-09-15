# -*- coding: utf-8 -*-
"""A minimal ENTSO-E Transparency Platform client — one file, no dependencies.

Standard library only. Handles the three things that trip people up:
variable resolution (PT15M / PT30M / PT60M), multi-day responses, and the
fact that errors come back as XML with a Reason element rather than an
HTTP status you can branch on.

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
        for period in root.findall(".//n:Period", ns):
            start = _utc(period.find("n:timeInterval/n:start", ns).text)
            step = RESOLUTIONS.get(period.find("n:resolution", ns).text, 60)
            for point in period.findall("n:Point", ns):
                pos = int(point.find("n:position", ns).text)
                value = point.find("n:price.amount", ns)
                if value is None:
                    value = point.find("n:quantity", ns)
                if value is None:
                    continue
                out[start + timedelta(minutes=step * (pos - 1))] = float(value.text)
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
