"""Vendor ticker conventions and OpenFIGI response parsing."""

from qmf.data.security_master import _row, to_openfigi_ticker


def test_share_class_separator_is_translated():
    # yfinance says BRK-B, OpenFIGI/Bloomberg say BRK/B. Same security.
    assert to_openfigi_ticker("BRK-B") == "BRK/B"
    assert to_openfigi_ticker("BF-B") == "BF/B"


def test_plain_ticker_is_unchanged():
    assert to_openfigi_ticker("AAPL") == "AAPL"


def test_matched_response_is_parsed():
    result = {
        "data": [
            {
                "figi": "BBG000B9XRY4",
                "compositeFIGI": "BBG000B9XRY4",
                "shareClassFIGI": "BBG001S5N8V8",
                "name": "APPLE INC",
                "securityType": "Common Stock",
                "marketSector": "Equity",
            }
        ]
    }
    row = _row("AAPL", "AAPL", "US", result)
    assert row["match_status"] == "matched"
    assert row["figi"] == "BBG000B9XRY4"
    assert row["security_name"] == "APPLE INC"
    assert row["message"] is None


def test_warning_response_is_unmatched():
    row = _row("BRK-B", "BRK-B", "US", {"warning": "No identifier found."})
    assert row["match_status"] == "unmatched"
    assert row["figi"] is None
    assert "No identifier" in row["message"]


def test_row_records_both_conventions():
    """We keep what we sent alongside our canonical ticker — matching must be auditable."""
    row = _row("BRK-B", "BRK/B", "US", {"warning": "x"})
    assert row["ticker"] == "BRK-B"
    assert row["vendor_ticker"] == "BRK/B"
