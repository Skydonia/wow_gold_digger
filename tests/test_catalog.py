from gold_digger.import_catalog import parse_profession, parse_vendor_price
import pytest


def html(title, reagents="<a href='/en/wow-forever/items/1'>2 × Composant</a>"):
    return f"""<p>From the WoW Forever client, build 1.60.1.71037.</p>
    <div id='recipes'><section><h2>Reagents</h2><li id='r123' class='recipe'>
    <p class='recipe-title'>{title}</p><p>Reagents: {reagents}</p>
    <p>Needs Forge</p></li></section></div>"""


def test_recipe_fields():
    build, recipes = parse_profession(html("<a href='/en/wow-forever/items/2'>5 × Output</a>"), "engineering")
    r = recipes[0]
    assert build == "1.60.1.71037" and r.outputs[0].quantity == 5
    assert r.ingredients[0].quantity == 2 and r.restrictions == ("Needs Forge",)
    assert r.cooldown_seconds is None


def test_unknown_output_and_variable_yield():
    assert parse_profession(html("<span>Random result</span>"), "engineering")[1][0].exclusion
    assert parse_profession(html("<a href='/en/wow-forever/items/2'>1–3 × Output</a>"), "engineering")[1][0].exclusion


def test_page_layout_failure():
    with pytest.raises(ValueError):
        parse_profession("<h1>Not found</h1>", "engineering")


def test_vendor_price_and_canonical_validation():
    page = """<link rel='canonical' href='https://endgametools.com/en/wow-forever/items/2'>
    <dl><dt>Item ID</dt><dd>2</dd><dt>Client build</dt><dd>build</dd></dl>
    <p>Sell price <span aria-hidden='true'>2</span><span>2 Gold</span>
    <span aria-hidden='true'>3</span><span>3 Silver</span><span>4 Copper</span></p>"""
    assert parse_vendor_price(page, 2, "build")["sell_copper"] == 20304
    assert parse_vendor_price(page, 3, "build") is None
    assert parse_vendor_price(page, 2, "other-build") is None
    assert parse_vendor_price(page.replace("Sell price", "Buy price"), 2, "build") is None


def test_vendor_missing_price_is_unknown():
    assert parse_vendor_price("<h1>Missing item</h1>", 2, "build") is None


def test_output_on_separate_makes_line_and_multiple_yield():
    page=html('<span>Transmute</span>').replace('<p>Needs Forge</p>',"<p><span class='sr-only'>Makes </span>→ <a href='/en/wow-forever/items/2'>3 × Elemental Fire</a></p><p>Needs Forge</p>")
    r=parse_profession(page,'alchemy')[1][0]
    assert not r.exclusion
    assert [(i.item_id,i.quantity) for i in r.outputs]==[(2,3)]
    assert len(r.ingredients)==1
    assert all('Makes' not in t for t in r.restrictions)


def test_number_in_item_name_is_not_variable_yield():
    r=parse_profession(html("<a href='/en/wow-forever/items/274048'>9-60 Battery Pack</a>"),'engineering')[1][0]
    assert not r.exclusion and r.outputs[0].quantity==1
    assert r.ingredients[0].quantity==2


def test_variable_yield_still_excluded_on_makes_line():
    page=html('<span>Random</span>').replace('<p>Needs Forge</p>',"<p>Makes → <a href='/en/wow-forever/items/2'>1–3 × Random</a></p>")
    assert parse_profession(page,'engineering')[1][0].exclusion=='Rendement variable non modélisé'
