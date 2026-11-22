from dataclasses import replace
import random
import pytest
from gold_digger.engine import analyze, purchase
from gold_digger.models import Ingredient, MarketItem, Recipe, Tier


def recipe(**kwargs):
    base = Recipe("test:1", "Objet", "Couture", (Ingredient(1, 2),),
                  (Ingredient(2, 1),), "https://example.test/recipe", "test-build")
    return replace(base, **kwargs)


def market(tiers=(Tier(10, 3), Tier(30, 5)), npc=50):
    return {1: MarketItem(1, "Composant", None, tiers, sum(t.quantity for t in tiers)),
            2: MarketItem(2, "Objet", npc, (), 0)}


def test_crossing_tiers_stops_before_loss():
    result = analyze(recipe(), market())
    assert (result.first_cost, result.first_profit, result.crafts, result.investment, result.profit) == (20, 30, 2, 60, 40)
    assert result.roi == 150
    assert result.purchases == [
        {"item_id": 1, "name": "Composant", "unit_price": 10, "quantity": 3, "cost": 30},
        {"item_id": 1, "name": "Composant", "unit_price": 30, "quantity": 1, "cost": 30}]


def test_multiple_outputs_and_yield():
    result = analyze(recipe(outputs=(Ingredient(2, 3),)), market())
    assert result.revenue == 150 and result.crafts == 4 and result.profit == 420


@pytest.mark.parametrize("npc", [20, 10])
def test_non_profitable(npc):
    result = analyze(recipe(), market(npc=npc))
    assert result.status == "Non rentable" and result.crafts == 0 and result.investment == 0


def test_zero_marginal_profit_is_excluded():
    result = analyze(recipe(), market(npc=40))
    assert result.crafts == 1


def test_missing_npc_is_not_zero():
    assert analyze(recipe(), market(npc=None)).status == "Données insuffisantes"
    assert analyze(recipe(), market(npc=0)).status == "Exclue"


def test_vendor_price_fallback_and_csv_priority():
    prices = {"2": {"sell_copper": 150, "source": "source", "build": "test-build"}}
    assert analyze(recipe(), market(npc=None), prices).revenue == 150
    assert analyze(recipe(), market(npc=50), prices).revenue == 50
    assert analyze(recipe(), market(npc=0), prices).status == "Exclue"
    prices["2"]["build"] = "wrong"
    assert analyze(recipe(), market(npc=None), prices).revenue is None


def test_missing_ingredient():
    assert analyze(recipe(), {}).status == "Données insuffisantes"
    m = market(); del m[1]
    assert "Paliers" in analyze(recipe(), m).reason


def test_insufficient_whole_craft():
    result = analyze(recipe(), market((Tier(10, 1),)))
    assert result.status == "Données insuffisantes" and result.crafts == 0


def test_known_cooldown_one_activation():
    result = analyze(recipe(cooldown_seconds=86400), market())
    assert result.status == "Cooldown" and result.crafts == 1 and result.profit == 30


def test_no_extrapolation_of_total_quantity():
    m = market((Tier(1, 2),))
    m[1] = replace(m[1], total_quantity=10000)
    assert analyze(recipe(), m).crafts == 1


def test_duplicate_ingredients_aggregate():
    result = analyze(recipe(ingredients=(Ingredient(1, 1), Ingredient(1, 1))), market())
    assert result.crafts == 2 and result.profit == 40


def test_independent_market_not_mutated():
    m = market()
    assert analyze(recipe(), m) == analyze(recipe(), m)
    assert m[1].tiers[0].quantity == 3


def test_purchase_insufficient_raises():
    with pytest.raises(ValueError):
        purchase((Tier(1, 2),), 3)


def test_binary_search_matches_brute_force_multiple_reagents():
    rng = random.Random(17)
    for _ in range(150):
        m = {}
        ingredients = []
        for item_id in [1, 3]:
            prices = sorted(rng.sample(range(1, 100), 3))
            tiers = tuple(Tier(p, rng.randint(1, 20)) for p in prices)
            m[item_id] = MarketItem(item_id, str(item_id), None, tiers, sum(t.quantity for t in tiers))
            ingredients.append(Ingredient(item_id, rng.randint(1, 5)))
        revenue = rng.randint(10, 600)
        m[2] = MarketItem(2, "Objet", revenue, (), 0)
        r = recipe(ingredients=tuple(ingredients))
        result = analyze(r, m)
        capacity = min(sum(t.quantity for t in m[i.item_id].tiers) // i.quantity for i in ingredients)
        costs = [sum(purchase(m[i.item_id].tiers, i.quantity*n)[0] for i in ingredients) for n in range(capacity+1)]
        profitable = [n for n in range(1, capacity+1) if costs[n]-costs[n-1] < revenue]
        expected = max(profitable, default=0)
        assert result.crafts == expected
        assert result.profit == expected * revenue - costs[expected]
