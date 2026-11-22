from dataclasses import replace
import json
import sqlite3
import pytest
from gold_digger.models import Ingredient,Recipe,Result,MarketItem,Tier
from gold_digger.engine import analyze
from gold_digger.collect_timings import milliseconds,parse_timings,match_timing
from gold_digger.build_database import attach_timings
from gold_digger.database import publish_database,load_database


def recipe():
    return Recipe('tailoring:1','Sac','Couture',(Ingredient(1,1,'Fil'),),(Ingredient(2,3,'Sac'),),'recipe-source','current-build',cast_time_ms=2000,timing_source='timing-source',timing_build='old-build')


def test_net_gold_rate_uses_casts_not_number_of_items():
    r=Result(recipe(),'Rentable',crafts=30,profit=10000)
    assert r.crafting_time_ms==60000
    assert r.gold_per_minute==1.0


def test_known_cooldown_in_reference_cycle():
    r=Result(replace(recipe(),cooldown_seconds=3600),'Cooldown',crafts=1,profit=10000)
    assert r.crafting_time_ms==2000 and r.reference_time_ms==3600000
    assert r.gold_per_minute==pytest.approx(1/60)


@pytest.mark.parametrize('duration',[None,0])
def test_unknown_and_instant_never_infinite(duration):
    r=Result(replace(recipe(),cast_time_ms=duration),'Rentable',crafts=1,profit=1000)
    assert r.gold_per_minute is None and r.reference_time_ms is None


def test_no_profitable_lot_has_no_rate():
    assert Result(recipe(),'Non rentable',crafts=0,profit=0).gold_per_minute is None


def test_decimal_cast_time():
    assert milliseconds(5.125)==5125
    for value in [-1,'NaN','Infinity',True,'abc',0.00001]:
        with pytest.raises(ValueError):
            milliseconds(value)


def test_nested_source_payload():
    data={'version':'forever','profession':'tailoring','recipes':[{'id':1,'castTime':5.125}]}
    tree=['$', 'section',None,{'children':['$','component',None,{'data':data}]}]
    chunk='1:'+json.dumps(tree)+'\n'
    html='<p>recipes from the WoW Forever client 1.60.1.70888.</p><script>self.__next_f.push('+json.dumps([1,chunk])+')</script>'
    build,records=parse_timings(html,'tailoring')
    assert build=='1.60.1.70888' and records[0]['castTime']==5.125
    with pytest.raises(ValueError):
        parse_timings(html,'alchemy')


def raw_recipe():
    return {'id':1,'castTime':5.125,'reagents':[{'item':1,'quantity':1}],'creates':[{'item':2,'min':3,'max':3}]}


def test_match_identity_reagents_output_and_unknown_cooldown():
    r=recipe(); raw=raw_recipe()
    timing=match_timing(r,raw,'old-build')
    assert timing['cast_time_ms']==5125 and timing['cooldown_seconds'] is None
    for change in [{'id':2},{'reagents':[{'item':1,'quantity':2}]},{'creates':[{'item':2,'min':2,'max':3}]},{'castTime':None}]:
        with pytest.raises(ValueError):
            match_timing(r,{**raw,**change},'old-build')


def test_stale_timing_does_not_attach_after_recipe_change():
    r=replace(recipe(),cast_time_ms=None,timing_source='',timing_build='')
    timing=match_timing(r,raw_recipe(),'old-build')
    payload={'game':'wow-forever','schema_version':1,'timings':[timing]}
    assert attach_timings([r],payload)[0].cast_time_ms==5125
    assert attach_timings([replace(r,build='new-build')],payload)[0].cast_time_ms is None
    with pytest.raises(ValueError):
        attach_timings([r],{**payload,'timings':[timing,timing]})


def test_rate_optimization_chooses_fast_profit_instead_of_max_total():
    r=replace(recipe(),outputs=(Ingredient(2,1),))
    market={1:MarketItem(1,'Fil',None,(Tier(1,3),Tier(9,97)),100),2:MarketItem(2,'Sac',10,(),0)}
    total=analyze(r,market,max_crafts=100)
    rate=analyze(r,market,max_crafts=100,objective='rate')
    assert total.crafts==100 and rate.crafts==3
    assert total.profit>rate.profit and rate.gold_per_minute>total.gold_per_minute
    assert rate.analysis_limit==100
    # Même choix en présence d'un marchand plus cher que les paliers.
    offers={1:[{'unlimited':True,'source':'source','lot_price_copper':20,'lot_quantity':1}]}
    assert analyze(r,market,merchant_offers=offers,max_crafts=100,objective='rate').crafts==3


def test_rate_optimization_can_amortize_vendor_pack():
    r=replace(recipe(),outputs=(Ingredient(2,1),))
    market={2:MarketItem(2,'Sac',6,(),0)}
    offers={1:[{'unlimited':True,'source':'source','lot_price_copper':20,'lot_quantity':5}]}
    result=analyze(r,market,merchant_offers=offers,max_crafts=7,objective='rate')
    assert result.crafts==5 and result.first_profit<0 and result.profit==10


def test_timing_sqlite_roundtrip_and_provenance(tmp_path):
    path=tmp_path/'catalog.sqlite'
    r=recipe()
    items={i:{'name_fr':str(i),'source':'items','build':'current-build'} for i in (1,2)}
    publish_database(path,{'schema_version':2},[r],items,[])
    data,recipes=load_database(path)
    assert recipes[0].cast_time_ms==2000
    assert recipes[0].timing_build=='old-build' and recipes[0].build=='current-build'
    assert data['schema_version']==5
    with sqlite3.connect(path) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0]==5
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()


def test_v2_database_can_still_be_read(tmp_path):
    path=tmp_path/'catalog.sqlite'
    r=recipe()
    items={i:{'name_fr':str(i),'source':'items','build':'current-build'} for i in (1,2)}
    publish_database(path,{},[r],items,[])
    with sqlite3.connect(path) as c:
        c.execute('DROP TABLE recipe_timings')
        c.execute('PRAGMA user_version=2')
        c.execute('UPDATE metadata SET value=? WHERE key=?',('2','schema_version'))
    assert load_database(path)[1][0].cast_time_ms is None


def test_rate_request_without_duration_keeps_normal_profit_analysis():
    r=replace(recipe(),outputs=(Ingredient(2,1),),cast_time_ms=None)
    market={1:MarketItem(1,'Fil',None,(Tier(1,3),Tier(9,97)),100),2:MarketItem(2,'Sac',10,(),0)}
    result=analyze(r,market,max_crafts=100,objective='rate')
    assert result.crafts==100 and result.gold_per_minute is None
