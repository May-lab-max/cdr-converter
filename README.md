# CDR ⇄ USD converter

**Live at [cdr.maylab.app](https://cdr.maylab.app)**

Converts a Canadian-listed price into its US$-per-share equivalent — and back.
Covers all CIBC CDRs (CAD-hedged depositary receipts, now primarily on the
TSX) plus major TSX/NYSE cross-listings.

## Why not just use the FX rate?

CDRs are **CAD-hedged**: their price embeds CIBC's notional currency hedge and
a fractional share ratio that resets daily. Dividing a CDR price by the spot
FX rate gives a number that means nothing. Instead, this tool measures the
conversion factor directly from both tapes:

```
k = median over matched minutes of ( CAD price / USD price )
```

The updater pulls 1-minute bars for both legs, keeps only minutes where both
traded (same timestamp), skips the opening auction (before 9:35 ET), and takes
the median over the latest session with at least 20 matched minutes. A single
close-to-close ratio is one noisy sample — in a fast market the two closing
prints can be seconds apart, and the CDR close can sit a few ticks off fair
value. Thinly traded CDRs fall back to the close ratio.

**Reliability label.** The page labels each pair "Accurate to ±0.25%" or
"Approximate · <reason>". The ±0.25% figure is measured: across 48 hedged CDRs
(Nov 2026), a day-old `k` applied to the next day's 1-minute prices put 96% of
minutes within ±0.25% (99.6% within ±0.5%). It is shown only for hedged CDRs
priced from matched minutes whose session band (half the p10–p90 spread of the
minute ratios, `k_band_bp`) is ≤ 25 bp. Cross-listings (k moves with USD/CAD),
close-ratio fallbacks and mismatched dates get "Approximate".

`k` bundles the share ratio and the hedged FX into one number, and because the
hedge resets daily it does not move with intraday FX — so one measurement
converts live prices all day, entirely client-side. The updater never replaces
a pair with a `k` from an older session than the one already published.

**Comparing against live quotes:** use the same instant on both legs. Many
free quote pages delay TSX quotes by 15 minutes; in a volatile session a US
stock often moves 1% or more in 15 minutes, which looks like a conversion
error but is quote lag.

For unhedged cross-listings (SHOP, TD, CNR/CNI, …) the same `k` works and
lands within arbitrage distance of spot FX, as it should.

## How it stays fresh

A GitHub Actions workflow refreshes [rates.json](rates.json) after the
Toronto/New York open and again after the close (weekdays). Vercel Cron starts
it on time through [api/dispatch-refresh.js](api/dispatch-refresh.js); GitHub's
own schedule runs hours late, so it is only a backup. Vercel serves the site and
redeploys on every commit, so each refresh goes live in about a minute.
Vercel Web Analytics counts visits and referrers. The page itself is static —
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
