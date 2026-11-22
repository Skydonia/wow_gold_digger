from dataclasses import replace
import pytest
from gold_digger.auction import estimate_auction
from gold_digger.models import Ingredient, Recipe, Result, MarketItem, Tier


def sample():
    recipe=Recipe('test','Test','Couture',(),(Ingredient(1,3),Ingredient(2,1)),'test','test')
    result=Result(recipe,'Rentable',first_cost=100,crafts=2,investment=200)
    market={1:MarketItem(1,'Un',1,(Tier(100,1),Tier(120,5)),6),
            2:MarketItem(2,'Deux',1,(Tier(50,1),),1)}
    return result,market


def test_all_outputs_and_same_purchase_cost():
    result,market=sample()
    estimate=estimate_auction(result,market,5)
    assert (estimate.gross,estimate.net,estimate.profit)==(700,665,465)
    assert result.investment==200


@pytest.mark.parametrize('fee,expected',[(0,500),(100,-200),(15,395)])
def test_commission_and_negative_profit(fee,expected):
    result,market=sample()
    assert estimate_auction(result,market,fee).profit==expected


def test_missing_price_is_not_zero_or_npc_fallback():
    result,market=sample()
    market[2]=replace(market[2],tiers=())
    estimate=estimate_auction(result,market)
    assert estimate.profit is None and 'Prix HDV absent' in estimate.reason


def test_no_selected_batch_is_unavailable():
    result,market=sample()
    result.crafts=0
    assert estimate_auction(result,market).profit is None


def test_rounding_and_invalid_fee():
    result,market=sample()
    market[2]=replace(market[2],tiers=(Tier(51,1),))
    assert estimate_auction(result,market).net==666
    with pytest.raises(ValueError):
        estimate_auction(result,market,101)


@pytest.mark.parametrize('duration,cooldown,fee,expected',[
    (3000,None,5,0.465),
    (3000,60,5,0.02325),
    (3000,None,100,-0.2),
    (None,None,5,None),
    (0,None,5,None),
])
def test_auction_rate_duration_cooldown_and_loss(duration,cooldown,fee,expected):
    result,market=sample()
    result.recipe=replace(result.recipe,cast_time_ms=duration,cooldown_seconds=cooldown)
    rate=estimate_auction(result,market,fee).gold_per_minute
    if expected is None:
        assert rate is None
    else:
        assert rate==pytest.approx(expected)


def test_auction_rate_requires_price_and_batch():
    result,market=sample()
    result.recipe=replace(result.recipe,cast_time_ms=3000)
    assert estimate_auction(result,{}).gold_per_minute is None
    result.crafts=0
    assert estimate_auction(result,market).gold_per_minute is None
