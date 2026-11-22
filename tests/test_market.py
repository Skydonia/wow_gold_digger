from pathlib import Path
import pytest
from gold_digger.market import copper, parse_market, money


def test_decimal_exact():
    assert copper("45.9999") == 459999
    assert copper("0.0001") == 1
    assert money(-12345) == "−1 po 23 pa 45 pc"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "0.00001", "oops"])
def test_bad_price(value):
    with pytest.raises(ValueError):
        copper(value)


def csv(content):
    return ("id;name;npc;first;quantity;min\n" + content).encode("utf-8-sig")


def test_sort_and_aggregate_tiers():
    report = parse_market(csv("1;Test;;0.02x2 0.01x1 0.02x1;4;0.01\n"))
    assert not report.errors
    assert report.items[1].tiers[0].price == 100
    assert report.items[1].tiers[1].quantity == 3
    assert report.items[1].npc is None


def test_bad_row_does_not_hide_good_row():
    report = parse_market(csv("1;Bad;;oops;1;1\n2;Good;0;1x1;1;1\n"))
    assert len(report.errors) == 1 and list(report.items) == [2]


def test_duplicate_id_excluded_entirely():
    report = parse_market(csv("1;A;;1x1;1;1\n1;B;;1x1;1;1\n1;C;;1x1;1;1\n"))
    assert not report.items and len(report.errors) == 2


def test_missing_headers_and_bad_encoding():
    assert parse_market(b"id,name\n1,a").errors
    assert parse_market(b"\xff").errors


def test_invalid_total_quantity():
    assert parse_market(csv("1;Test;;1x2;1;1\n")).errors


def test_supplied_export():
    path = Path(__file__).resolve().parents[1] / "data/input/export_hdv.csv"
    if not path.exists():
        pytest.skip("Export local absent")
    report = parse_market(path.read_bytes())
    assert report.rows == 6907 and len(report.items) == 6907
    assert not report.errors and not report.warnings
    assert report.items[12360].npc == 5000
