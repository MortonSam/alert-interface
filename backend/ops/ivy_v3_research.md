# Ivy v3 research: which setups earn a rare, arithmetic-first pick

Report only (2026-10-12). Ivy v2 is unchanged; nothing here touched the ledger, the site or production data.
Code: `app/scripts/ivy_v3_pull.py` (the chain pull) and `app/scripts/ivy_v3_analyze.py` (odds, families, costs, bootstrap, calibration);
data: `ops/ivy_v3/events*.jsonl` (per-event figures only), `results.json`, `tables.md`, `picks.json`.

## 1. Historical option prices

Intrinio's EOD option chains on this plan begin in January 2022: a 2021 date returns no expirations for TSLA, JPM or KO, while
2022-01-18, 2023-07-18 and 2025-07-15 return full chains with bids, asks and IVs. So the fit window is 2022-2023, not 2021-2023.

For every stored earnings reaction since 2022 (9,349 with a 1-day move), the pull fetched the expirations listed on the last session
before the report, chose the nearest expiry that captures it (the same rule the nightly uses: after the report day, or on it for a
before-open report), and read that expiry's chain on the session before and the session after. Each event keeps only derived
figures: the ATM straddle's bid, ask and mid, the implied move, ATM IV before and after, and the bids, asks and IVs of a strike ladder
at spot × (1 ± k × implied move) for k = 0.5, 1, 1.5, 2 and at spot × (1 ± 2.5%, 5%, 7.5%, 10%, 15%), on both sessions.

Coverage (events with both chains): 2022 1878, 2023 1891, 2024 1935, 2025 1964, 2026 1476; 9,144 in all.
Skipped: no expirations returned 149 (mostly renamed or newly listed tickers), no priced ATM pair 52, no stored close 22, one dropped
connection. API calls: 27,795 across the four parallel pulls, plus 39 feasibility calls and about 1,500 from a first single-stream
pull that was stopped (its records were kept and deduplicated).

## 2. Each stock's own odds

For an event on date d, the stock's typical absolute 1-day move τ is the mean absolute move of its own reports before d, shrunk toward
its GICS sector's mean before d with weight 6 (so a stock with 2 reports is mostly its sector, one with 20 is mostly itself); fewer than
2 own reports uses the sector alone. The probability model pools standardized moves z = move / τ (τ as known at the time) over every
report before d and reads P(|z| < x), P(|z| > x) or P(z > x) from that empirical distribution: no look-ahead, and no parametric shape.
The options' implied move is the ATM straddle mid over the pre-report close; R = implied move / τ is the pricing ratio each family keys on.

## 3. Families and the pre-registered grids

- a. Options overpriced: sell premium when R > θ, θ ∈ {1.1, 1.25, 1.5, 1.75, 2.0}. Iron butterfly (short ATM straddle, long wings at ±1 or ±2 implied moves) and iron condor (short ±1, long ±2). A structure with under 25% of its width at risk is skipped (dollars per $100 risked would mean nothing).
- b. Options underpriced: buy a straddle (ATM) or strangle (±1 implied move) when R < θ, θ ∈ {0.5, 0.65, 0.8, 0.9}.
- c. The v2 rule as baseline: 20-day momentum ≤ −10% (and −5%), at least 8 prior reports, implied move ≤ 1.2 × (and 1.5 ×) the prior average 5-day move; a bull call spread long ATM, short at the strike nearest spot × (1 + usual 5-day move). Features come from the stored earnings_features rows (built without look-ahead).
- d. Post-earnings drift: after a report-day move beyond θ × τ (θ ∈ {1, 1.5, 2}) or beyond 5% / 8%, hold the stock in that direction 20 sessions from the post-report close, judged against the S&P 500's own 20-session return (SPY, stored bars) so a bull market is not mistaken for drift. No estimates used.
- e. Analyst action drift (research only, unshippable: the actions come from Yahoo): after an upgrade (long), a downgrade (short) or both, hold 20 sessions from the action day's close, index-relative as in d.

Entries at the pre-report close, exits at the post-report close (a, b, c); 20 sessions later for d and e. Costs: every leg buys at mid + c × spread
and sells at mid − c × spread with c = 0.5 (that is, at the ask and the bid) and again c = 1.0 (a full spread each way); stock trades pay 10 bp
and 20 bp round trips. An expiry-day exit with no two-sided quote settles at intrinsic value. Fit years 2022-2023 (1.95 years of events),
held-out 2024-2026 (2.74 years). Judged by expected dollars per $100 risked (max loss for spreads, debit for long options, $100 of stock
for d and e) with a 2,000-draw bootstrap 95% interval. A variant passes only if its held-out interval stays above zero at c = 0.5, its point estimate stays
positive at c = 1.0, and it has at least 30 held-out trades.

## 4. Every variant tried (held-out 2024-2026 unless marked fit)

| pass | family | variant | fit n | fit EV | held-out n | per yr | EV/$100 | 95% CI | win | avg win | avg loss | worst | max DD | EV full spread |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| yes | e_analyst_drift | {"action": "up"} | 1944 | 0.16 | 2812 | 1026.1 | 0.41 | [0.05, 0.75] | 0.488 | 7.25 | -6.13 | -36.11 | 709.6 | 0.31 |
|  | b_long_vol | {"structure": "strangle", "theta": 0.65} | 22 | 174.7 | 10 | 3.6 | 47.5 | [-69.13, 231.29] | 0.2 | 483.65 | -61.53 | -100.0 | 297.6 | 30.45 |
|  | d_post_earnings_drift | {"theta_tau": 2.0} | 485 | -0.02 | 772 | 281.7 | 0.3 | [-0.45, 1.04] | 0.506 | 7.16 | -6.74 | -93.74 | 236.2 | 0.2 |
|  | d_post_earnings_drift | {"theta_tau": 1.5} | 923 | 0.3 | 1404 | 512.3 | 0.18 | [-0.34, 0.68] | 0.509 | 6.55 | -6.43 | -93.74 | 266.9 | 0.08 |
|  | d_post_earnings_drift | {"theta_abs": 0.08} | 565 | 0.67 | 1072 | 391.2 | 0.16 | [-0.55, 0.9] | 0.501 | 7.83 | -7.54 | -93.74 | 314.6 | 0.06 |
|  | e_analyst_drift | {"action": "both"} | 4096 | -0.04 | 5365 | 1957.6 | 0.12 | [-0.14, 0.39] | 0.505 | 6.93 | -6.82 | -94.76 | 918.7 | 0.02 |
|  | d_post_earnings_drift | {"theta_tau": 1.0} | 1635 | 0.24 | 2431 | 887.0 | -0.02 | [-0.37, 0.34] | 0.501 | 6.18 | -6.23 | -93.74 | 538.7 | -0.12 |
|  | d_post_earnings_drift | {"theta_abs": 0.05} | 1258 | 0.24 | 2089 | 762.2 | -0.05 | [-0.48, 0.41] | 0.495 | 6.85 | -6.83 | -148.83 | 578.2 | -0.15 |
|  | e_analyst_drift | {"action": "down"} | 2152 | -0.22 | 2553 | 931.6 | -0.19 | [-0.57, 0.19] | 0.523 | 6.6 | -7.63 | -94.76 | 1439.0 | -0.29 |
|  | b_long_vol | {"structure": "strangle", "theta": 0.8} | 157 | 19.0 | 84 | 30.7 | -5.55 | [-35.05, 29.15] | 0.298 | 158.65 | -75.12 | -100.0 | 2127.5 | -22.38 |
|  | b_long_vol | {"structure": "straddle", "theta": 0.8} | 161 | 4.17 | 86 | 31.4 | -8.8 | [-22.45, 5.66] | 0.407 | 54.81 | -52.45 | -99.21 | 1040.4 | -21.25 |
|  | b_long_vol | {"structure": "straddle", "theta": 0.65} | 22 | 80.99 | 10 | 3.6 | -14.45 | [-64.45, 50.59] | 0.2 | 152.94 | -56.29 | -91.8 | 369.5 | -26.25 |
|  | b_long_vol | {"structure": "straddle", "theta": 0.9} | 374 | 2.26 | 225 | 82.1 | -16.22 | [-24.06, -7.89] | 0.338 | 53.4 | -51.73 | -100.0 | 3690.1 | -29.73 |
|  | b_long_vol | {"structure": "strangle", "theta": 0.9} | 362 | 13.54 | 220 | 80.3 | -19.15 | [-36.15, -1.16] | 0.264 | 143.45 | -77.37 | -100.0 | 5078.5 | -34.61 |
|  | a_short_premium | {"structure": "iron_condor", "theta": 1.1, "wing": 2} | 1737 | -14.58 | 3000 | 1094.7 | -20.74 | [-22.24, -19.29] | 0.336 | 14.46 | -38.55 | -494.44 | 62379.2 | -27.15 |
|  | a_short_premium | {"structure": "iron_condor", "theta": 1.25, "wing": 2} | 1396 | -15.46 | 2270 | 828.3 | -21.6 | [-23.24, -20.1] | 0.289 | 13.51 | -35.9 | -494.44 | 49113.2 | -28.23 |
|  | a_short_premium | {"structure": "iron_condor", "theta": 1.5, "wing": 2} | 917 | -16.1 | 1318 | 480.9 | -22.08 | [-24.14, -20.22] | 0.221 | 12.5 | -31.87 | -494.44 | 29100.4 | -28.88 |
|  | a_short_premium | {"structure": "iron_condor", "theta": 1.75, "wing": 2} | 576 | -17.66 | 666 | 243.0 | -22.88 | [-25.5, -20.3] | 0.174 | 10.26 | -29.86 | -494.44 | 15221.3 | -28.75 |
|  | a_short_premium | {"structure": "iron_condor", "theta": 2.0, "wing": 2} | 398 | -17.44 | 360 | 131.4 | -23.72 | [-27.13, -20.41] | 0.136 | 8.79 | -28.84 | -313.42 | 8508.8 | -30.87 |
|  | a_short_premium | {"structure": "iron_butterfly", "theta": 1.1, "wing": 2} | 2269 | -22.65 | 4026 | 1469.0 | -28.39 | [-30.0, -26.99] | 0.273 | 22.44 | -47.48 | -564.52 | 114439.0 | -42.75 |
|  | a_short_premium | {"structure": "iron_butterfly", "theta": 1.25, "wing": 2} | 1871 | -23.73 | 3181 | 1160.7 | -29.88 | [-31.42, -28.24] | 0.241 | 20.79 | -46.01 | -564.52 | 95073.6 | -44.37 |
|  | a_short_premium | {"structure": "iron_butterfly", "theta": 1.5, "wing": 2} | 1292 | -24.91 | 1952 | 712.3 | -31.22 | [-33.1, -29.45] | 0.191 | 18.33 | -42.93 | -321.21 | 60926.0 | -45.55 |
|  | a_short_premium | {"structure": "iron_butterfly", "theta": 1.75, "wing": 2} | 840 | -27.91 | 1054 | 384.6 | -33.45 | [-35.86, -31.01] | 0.145 | 15.41 | -41.75 | -321.21 | 35238.0 | -48.05 |
|  | c_v2_baseline | {"momentum": -0.05, "vol_cap": 1.2} | 92 | 3.39 | 455 | 166.0 | -36.89 | [-43.6, -29.57] | 0.299 | 65.81 | -80.67 | -171.7 | 16805.4 | -56.32 |
|  | a_short_premium | {"structure": "iron_butterfly", "theta": 2.0, "wing": 2} | 567 | -27.07 | 592 | 216.0 | -37.08 | [-40.58, -33.72] | 0.108 | 11.72 | -43.0 | -321.21 | 21930.5 | -51.32 |
|  | c_v2_baseline | {"momentum": -0.1, "vol_cap": 1.2} | 37 | 14.9 | 159 | 58.0 | -39.5 | [-51.37, -27.56] | 0.296 | 61.93 | -82.07 | -141.03 | 6435.7 | -56.37 |
|  | c_v2_baseline | {"momentum": -0.1, "vol_cap": 1.5} | 43 | 11.78 | 233 | 85.0 | -40.24 | [-48.52, -31.2] | 0.279 | 56.21 | -77.55 | -141.03 | 9612.1 | -59.59 |
|  | b_long_vol | {"structure": "strangle", "theta": 0.5} | 4 | 674.64 | 4 | 1.5 | -40.34 | [-59.01, -21.67] | 0.0 | None | -40.34 | -65.38 | 96.0 | -64.86 |
|  | c_v2_baseline | {"momentum": -0.05, "vol_cap": 1.5} | 125 | -6.39 | 672 | 245.2 | -40.51 | [-45.83, -34.93] | 0.271 | 60.17 | -77.9 | -182.35 | 27243.1 | -61.12 |
|  | b_long_vol | {"structure": "straddle", "theta": 0.5} | 4 | 302.53 | 4 | 1.5 | -45.7 | [-76.58, -26.21] | 0.0 | None | -45.7 | -91.8 | 160.4 | -65.06 |
|  | a_short_premium | {"structure": "iron_butterfly", "theta": 1.1, "wing": 1} | 1932 | -62.21 | 3440 | 1255.2 | -80.47 | [-83.44, -77.55] | 0.142 | 48.8 | -101.89 | -933.33 | 277042.0 | -116.55 |
|  | a_short_premium | {"structure": "iron_butterfly", "theta": 1.25, "wing": 1} | 1584 | -64.31 | 2686 | 980.1 | -83.25 | [-86.64, -79.95] | 0.115 | 46.17 | -100.14 | -933.33 | 223619.7 | -119.43 |
|  | a_short_premium | {"structure": "iron_butterfly", "theta": 1.5, "wing": 1} | 1066 | -69.62 | 1597 | 582.7 | -87.04 | [-91.03, -82.99] | 0.075 | 39.8 | -97.26 | -933.33 | 138955.2 | -122.79 |
|  | a_short_premium | {"structure": "iron_butterfly", "theta": 1.75, "wing": 1} | 682 | -76.3 | 839 | 306.1 | -91.59 | [-97.52, -86.16] | 0.045 | 34.89 | -97.59 | -933.33 | 76820.5 | -126.68 |
|  | a_short_premium | {"structure": "iron_butterfly", "theta": 2.0, "wing": 1} | 453 | -74.91 | 451 | 164.6 | -91.64 | [-98.5, -85.07] | 0.031 | 32.62 | -95.63 | -883.33 | 41305.6 | -131.07 |

## Calibration (held-out, c=0.5): stated probability band vs realized hit rate

- e_analyst_drift {"action": "up"}: 0.4-0.6: n=2812 realized 0.49
- b_long_vol {"structure": "strangle", "theta": 0.65}: 0.4-0.6: n=4 realized 0.5; 0.6-0.8: n=5 realized 0.0; 0.8-1.0: n=1 realized 0.0
- d_post_earnings_drift {"theta_tau": 2.0}: 0.4-0.6: n=772 realized 0.51
- d_post_earnings_drift {"theta_tau": 1.5}: 0.4-0.6: n=1404 realized 0.51
- d_post_earnings_drift {"theta_abs": 0.08}: 0.4-0.6: n=1072 realized 0.5
- e_analyst_drift {"action": "both"}: 0.4-0.6: n=5365 realized 0.5
- d_post_earnings_drift {"theta_tau": 1.0}: 0.4-0.6: n=2431 realized 0.5
- d_post_earnings_drift {"theta_abs": 0.05}: 0.4-0.6: n=2089 realized 0.5
- e_analyst_drift {"action": "down"}: 0.4-0.6: n=2553 realized 0.52
- b_long_vol {"structure": "strangle", "theta": 0.8}: 0.2-0.4: n=9 realized 0.22; 0.4-0.6: n=69 realized 0.33; 0.6-0.8: n=5 realized 0.0; 0.8-1.0: n=1 realized 0.0
- b_long_vol {"structure": "straddle", "theta": 0.8}: 0.2-0.4: n=3 realized 0.0; 0.4-0.6: n=73 realized 0.45; 0.6-0.8: n=8 realized 0.25; 0.8-1.0: n=2 realized 0.0
- b_long_vol {"structure": "straddle", "theta": 0.65}: 0.4-0.6: n=1 realized 0.0; 0.6-0.8: n=7 realized 0.29; 0.8-1.0: n=2 realized 0.0
- b_long_vol {"structure": "straddle", "theta": 0.9}: 0.2-0.4: n=16 realized 0.12; 0.4-0.6: n=199 realized 0.36; 0.6-0.8: n=8 realized 0.25; 0.8-1.0: n=2 realized 0.0
- b_long_vol {"structure": "strangle", "theta": 0.9}: 0.0-0.2: n=3 realized 0.0; 0.2-0.4: n=110 realized 0.25; 0.4-0.6: n=101 realized 0.3; 0.6-0.8: n=5 realized 0.0; 0.8-1.0: n=1 realized 0.0
- a_short_premium {"structure": "iron_condor", "theta": 1.1, "wing": 2}: 0.4-0.6: n=25 realized 0.08; 0.6-0.8: n=1651 realized 0.39; 0.8-1.0: n=1324 realized 0.28
- a_short_premium {"structure": "iron_condor", "theta": 1.25, "wing": 2}: 0.4-0.6: n=11 realized 0.0; 0.6-0.8: n=936 realized 0.31; 0.8-1.0: n=1323 realized 0.28
- a_short_premium {"structure": "iron_condor", "theta": 1.5, "wing": 2}: 0.4-0.6: n=1 realized 0.0; 0.6-0.8: n=173 realized 0.06; 0.8-1.0: n=1144 realized 0.24
- a_short_premium {"structure": "iron_condor", "theta": 1.75, "wing": 2}: 0.6-0.8: n=16 realized 0.0; 0.8-1.0: n=650 realized 0.18
- a_short_premium {"structure": "iron_condor", "theta": 2.0, "wing": 2}: 0.6-0.8: n=4 realized 0.0; 0.8-1.0: n=356 realized 0.14
- a_short_premium {"structure": "iron_butterfly", "theta": 1.1, "wing": 2}: 0.0-0.2: n=127 realized 0.0; 0.2-0.4: n=270 realized 0.02; 0.4-0.6: n=1589 realized 0.27; 0.6-0.8: n=1759 realized 0.34; 0.8-1.0: n=281 realized 0.22
- a_short_premium {"structure": "iron_butterfly", "theta": 1.25, "wing": 2}: 0.0-0.2: n=102 realized 0.0; 0.2-0.4: n=201 realized 0.02; 0.4-0.6: n=887 realized 0.15; 0.6-0.8: n=1710 realized 0.34; 0.8-1.0: n=281 realized 0.22
- a_short_premium {"structure": "iron_butterfly", "theta": 1.5, "wing": 2}: 0.0-0.2: n=75 realized 0.0; 0.2-0.4: n=101 realized 0.0; 0.4-0.6: n=343 realized 0.04; 0.6-0.8: n=1152 realized 0.26; 0.8-1.0: n=281 realized 0.22
- a_short_premium {"structure": "iron_butterfly", "theta": 1.75, "wing": 2}: 0.0-0.2: n=43 realized 0.0; 0.2-0.4: n=45 realized 0.0; 0.4-0.6: n=143 realized 0.01; 0.6-0.8: n=542 realized 0.17; 0.8-1.0: n=281 realized 0.22
- c_v2_baseline {"momentum": -0.05, "vol_cap": 1.2}: 0.2-0.4: n=385 realized 0.28; 0.4-0.6: n=70 realized 0.39
- a_short_premium {"structure": "iron_butterfly", "theta": 2.0, "wing": 2}: 0.0-0.2: n=25 realized 0.0; 0.2-0.4: n=30 realized 0.0; 0.4-0.6: n=67 realized 0.0; 0.6-0.8: n=208 realized 0.06; 0.8-1.0: n=262 realized 0.19
- c_v2_baseline {"momentum": -0.1, "vol_cap": 1.2}: 0.2-0.4: n=139 realized 0.28; 0.4-0.6: n=20 realized 0.4
- c_v2_baseline {"momentum": -0.1, "vol_cap": 1.5}: 0.0-0.2: n=3 realized 0.0; 0.2-0.4: n=201 realized 0.27; 0.4-0.6: n=29 realized 0.34
- b_long_vol {"structure": "strangle", "theta": 0.5}: 0.6-0.8: n=3 realized 0.0; 0.8-1.0: n=1 realized 0.0
- c_v2_baseline {"momentum": -0.05, "vol_cap": 1.5}: 0.0-0.2: n=9 realized 0.11; 0.2-0.4: n=564 realized 0.26; 0.4-0.6: n=99 realized 0.36
- b_long_vol {"structure": "straddle", "theta": 0.5}: 0.6-0.8: n=2 realized 0.0; 0.8-1.0: n=2 realized 0.0
- a_short_premium {"structure": "iron_butterfly", "theta": 1.1, "wing": 1}: 0.0-0.2: n=223 realized 0.0; 0.2-0.4: n=851 realized 0.06; 0.4-0.6: n=2006 realized 0.2; 0.6-0.8: n=329 realized 0.12; 0.8-1.0: n=31 realized 0.03
- a_short_premium {"structure": "iron_butterfly", "theta": 1.25, "wing": 1}: 0.0-0.2: n=165 realized 0.0; 0.2-0.4: n=566 realized 0.03; 0.4-0.6: n=1595 realized 0.16; 0.6-0.8: n=329 realized 0.12; 0.8-1.0: n=31 realized 0.03
- a_short_premium {"structure": "iron_butterfly", "theta": 1.5, "wing": 1}: 0.0-0.2: n=95 realized 0.0; 0.2-0.4: n=255 realized 0.02; 0.4-0.6: n=890 realized 0.09; 0.6-0.8: n=326 realized 0.11; 0.8-1.0: n=31 realized 0.03
- a_short_premium {"structure": "iron_butterfly", "theta": 1.75, "wing": 1}: 0.0-0.2: n=50 realized 0.0; 0.2-0.4: n=106 realized 0.01; 0.4-0.6: n=359 realized 0.02; 0.6-0.8: n=293 realized 0.1; 0.8-1.0: n=31 realized 0.03
- a_short_premium {"structure": "iron_butterfly", "theta": 2.0, "wing": 1}: 0.0-0.2: n=32 realized 0.0; 0.2-0.4: n=49 realized 0.0; 0.4-0.6: n=138 realized 0.01; 0.6-0.8: n=201 realized 0.06; 0.8-1.0: n=31 realized 0.03

## Coverage

- 2022 ok: 1878
- 2022 skip:no expirations returned: 50
- 2022 skip:no priced ATM pair on the pre session: 11
- 2022 skip:no stored close for the pre or post sess: 5
- 2023 ok: 1891
- 2023 skip:no expirations returned: 39
- 2023 skip:no priced ATM pair on the pre session: 24
- 2023 skip:no stored close for the pre or post sess: 8
- 2024 ok: 1935
- 2024 skip:error: peer closed connection without se: 1
- 2024 skip:no expirations returned: 31
- 2024 skip:no priced ATM pair on the pre session: 8
- 2024 skip:no stored close for the pre or post sess: 4
- 2025 ok: 1964
- 2025 skip:no expirations returned: 20
- 2025 skip:no priced ATM pair on the pre session: 5
- 2025 skip:no stored close for the pre or post sess: 3
- 2026 ok: 1476
- 2026 skip:no expirations returned: 9
- 2026 skip:no priced ATM pair on the pre session: 4
- 2026 skip:no stored close for the pre or post sess: 2


## 5. Verdicts

- **a. Options overpriced (short premium): fails everywhere.** Every θ and both structures lose 20 to 90 dollars per $100 risked with intervals far from zero, in both halves. The straddle is dear before earnings, but the gap it is paid for arrives often enough that selling it loses after the spread; the higher the threshold, the worse (the richest straddles sit on the stocks that gap the most).
- **b. Options underpriced (long vol): fails.** The threshold variants with trades (θ = 0.8, 0.9) are negative out of sample; the stricter ones (θ ≤ 0.65) have 4-10 held-out trades, too few to judge, and their fit-period figures are a handful of outliers.
- **c. The v2 rule: fails held out.** On 2022-2023 it looked good (+14.9 per $100, 37 trades, the stock up 5 sessions later 57% of the time); on 2024-2026 the same spread lost -39.5 per $100 (95% interval [-51.37, -27.56], 159 trades, 58.0 a year), win rate 30%, and the stock itself was up 5 sessions later only 50% of the time with a mean move of -0.09%. The momentum-reversal edge that chose the rule did not survive the held-out years. (Ivy's live gates, a confirmed date in a short window and one open pick per name, make her pick far less often than this backtest trades, but they do not change the direction of the result.)
- **d. Post-earnings drift: no edge against the index.** Every variant sits within a fraction of a dollar of zero per $100 over 20 sessions, intervals straddling zero.
- **e. Analyst upgrade drift: passes the arithmetic, fails the business.** +0.41 per $100 over 20 sessions against the index (interval 0.06 to 0.75, 2,812 held-out trades, win rate 49%, calibration band 0.4-0.6 realized 0.49). It is real but thin: four tenths of a percent over a month, before financing, from upgrades sourced from Yahoo without a licence. Downgrades carry nothing. Not shippable.

## 6. Recommendation for Ivy's rule

**None passes.** No options structure in these families earns a rare, arithmetic-first pick on 2024-2026 after costs, and the v2 rule's
own edge reversed out of sample. The honest rule for Ivy v3 is to keep publishing her reasoning and her ledger but to make no options
pick from these setups; if she must act, the only held-out positive is a stock position after an analyst upgrade, which is too small to
matter and rests on an unlicensed source. What would change this: (1) a licensed analyst-action feed, then a 20-session index-relative
upgrade position sized small, graded on calibration; (2) a different family altogether (for example, the post-report straddle's decay
over the next week, or dispersion across a sector), pre-registered the same way; (3) more years: 2022-2023 held out by themselves
would have passed the v2 rule, which is exactly why a two-year fit window should never ship a rule.

## 7. Three real held-out picks of the best passing variant (the first, the middle and the last, chosen before looking at them)

**HBAN · 2024-01-02 · Barclays upgrades to Equal-Weight from Underweight, target $15.0**
- What the options charged: nothing bought. This is a stock position, $11.50 a share at the 2024-01-02 close, held 20 sessions to 2024-01-31.
- What the stock's history says: across the 1,944 upgrades before this one, the upgraded stock beat the index over the next 20 sessions 49% of the time, by 0.16% on average.
- Probability stated: 49%. Expected value: $0.16 per $100, after a 10 bp round trip.
- The outcome that loses: the stock trails the S&P 500 over the 20 sessions.
- How it settled: $11.50 to $11.39 (-1.0%) while the index moved +2.2%: -3.2% against the index, -3.28 per $100 after costs.
**CHD · 2025-04-15 · B of A Securities upgrades to Buy from Neutral, target $125.0**
- What the options charged: nothing bought. This is a stock position, $103.07 a share at the 2025-04-15 close, held 20 sessions to 2025-05-14.
- What the stock's history says: across the 3,350 upgrades before this one, the upgraded stock beat the index over the next 20 sessions 48% of the time, by 0.06% on average.
- Probability stated: 48%. Expected value: $0.06 per $100, after a 10 bp round trip.
- The outcome that loses: the stock trails the S&P 500 over the 20 sessions.
- How it settled: $103.07 to $91.39 (-11.3%) while the index moved +9.3%: -20.6% against the index, -20.73 per $100 after costs.
**CPRT · 2026-09-11 · Barrington Research upgrades to Outperform from Market Perform, target $40.0**
- What the options charged: nothing bought. This is a stock position, $29.95 a share at the 2026-09-11 close, held 20 sessions to 2026-10-09.
- What the stock's history says: across the 4,755 upgrades before this one, the upgraded stock beat the index over the next 20 sessions 49% of the time, by 0.31% on average.
- Probability stated: 49%. Expected value: $0.31 per $100, after a 10 bp round trip.
- The outcome that loses: the stock trails the S&P 500 over the 20 sessions.
- How it settled: $29.95 to $27.32 (-8.8%) while the index moved +2.1%: -10.9% against the index, -11.00 per $100 after costs.

All three lost. That is what a 49% win rate and a +0.4% average look like pick by pick: the average comes from the tails, not from any
pick a reader would recognise as right.

## Research check: short premium two more ways (held-out 2024-2026)

| structure | θ | wing | mode | n | EV/$100 | 95% CI | win | median spread/mid of legs |
|---|---|---|---|---|---|---|---|---|
| iron_butterfly | 1.1 | 1 | expiry_no_exit_cost | 3486 | -39.28 | [-42.71, -36.0] | 0.324 | 0.225 |
| iron_butterfly | 1.1 | 1 | mid_to_mid | 2220 | 1.93 | [-1.26, 5.13] | 0.522 | 0.218 |
| iron_butterfly | 1.1 | 2 | expiry_no_exit_cost | 4101 | -14.98 | [-16.82, -13.17] | 0.45 | 0.319 |
| iron_butterfly | 1.1 | 2 | mid_to_mid | 4119 | 1.11 | [-0.38, 2.5] | 0.594 | 0.333 |
| iron_butterfly | 1.25 | 1 | expiry_no_exit_cost | 2715 | -41.8 | [-45.86, -38.07] | 0.314 | 0.247 |
| iron_butterfly | 1.25 | 1 | mid_to_mid | 1701 | 2.07 | [-1.35, 5.26] | 0.527 | 0.238 |
| iron_butterfly | 1.25 | 2 | expiry_no_exit_cost | 3232 | -16.17 | [-18.19, -14.09] | 0.442 | 0.353 |
| iron_butterfly | 1.25 | 2 | mid_to_mid | 3262 | 1.27 | [-0.3, 2.77] | 0.6 | 0.375 |
| iron_butterfly | 1.5 | 1 | expiry_no_exit_cost | 1610 | -47.19 | [-51.8, -42.04] | 0.298 | 0.273 |
| iron_butterfly | 1.5 | 1 | mid_to_mid | 985 | 3.99 | [0.27, 8.07] | 0.547 | 0.267 |
| iron_butterfly | 1.5 | 2 | expiry_no_exit_cost | 1979 | -16.81 | [-19.48, -14.04] | 0.438 | 0.4 |
| iron_butterfly | 1.5 | 2 | mid_to_mid | 2017 | 2.47 | [0.63, 4.32] | 0.614 | 0.405 |
| iron_butterfly | 1.75 | 1 | expiry_no_exit_cost | 843 | -49.07 | [-56.21, -42.27] | 0.302 | 0.293 |
| iron_butterfly | 1.75 | 1 | mid_to_mid | 503 | 4.04 | [-0.69, 8.85] | 0.551 | 0.286 |
| iron_butterfly | 1.75 | 2 | expiry_no_exit_cost | 1069 | -17.77 | [-21.42, -14.15] | 0.43 | 0.417 |
| iron_butterfly | 1.75 | 2 | mid_to_mid | 1103 | 3.99 | [1.57, 6.38] | 0.633 | 0.462 |
| iron_butterfly | 2.0 | 1 | expiry_no_exit_cost | 451 | -46.93 | [-55.95, -38.47] | 0.313 | 0.304 |
| iron_butterfly | 2.0 | 1 | mid_to_mid | 271 | 2.47 | [-3.69, 8.32] | 0.565 | 0.295 |
| iron_butterfly | 2.0 | 2 | expiry_no_exit_cost | 600 | -17.82 | [-22.76, -13.11] | 0.442 | 0.462 |
| iron_butterfly | 2.0 | 2 | mid_to_mid | 623 | 2.82 | [-0.68, 6.49] | 0.636 | 0.5 |
| iron_condor | 1.1 | 2 | expiry_no_exit_cost | 3068 | -10.75 | [-12.45, -9.0] | 0.653 | 0.383 |
| iron_condor | 1.1 | 2 | mid_to_mid | 3862 | 0.86 | [-0.32, 2.06] | 0.65 | 0.5 |
| iron_condor | 1.25 | 2 | expiry_no_exit_cost | 2317 | -11.2 | [-13.33, -9.29] | 0.656 | 0.4 |
| iron_condor | 1.25 | 2 | mid_to_mid | 3029 | 1.21 | [-0.15, 2.52] | 0.648 | 0.545 |
| iron_condor | 1.5 | 2 | expiry_no_exit_cost | 1342 | -10.17 | [-12.84, -7.7] | 0.668 | 0.444 |
| iron_condor | 1.5 | 2 | mid_to_mid | 1839 | 2.64 | [0.98, 4.15] | 0.654 | 0.62 |
| iron_condor | 1.75 | 2 | expiry_no_exit_cost | 677 | -10.22 | [-13.74, -6.8] | 0.671 | 0.475 |
| iron_condor | 1.75 | 2 | mid_to_mid | 975 | 4.15 | [1.95, 6.3] | 0.653 | 0.667 |
| iron_condor | 2.0 | 2 | expiry_no_exit_cost | 366 | -8.65 | [-13.86, -3.91] | 0.694 | 0.462 |
| iron_condor | 2.0 | 2 | mid_to_mid | 532 | 2.98 | [-0.49, 6.28] | 0.643 | 0.667 |

Reading: held to expiration with the entry at the bid and ask and no exit cost, short premium still loses 9 to 49 dollars per $100 risked
at every threshold (the wide wings, w = 1, are the worst: the structure keeps little width at risk and pays the full gap). Mid-to-mid with no
spread at all, the upper bound no trader can reach, the same structures make +1 to +4 per $100, and only four of the thirty variants clear zero
at the 95% level (iron condor θ 1.5 and 1.75, iron butterfly w = 2 at θ 1.5 and 1.75). The legs these structures need are illiquid before a
report: the median bid-ask on a leg is 22% to 67% of its mid, wider at the higher thresholds. So the costs drove the sign, and the idea alone,
at zero cost, is worth one to four dollars per $100 before paying a spread that is several times that: no threshold makes it tradable.
