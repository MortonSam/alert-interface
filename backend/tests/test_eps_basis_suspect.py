"""Validate flags EPS rows whose surprise looks like a GAAP-vs-adjusted basis mismatch."""
from app.scripts.validate_data import EPS_BASIS_SUSPECT_MIN_ROWS, PASS, WARN, eps_basis_suspect_result


def test_clean_rows_pass():
    out = eps_basis_suspect_result([("AAPL", "Tech", 1.52, 1.43), ("MSFT", "Tech", 2.93, 2.78)])
    assert out.level == PASS


def test_beyond_100_and_opposite_sign_count_and_tickers_with_3_are_listed():
    rows = [
        ("UBER", "Industrials", 3.21, 0.48),     # +569%
        ("UBER", "Industrials", 3.11, 0.69),     # +351%
        ("UBER", "Industrials", -0.21, 0.06),    # opposite sign, estimate under the dollar floor
        ("PLD", "Real Estate", 1.46, 0.68),      # +115%
        ("PLD", "Real Estate", 1.37, 0.68),      # +101%
        ("AAPL", "Tech", 1.52, 1.43),            # clean
        ("BE", "Industrials", 0.27, 0.11),       # +145%
        ("BE", "Industrials", 0.15, -0.04),      # opposite sign
        ("BE", "Industrials", -0.01, 0.08),      # opposite sign
        ("BE", "Industrials", 0.12, 0.11),       # clean
    ]
    out = eps_basis_suspect_result(rows)
    assert out.level == WARN
    assert out.message.startswith("8 earnings row(s) across 3 ticker(s)")
    assert out.rows == ["BE (Industrials): 3 row(s)", "UBER (Industrials): 3 row(s)"]
    assert EPS_BASIS_SUSPECT_MIN_ROWS == 3


def test_exactly_100_percent_is_not_beyond():
    out = eps_basis_suspect_result([("X", None, 2.0, 1.0)])   # +100.0%, not beyond
    assert out.level == PASS
    out = eps_basis_suspect_result([("X", None, 2.01, 1.0)])
    assert out.level == WARN and out.rows == []               # counted, but under 3 rows so not listed
