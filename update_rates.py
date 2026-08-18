#!/usr/bin/env python3
"""
Refresh conversion factors for the CDR/USD converter page.

Usage:
    python3 update_rates.py

Reads cdr_universe.json (seed list of CAD-listed ⇄ US-listed pairs), batch-
fetches recent daily closes for every leg from Yahoo Finance, and for each
pair computes the day conversion factor

    k = CAD close / USD close        (same trading date on both legs)

Writes rates.json plus rates.js (window.__RATES__ wrapper so the page also
works when opened directly from disk). Pairs where a leg fails to fetch are
dropped with a warning. If most of the universe fails (Yahoo outage or rate
limit), the script aborts WITHOUT writing, so the published rates never
degrade to a near-empty file.
"""

import json
import os
import sys
from datetime import datetime, timezone

import yfinance as yf

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
UNIVERSE_FILE = os.path.join(SCRIPT_DIR, "cdr_universe.json")
RATES_JSON = os.path.join(SCRIPT_DIR, "rates.json")
RATES_JS = os.path.join(SCRIPT_DIR, "rates.js")

FX_SYMBOL = "CAD=X"  # USD/CAD
MIN_COVERAGE = 0.6   # abort without writing below this fetch success rate


def fetch_last_closes(symbols):
    """Batched download; returns { symbol: {'YYYY-MM-DD': close} } of recent closes."""
    out = {}
    hist = yf.download(sorted(set(symbols)), period="7d", interval="1d",
                       group_by="ticker", auto_adjust=False, progress=False, threads=True)
    if hist is None or hist.empty:
        return out
    multi = hasattr(hist.columns, "levels")
    for sym in set(symbols):
        try:
            frame = hist[sym] if multi else hist
            closes = frame["Close"].dropna()
            if closes.empty:
                continue
            # keep every valid (date, close) so pairs can align on a common date
            out[sym] = {d.strftime("%Y-%m-%d"): float(v) for d, v in closes.items()}
        except (KeyError, TypeError):
            continue
    return out


def main():
    with open(UNIVERSE_FILE) as f:
        universe = json.load(f)["pairs"]

    legs = [p["cad"] for p in universe] + [p["us"] for p in universe] + [FX_SYMBOL]
    print(f"Fetching {len(set(legs))} symbols for {len(universe)} pairs...")
    closes = fetch_last_closes(legs)

    fx_series = closes.get(FX_SYMBOL, {})
    usdcad = fx_series[max(fx_series)] if fx_series else None

    pairs, dropped = {}, []
    for p in universe:
        cad_c = closes.get(p["cad"]) or {}
        us_c = closes.get(p["us"]) or {}
        common = sorted(set(cad_c) & set(us_c))
        if common:
            date = common[-1]
            cad_px, us_px = cad_c[date], us_c[date]
        elif cad_c and us_c:
            # No overlapping session (e.g. one-sided holiday) — use each leg's
            # latest close and flag the date mismatch.
            date = f"{max(cad_c)} / {max(us_c)}"
            cad_px, us_px = cad_c[max(cad_c)], us_c[max(us_c)]
        else:
            dropped.append(p["cad"])
            continue
        pairs[p["cad"]] = {
            "cad_symbol": p["cad"],
            "us_symbol": p["us"],
            "type": p["type"],
            "name": p.get("name", p["us"]),
            "aliases": p.get("aliases", []),
            "cad_price": round(cad_px, 4),
            "us_price": round(us_px, 4),
            "k": round(cad_px / us_px, 6),
            "price_date": date,
        }

    if len(pairs) < MIN_COVERAGE * len(universe):
        print(f"ABORT: only {len(pairs)}/{len(universe)} pairs fetched — "
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

    print(f"Wrote {len(pairs)} pairs -> rates.json (+ rates.js)")
    if dropped:
        print(f"Dropped (no data): {', '.join(dropped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
