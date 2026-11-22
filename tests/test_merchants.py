from dataclasses import replace
import random
import pytest
from gold_digger.engine import analyze, supply_purchase, purchase, merchant_reference
from gold_digger.models import Ingredient, MarketItem, Recipe, Tier


def offer(price=10,lot=1,**kwargs):
    return {'lot_price_copper':price,'lot_quantity':lot,'unlimited':True,'source':'https://example.test/vendor','vendor_name':'Marchand',**kwargs}


def recipe(quantity=2):
    return Recipe('tailoring:1','Objet','Couture',(Ingredient(1,quantity,'Fil'),),(Ingredient(2,1,'Objet'),),'source','build')


def market(revenue=40):
    return {1:MarketItem(1,'Fil',None,(Tier(5,3),Tier(30,5)),8),2:MarketItem(2,'Objet',revenue,(),0)}


def test_mix_cheap_ah_then_vendor():
    cost,rows=supply_purchase((Tier(5,3),Tier(30,10)),8,offer(10))
    assert cost==65
    assert [(r['channel'],r['quantity']) for r in rows]==[('HDV',3),('Marchand',5)]


def test_ah_cheaper_for_all_items():
    cost,rows=supply_purchase((Tier(5,20),),3,offer(10))
    assert cost==15 and all(r['channel']=='HDV' for r in rows)


def test_buy_whole_pack_and_show_surplus():
    cost,rows=supply_purchase((),2,offer(20,5))
    assert cost==20 and rows[0]['quantity']==5 and rows[0]['surplus']==3


def test_pack_can_be_more_expensive_than_ah_for_one_unit():
    cost,rows=supply_purchase((Tier(6,10),),1,offer(20,5))
    assert cost==6 and rows[0]['channel']=='HDV'


def test_pack_optimizer_matches_exhaustive_purchase():
    rng=random.Random(81)
    for _ in range(300):
        tiers=tuple(Tier(p,rng.randint(1,15)) for p in sorted(rng.sample(range(1,100),3)))
        quantity=rng.randint(1,100)
        lot=rng.randint(1,12)
        price=rng.randint(1,200)
        values=[]
        for packs in range((quantity+lot-1)//lot+1):
            try:
                values.append(purchase(tiers,max(0,quantity-packs*lot))[0]+packs*price)
            except ValueError:
                pass
        cost,rows=supply_purchase(tiers,quantity,offer(price,lot))
        assert cost==min(values)
        assert sum(r['quantity'] for r in rows)>=quantity
        assert sum(r['cost'] for r in rows)==cost


def test_positive_batch_despite_negative_first_craft():
    m=market(revenue=6); del m[1]
    r=analyze(recipe(quantity=1),m,merchant_offers={1:[offer(20,5)]},max_crafts=5)
    assert r.first_profit==-14 and r.crafts==5 and r.profit==10 and r.batch_roi==50
    assert r.unlimited_supply


def test_unlimited_vendor_bounded_by_simulation():
    m=market(); del m[1]
    r=analyze(recipe(),m,merchant_offers={1:[offer(10)]},max_crafts=7)
    assert r.crafts==7 and r.investment==140 and r.profit==140 and r.batch_roi==100


def test_finite_other_ingredient_limits_production():
    m=market(revenue=100)
    m[3]=MarketItem(3,'Pierre',None,(Tier(10,3),),3)
    r=replace(recipe(),ingredients=(Ingredient(1,1),Ingredient(3,2)))
    result=analyze(r,m,merchant_offers={1:[offer()]},max_crafts=20)
    assert result.crafts==1 and not result.unlimited_supply


def test_limited_vendor_or_no_source_not_used():
    assert merchant_reference([offer(unlimited=False)]) is None
    assert merchant_reference([offer(source='')]) is None
    assert merchant_reference([offer(-1)]) is None


def test_conservative_and_best_price_are_explicit():
    offers=[offer(10),offer(9),offer(50,5)]
    assert merchant_reference(offers)['lot_price_copper']==10
    assert merchant_reference(offers,'best')['lot_price_copper']==9


def test_cooldown_caps_one_activation():
    r=analyze(replace(recipe(),cooldown_seconds=60),market(),merchant_offers={1:[offer()]},max_crafts=100)
    assert r.status=='Cooldown' and r.crafts==1


@pytest.mark.parametrize('limit',[0,-1,10001,True])
def test_bad_simulation_limit(limit):
    with pytest.raises(ValueError):
        analyze(recipe(),market(),max_crafts=limit)
