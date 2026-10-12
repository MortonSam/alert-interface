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
