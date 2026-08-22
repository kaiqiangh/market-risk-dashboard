"""Yahoo Chart API ZQ fed funds futures fetching (architecture §1.6).

ZQ contract codes look like ZQU26.CBT (Sep 2026); the free interface needs no key.
On rate limiting, raise ProviderError → degradation chain (FedWatch absence does not affect the whole pipeline).
"""

from __future__ import annotations

from pipeline.providers._util import UA
from pipeline.providers.base import ProviderError

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def fetch_contract_price(symbol: str, timeout: float = 12.0) -> float | None:
    """Fetch the most recent settlement price of a single ZQ contract (100 − price = implied rate).

    #87/#103: Yahoo's 429s are TLS-client-fingerprint gating, not rate limiting — so this
    talks to the chart endpoint with curl_cffi impersonating Chrome, and #103/E-3 removed the
    nested retry (FedWatch absence degrades the macro dataset; it never blocks the pipeline).
    """
    from curl_cffi import requests as crequests

    try:
        resp = crequests.get(
            YAHOO_CHART.format(symbol=symbol),
            params={"interval": "1d", "range": "5d"},
            headers={"User-Agent": UA},
            timeout=timeout,
            impersonate="chrome",
        )
        if resp.status_code == 429:
            raise ProviderError(f"Yahoo chart {symbol}: 429 rate limited", cls="rate_limited")
        if resp.status_code != 200:
            raise ProviderError(f"Yahoo chart {symbol}: HTTP {resp.status_code}")
        data = resp.json()
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ProviderError.from_exception(exc, detail=f"Yahoo chart {symbol}: {exc}") from exc

    try:
        result = data.get("chart", {}).get("result", [])[0]
        meta = result.get("meta", {})
        price = meta.get("regularMarketPrice") or meta.get("previousClose")
        if price is None:
            closes = [c for c in result.get("indicators", {}).get("quote", [{}])[0].get("close", []) if c]
            price = closes[-1] if closes else None
        if price is None:
            raise ProviderError(f"Yahoo chart {symbol}: no price")
        return float(price)
    except (IndexError, KeyError, TypeError, ValueError) as exc:  # noqa: BLE001
        raise ProviderError(f"Yahoo chart {symbol}: parse failed: {exc}") from exc


# ZQ contract month codes: F=Jan G=Feb H=Mar J=Apr K=May M=Jun N=Jul Q=Aug U=Sep V=Oct X=Nov Z=Dec
_CONTRACT_MONTHS = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
                   7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}
_QUARTERLY_MONTHS = (3, 6, 9, 12)


def next_contract_codes(date=None, count: int = 2) -> list[str]:
    """Generate the next count ZQ quarterly contract codes (e.g. 2026-08 → ["ZQU26.CBT", "ZQZ26.CBT"]).

    Month-end meetings use the next-month contract method (architecture §1.6): expiry months are
    quarter ends (Mar/Jun/Sep/Dec).
    """
    from datetime import date as _date

    today = date or _date.today()
    codes: list[str] = []
    year = today.year
    month = today.month
    while len(codes) < count:
        for m in _QUARTERLY_MONTHS:
            if m > month or (m == month and len(codes) == 0 and _is_end_of_month(today)):
                yy = year % 100
                codes.append(f"ZQ{_CONTRACT_MONTHS[m]}{yy:02d}.CBT")
        month = 0
        year += 1
        if len(codes) >= count:
            break
    return codes[:count]


def _is_end_of_month(day) -> bool:
    from datetime import date, timedelta

    if not isinstance(day, date):
        return False
    tomorrow = day + timedelta(days=1)
    return tomorrow.month != day.month


def meeting_date_for_contract(code: str) -> str | None:
    """Infer the FOMC meeting date from the contract code (approximation: third Wednesday of the contract month, ISO UTC date).

    E.g. ZQU26.CBT → 2026-09-16T18:00:00Z. Exact dates follow the Fed's official calendar (V2).
    """
    import datetime as _dt

    code = code.upper().replace(".CBT", "")
    if not code.startswith("ZQ") or len(code) < 5:
        return None
    month_code = code[2]
    year = 2000 + int(code[3:5])
    month = next((m for m, c in _CONTRACT_MONTHS.items() if c == month_code), None)
    if month is None:
        return None
    # Third Wednesday of that month
    first = _dt.date(year, month, 1)
    offset = (2 - first.weekday()) % 7  # Wednesday = 2
    third_wed = first + _dt.timedelta(days=offset + 14)
    return f"{third_wed.isoformat()}T18:00:00Z"
