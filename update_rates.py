#!/usr/bin/env python3
"""
Refresh conversion factors for the CDR/USD converter page.

Usage:
    python3 update_rates.py

Reads cdr_universe.json (seed list of CAD-listed ⇄ US-listed pairs) and, for
each pair, estimates the conversion factor

    k = CAD price / USD price

Method (in order of preference):

1. "intraday" — batch-fetch 1-minute bars for every leg, align the two legs on
   the SAME minute timestamp, compute k for every minute in which both legs
   traded, and take the MEDIAN over the latest session with enough overlap.
   One closing print per leg is a single noisy sample: the two closes can be
   seconds apart in a fast market, and the CDR close can sit a few ticks off
   fair value. The median of hundreds of synchronized minutes is not moved by
   either. The p10–p90 spread of the minute ratios is published as k_band_bp
   (half-width, basis points) so the page can show how tight k is.

2. "close" — fallback when minute data is missing: CAD close / USD close on the
   latest common trading date (the original method).

Stale guard: Yahoo sometimes drops the newest daily bar for one leg, which used
to make the "latest common date" slide back two or three sessions. A pair is
never replaced with a k from an OLDER session than the one already published.

Writes rates.json plus rates.js (window.__RATES__ wrapper so the page also
works when opened directly from disk). Pairs where a leg fails to fetch are
dropped with a warning. If most of the universe fails (Yahoo outage or rate
limit), the script aborts WITHOUT writing, so the published rates never
degrade to a near-empty file.
"""

import json
import os
import sys
from datetime import datetime, time, timezone

import yfinance as yf

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
UNIVERSE_FILE = os.path.join(SCRIPT_DIR, "cdr_universe.json")
RATES_JSON = os.path.join(SCRIPT_DIR, "rates.json")
RATES_JS = os.path.join(SCRIPT_DIR, "rates.js")

FX_SYMBOL = "CAD=X"  # USD/CAD
MIN_COVERAGE = 0.6   # abort without writing below this fetch success rate

MARKET_TZ = "America/New_York"
SKIP_BEFORE = time(9, 35)  # ignore the opening-auction minutes
MIN_MINUTES = 20           # fewest synchronized minutes for an intraday k


def _frames(hist, symbols):
    """Yield (symbol, per-symbol frame) from a yf.download result."""
    if hist is None or hist.empty:
        return
    multi = hasattr(hist.columns, "levels")
    for sym in set(symbols):
        try:
            yield sym, (hist[sym] if multi else hist)
        except (KeyError, TypeError):
            continue


def fetch_daily_closes(symbols):
    """Returns { symbol: {'YYYY-MM-DD': close} } of recent daily closes."""
    hist = yf.download(sorted(set(symbols)), period="10d", interval="1d",
                       group_by="ticker", auto_adjust=False, progress=False, threads=True)
    out = {}
    for sym, frame in _frames(hist, symbols):
        closes = frame["Close"].dropna()
        if not closes.empty:
            out[sym] = {d.strftime("%Y-%m-%d"): float(v) for d, v in closes.items()}
    return out


def fetch_minute_closes(symbols):
    """Returns { symbol: Series of 1-minute closes, index in New York time }.

    Yahoo only emits a minute bar when the symbol traded in that minute, so an
    inner join of two legs keeps exactly the minutes where both printed."""
    try:
        hist = yf.download(sorted(set(symbols)), period="5d", interval="1m",
                           prepost=False, group_by="ticker", auto_adjust=False,
                           progress=False, threads=True)
    except Exception as e:  # minute data is an upgrade, never a hard failure
        print(f"WARN: minute download failed ({e}); falling back to closes")
        return {}
    out = {}
    for sym, frame in _frames(hist, symbols):
        s = frame["Close"].dropna()
        if s.empty:
            continue
        idx = s.index.tz_localize("UTC") if s.index.tz is None else s.index
        s.index = idx.tz_convert(MARKET_TZ)
        out[sym] = s
    return out


def intraday_k(cad_min, us_min):
    """Median minute ratio over the latest session with enough overlap.

    Returns (k, band_bp, n_minutes, 'YYYY-MM-DD') or None."""
    if cad_min is None or us_min is None:
        return None
    ratio = (cad_min / us_min).dropna()  # aligns on the exact minute timestamp
    ratio = ratio[ratio.index.time >= SKIP_BEFORE]
    if ratio.empty:
        return None
    for day in sorted(set(ratio.index.date), reverse=True):
        r = ratio[ratio.index.date == day]
        if len(r) < MIN_MINUTES:
            continue
        k = float(r.median())
        band = (float(r.quantile(0.9)) - float(r.quantile(0.1))) / 2 / k * 1e4
        return k, round(band, 1), len(r), day.strftime("%Y-%m-%d")
    return None


def close_k(cad_c, us_c):
    """Original method: ratio of closes on the latest common date."""
    common = sorted(set(cad_c) & set(us_c))
    if common:
        d = common[-1]
        return cad_c[d] / us_c[d], d, cad_c[d], us_c[d]
    if cad_c and us_c:
        # No overlapping session (e.g. one-sided holiday) — use each leg's
        # latest close and flag the date mismatch.
        dc, du = max(cad_c), max(us_c)
        return cad_c[dc] / us_c[du], f"{dc} / {du}", cad_c[dc], us_c[du]
    return None


def session_of(entry):
    """Latest YYYY-MM-DD a published pair entry is based on."""
    return max(entry.get("price_date", "").split(" / "))


def load_previous():
    try:
        with open(RATES_JSON) as f:
            return json.load(f).get("pairs", {})
    except (OSError, ValueError):
        return {}


def main():
    with open(UNIVERSE_FILE) as f:
        universe = json.load(f)["pairs"]
    previous = load_previous()

    legs = [p["cad"] for p in universe] + [p["us"] for p in universe]
    print(f"Fetching {len(set(legs))} symbols for {len(universe)} pairs...")
    daily = fetch_daily_closes(legs + [FX_SYMBOL])
    minutes = fetch_minute_closes(legs)

    fx_series = daily.get(FX_SYMBOL, {})
    usdcad = fx_series[max(fx_series)] if fx_series else None

    pairs, dropped, kept_prev = {}, [], []
    counts = {"intraday": 0, "close": 0}
    for p in universe:
        cad_c = daily.get(p["cad"]) or {}
        us_c = daily.get(p["us"]) or {}
        intra = intraday_k(minutes.get(p["cad"]), minutes.get(p["us"]))

        if intra:
            k, band, n, date = intra
            # display prices: that session's closes (last minute bar if the
            # daily bar is missing)
            cad_px = cad_c.get(date, float(minutes[p["cad"]].iloc[-1]))
            us_px = us_c.get(date, float(minutes[p["us"]].iloc[-1]))
            method = "intraday"
        else:
            fallback = close_k(cad_c, us_c)
            if not fallback:
                if p["cad"] in previous:
                    pairs[p["cad"]] = previous[p["cad"]]
                    kept_prev.append(p["cad"])
                else:
                    dropped.append(p["cad"])
                continue
            k, date, cad_px, us_px = fallback
            band, n, method = None, None, "close"

        entry = {
            "cad_symbol": p["cad"],
            "us_symbol": p["us"],
            "type": p["type"],
            "name": p.get("name", p["us"]),
            "aliases": p.get("aliases", []),
            "cad_price": round(cad_px, 4),
            "us_price": round(us_px, 4),
            "k": round(k, 6),
            "k_method": method,
            "k_minutes": n,
            "k_band_bp": band,
            "price_date": date,
        }

        # stale guard: never step back to an older session than is published
        prev = previous.get(p["cad"])
        if prev and session_of(prev) > session_of(entry):
            pairs[p["cad"]] = prev
            kept_prev.append(p["cad"])
            continue

        pairs[p["cad"]] = entry
        counts[method] += 1

    fresh = len(pairs) - len(kept_prev)
    if fresh < MIN_COVERAGE * len(universe):
        print(f"ABORT: only {fresh}/{len(universe)} pairs fetched — "
              f"keeping previous rates untouched.")
        return 1

    rates = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M UTC"),
        "usdcad_spot": round(usdcad, 5) if usdcad else None,
        "pairs": pairs,
    }
    with open(RATES_JSON, "w") as f:
        json.dump(rates, f, indent=2)
    with open(RATES_JS, "w") as f:
        f.write("window.__RATES__ = ")
        json.dump(rates, f, indent=2)
        f.write(";\n")

    print(f"Wrote {len(pairs)} pairs -> rates.json (+ rates.js): "
          f"{counts['intraday']} intraday-median, {counts['close']} close-ratio")
    if kept_prev:
        print(f"Kept previous (newer) entry: {', '.join(kept_prev)}")
    if dropped:
        print(f"Dropped (no data): {', '.join(dropped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
