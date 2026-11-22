from dataclasses import replace
import pytest
from gold_digger.engine import analyze_single
from gold_digger.auction import estimate_auction
from gold_digger.models import Ingredient, Recipe, MarketItem, Tier


def recipe():
    return Recipe('test','Test','Couture',(Ingredient(1,2),),(Ingredient(2,3),),'source','build',cast_time_ms=3000)


def market(npc=50):
    return {1:MarketItem(1,'Composant',None,(Tier(10,100),),100),
            2:MarketItem(2,'Objet',npc,(Tier(100,10),),10)}


@pytest.mark.parametrize('npc,profit',[(50,130),(5,-5)])
def test_single_craft_even_when_pnj_loses_money(npc,profit):
    result=analyze_single(recipe(),market(npc))
    assert (result.crafts,result.investment,result.profit)==(1,20,profit)
    assert result.batch_roi==profit/20*100
    assert sum(p['cost'] for p in result.purchases)==20
    assert sum(p['quantity'] for p in result.purchases)==2
    assert result.gold_per_minute==pytest.approx(profit*6/3000)
    auction=estimate_auction(result,market(npc))
    assert auction.profit==265
    assert auction.gold_per_minute==pytest.approx(0.53)
    assert result.status==('Rentable' if profit>0 else 'Non rentable')


def test_merchant_pack_is_not_amortized_over_future_crafts():
    offer={'lot_price_copper':100,'lot_quantity':5,'unlimited':True,'source':'source','vendor_name':'Vendeur'}
    m=market(5)
    del m[1]
    result=analyze_single(recipe(),m,merchant_offers={1:[offer]})
    assert (result.crafts,result.investment,result.profit)==(1,100,-85)
    assert result.purchases[0]['quantity']==5
    assert result.purchases[0]['surplus']==3
    assert result.purchases[0]['channel']=='Marchand'


def test_single_craft_cooldown_and_missing_stock():
    result=analyze_single(replace(recipe(),cooldown_seconds=60),market())
    assert result.crafts==1 and result.reference_time_ms==60000
    m=market()
    m[1]=replace(m[1],tiers=(Tier(10,1),),total_quantity=1)
    result=analyze_single(recipe(),m)
    assert result.first_cost is None and result.crafts==0
    assert estimate_auction(result,m).profit is None


@pytest.mark.parametrize('npc',[None,0])
def test_hdv_calculation_does_not_require_pnj_value(npc):
    from gold_digger.auction import profitability, auction_roi, filter_roi
    result=analyze_single(recipe(),market(npc))
    auction=estimate_auction(result,market(npc))
    assert result.crafts==1 and result.investment==20
    assert auction.profit==265
    assert profitability(result,auction)=='Rentable HDV'
    assert auction_roi(result,auction)==1325
    assert filter_roi(result,auction,'Rentables')==1325
    assert filter_roi(result,auction,'Rentables HDV')==1325
    if npc is None:
        assert result.profit is None and result.gold_per_minute is None
    else:
        assert result.profit==-20


def test_missing_hdv_price_is_not_classified_as_a_known_loss():
    from gold_digger.auction import profitability
    m=market(5)
    m[2]=replace(m[2],tiers=())
    result=analyze_single(recipe(),m)
    assert profitability(result,estimate_auction(result,m))=='Données insuffisantes'


def test_recipe_exclusions_still_apply_to_hdv():
    from gold_digger.auction import profitability
    result=analyze_single(replace(recipe(),exclusion='Résultat aléatoire non documenté'),market())
    auction=estimate_auction(result,market())
    assert auction.profit is None
    assert profitability(result,auction)=='Exclue'
