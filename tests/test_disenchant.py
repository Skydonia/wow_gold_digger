from dataclasses import replace
import json
from pathlib import Path

import pytest

from gold_digger.auction import estimate_auction, profitability, filter_roi
from gold_digger.disenchant import estimate_disenchant, estimate_direct_disenchant, item_profile, validate_reference
from gold_digger.engine import analyze_single
from gold_digger.models import Ingredient, MarketItem, Recipe, Tier


def example():
    recipe = Recipe('test', 'Armure', 'Couture', (Ingredient(1, 2),),
                    (Ingredient(2, 1),), 'source', 'build', cast_time_ms=7000)
    market = {1: MarketItem(1, 'Fil', None, (Tier(100, 20),), 20),
              2: MarketItem(2, 'Armure', 1, (Tier(1, 1),), 1),
              3: MarketItem(3, 'Poussière', None, (Tier(400, 1),), 1),
              4: MarketItem(4, 'Essence', None, (Tier(1000, 1),), 1)}
    profiles = {2: {'outcomes': [
        dict(item_id=3, probability=.8, min_quantity=1, max_quantity=2),
        dict(item_id=4, probability=.2, min_quantity=1, max_quantity=1)],
        'source': 'source', 'evidence': 'Estimation'}}
    return recipe, market, profiles


def test_expected_materials_commission_craft_cost_and_seconds():
    recipe, market, profiles = example()
    result = analyze_single(recipe, market)
    estimate = estimate_disenchant(result, market, profiles)
    # .8 * 1.5 * 400 + .2 * 1000 = 680; 5% commission, 200 craft cost.
    assert estimate.gross == pytest.approx(680)
    assert estimate.net == pytest.approx(646)
    assert estimate.profit == pytest.approx(446)
    assert estimate.duration_ms == 10000
    assert estimate.gold_per_minute == pytest.approx(.2676)
    auction = estimate_auction(result, market)
    assert profitability(result, auction, estimate) == 'Rentable désenchantement'
    assert filter_roi(result, auction, 'Rentables désenchantement', estimate) == pytest.approx(223)
    assert filter_roi(result, auction, 'Rentables', estimate) == pytest.approx(223)
    assert filter_roi(result, auction, 'Rentables PNJ', estimate) < 0


def test_multiple_outputs_and_cooldown_overlap():
    recipe, market, profiles = example()
    recipe = replace(recipe, outputs=(Ingredient(2, 3),))
    result = analyze_single(recipe, market)
    estimate = estimate_disenchant(result, market, profiles)
    assert estimate.gross == pytest.approx(2040)
    assert estimate.duration_ms == 16000
    assert estimate.profit == pytest.approx(1738)
    result.recipe = replace(recipe, cooldown_seconds=60)
    assert estimate_disenchant(result, market, profiles).duration_ms == 60000


def test_missing_material_price_retains_chances_but_not_partial_profit():
    recipe, market, profiles = example()
    del market[4]
    de = estimate_disenchant(analyze_single(recipe, market), market, profiles)
    assert de.profit is None and de.gold_per_minute is None and len(de.outcomes) == 2
    assert 'Prix HDV absent' in de.reason


@pytest.mark.parametrize('cast', [None, 0])
def test_no_rate_without_positive_craft_duration(cast):
    recipe, market, profiles = example()
    result = analyze_single(replace(recipe, cast_time_ms=cast), market)
    de = estimate_disenchant(result, market, profiles)
    assert de.profit == pytest.approx(446) and de.gold_per_minute is None


def test_unknown_output_and_excluded_recipe_cannot_produce_profit():
    recipe, market, profiles = example()
    result = analyze_single(recipe, market)
    assert estimate_disenchant(result, market, {}).profit is None
    result = analyze_single(replace(recipe, exclusion='Inconnue'), market)
    assert estimate_disenchant(result, market, profiles).profit is None
    mixed = replace(recipe, outputs=(Ingredient(2, 1), Ingredient(9, 1)))
    assert estimate_disenchant(analyze_single(mixed, market), market, profiles).profit is None


def test_merchant_cost_and_100_percent_fee():
    recipe, market, profiles = example()
    offer = dict(lot_price_copper=50, lot_quantity=5, unlimited=True, source='source')
    result = analyze_single(recipe, market, merchant_offers={1: [offer]})
    assert result.investment == 50
    assert estimate_disenchant(result, market, profiles).profit == pytest.approx(596)
    assert estimate_disenchant(result, market, profiles, 100).profit == -50


@pytest.mark.parametrize('seconds', [0, -1, float('nan'), float('inf')])
def test_invalid_duration(seconds):
    recipe, market, profiles = example()
    with pytest.raises(ValueError):
        estimate_disenchant(analyze_single(recipe, market), market, profiles, seconds_per_item=seconds)


def reference():
    return json.loads((Path(__file__).resolve().parents[1]/'data/sources/disenchant.json').read_text())


def test_direct_purchase_uses_one_equipment_and_only_disenchant_time():
    _, market, profiles = example()
    del market[1]  # No craft resources: buying the equipment must still work.
    market[2] = replace(market[2], tiers=(Tier(800, 10), Tier(200, 1)))
    direct = estimate_direct_disenchant(2, market, profiles)
    assert direct.purchase_cost == 200
    assert direct.net == pytest.approx(646)
    assert direct.profit == pytest.approx(446)
    assert direct.duration_ms == 3000
    assert direct.gold_per_minute == pytest.approx(.892)
    assert estimate_direct_disenchant(2, market, profiles, seconds_per_item=6).gold_per_minute == pytest.approx(.446)
    assert estimate_direct_disenchant(2, market, profiles, fee_percent=100).profit == -200
    market[2] = replace(market[2], tiers=(Tier(700, 1),))
    assert estimate_direct_disenchant(2, market, profiles).profit == -54


def test_direct_purchase_missing_prices_and_non_disenchantable_items():
    _, market, profiles = example()
    assert estimate_direct_disenchant(2, market, {}).profit is None
    no_stock = {**market, 2: replace(market[2], tiers=())}
    assert estimate_direct_disenchant(2, no_stock, profiles).gold_per_minute is None
    del market[4]
    direct = estimate_direct_disenchant(2, market, profiles)
    assert direct.purchase_cost == 1 and direct.profit is None and direct.outcomes


@pytest.mark.parametrize('craft_unavailable', [False, True])
def test_general_profitability_includes_direct_only_with_its_own_investment(craft_unavailable):
    recipe, market, profiles = example()
    market[1] = replace(market[1], tiers=(Tier(1000, 20),))
    market[2] = replace(market[2], tiers=(Tier(200, 1),))
    if craft_unavailable:
        del market[1]
    result = analyze_single(recipe, market)
    auction = estimate_auction(result, market)
    craft_de = estimate_disenchant(result, market, profiles)
    direct = estimate_direct_disenchant(2, market, profiles)
    assert profitability(result, auction, craft_de, direct) == 'Rentable désenchantement seul'
    assert filter_roi(result, auction, 'Rentables', craft_de, direct) == pytest.approx(223)
    assert filter_roi(result, auction, 'Rentables HDV', craft_de, direct) == (None if craft_unavailable else pytest.approx(-90.5))
    excluded = analyze_single(replace(recipe, exclusion='Craft exclu'), market)
    assert profitability(excluded, estimate_auction(excluded, market), direct=direct) == 'Rentable désenchantement seul'
    loss = replace(direct, profit=-1)
    assert not profitability(result, auction, craft_de, loss).startswith('Rentable ')


def test_source_reference_item_level_boundaries_exceptions_and_exclusions():
    data = reference()
    validate_reference(data)
    armor = dict(class_id=4, quality=2, item_level=35)
    assert item_profile(7915, armor, data) == ('5', '')
    assert item_profile(3484, {**armor, 'item_level': 29}, data) == ('4', '')
    assert item_profile(7915, {**armor, 'item_level': 36}, data) == ('6', '')
    assert item_profile(7915, {**armor, 'class_id': 2}, data) == ('25', '')
    assert item_profile(7915, {**armor, 'quality': 1}, data)[0] is None
    assert item_profile(7915, {**armor, 'item_level': None}, data)[0] is None
    assert item_profile(7344, armor, data) == ('25', '')  # item-specific override
    assert item_profile(11288, {**armor, 'class_id': 2}, data)[0] is None
    assert item_profile(21473, armor, data)[0] is None  # incomplete reference table


def test_reference_rejects_invalid_probabilities_and_overlapping_bands():
    data = reference()
    data['tables']['1'][0]['probability'] = .95
    with pytest.raises(ValueError):
        validate_reference(data)
    data = reference()
    data['brackets'].append(data['brackets'][0])
    with pytest.raises(ValueError):
        validate_reference(data)
