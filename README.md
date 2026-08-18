# CDR ⇄ USD converter

**Live at [cdr.maylab.app](https://cdr.maylab.app)**

Converts a Canadian-listed price into its US$-per-share equivalent — and back.
Covers all CIBC CDRs (CAD-hedged depositary receipts, now primarily on the
TSX) plus major TSX/NYSE cross-listings.

## Why not just use the FX rate?

CDRs are **CAD-hedged**: their price embeds CIBC's notional currency hedge and
a fractional share ratio that resets daily. Dividing a CDR price by the spot
FX rate gives a number that means nothing. Instead, this tool derives the day
conversion factor from **simultaneous closes** on both tapes:

```
k = CAD close / USD close
```

`k` bundles the share ratio and the hedged FX into one number, and because the
hedge resets daily it is stable intraday to within basis points — so a single
morning measurement converts live prices all day, entirely client-side.

For unhedged cross-listings (SHOP, TD, CNR/CNI, …) the same `k` works and
lands within arbitrage distance of spot FX, as it should.

## How it stays fresh

A GitHub Actions cron refreshes [rates.json](rates.json) after the Toronto/New
York open and again after the close (weekdays). The page itself is static —
open it anywhere, type a price in either currency, get the other instantly.

## Run it yourself

```bash
pip install -r requirements.txt
python3 update_rates.py     # regenerates rates.json + rates.js
open index.html             # works from file:// — no server needed
```

Add pairs in [cdr_universe.json](cdr_universe.json); entries that fail to
fetch are dropped with a warning, and the updater refuses to overwrite good
rates if Yahoo largely fails.
