from dataclasses import replace
import sqlite3
import pytest
from gold_digger.database import publish_database,load_database,wowhead_url
from gold_digger.models import Recipe,Ingredient
from gold_digger.presentation import recipe_matches,components_table
from gold_digger.build_database import leveling_data


def inputs():
    r=Recipe('tailoring:1','Sac','Couture',(Ingredient(1,2,'Fil'),),(Ingredient(2,1,'Sac'),),'https://source/recipe','build',skill_required=40,skill_basis='Documenté',skill_source='https://source/skills')
    items={1:{'name_fr':'Fil','name_en':'Thread','source':'https://source/items','build':'build'},2:{'name_fr':'Sac','name_en':'Bag','source':'https://source/items','build':'build'}}
    data={'schema_version':2,'vendor_prices':{'2':{'sell_copper':50,'source':'https://source/2','build':'build'}}}
    o={'item_id':1,'vendor':'Vendeur','lot_price_copper':10,'lot_quantity':1,'unlimited':True,'source':'https://source/vendors','observed_builds':'old-build','price_basis':'Observation'}
    return data,[r],items,[o]


def test_sqlite_roundtrip_foreign_keys_and_readonly(tmp_path):
    path=tmp_path/'test.sqlite'
    data,rs,items,offers=inputs()
    publish_database(path,data,rs,items,offers)
    d,r=load_database(path)
    assert r==rs
    assert d['items'][1]['name_fr']=='Fil'
    assert d['merchant_offers'][1][0]['lot_price_copper']==10
    assert d['vendor_prices']['2']['sell_copper']==50
    with sqlite3.connect(path) as connection:
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        assert connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_invalid_rebuild_keeps_previous_database(tmp_path):
    path=tmp_path/'test.sqlite'
    data,rs,items,offers=inputs()
    publish_database(path,data,rs,items,offers)
    original=path.read_bytes()
    offers[0]['lot_quantity']=0
    with pytest.raises(sqlite3.IntegrityError):
        publish_database(path,data,rs,items,offers)
    assert path.read_bytes()==original


def test_missing_item_ref_rejected(tmp_path):
    data,rs,items,offers=inputs()
    del items[1]
    with pytest.raises(sqlite3.IntegrityError):
        publish_database(tmp_path/'test.sqlite',data,rs,items,offers)


def test_skill_filter_known_and_unknown():
    r=inputs()[1][0]
    assert recipe_matches(r,['Couture'],40,False)
    assert not recipe_matches(r,['Couture'],39,False)
    assert not recipe_matches(r,['Forge'],300,True)
    unknown=replace(r,skill_required=None)
    assert not recipe_matches(unknown,[],300,False)
    assert recipe_matches(unknown,[],300,True)


def test_all_components_include_absent_market_items_and_links():
    _,rs,items,_=inputs()
    rows=components_table(rs[0],items,{}, {},quantity=7)
    assert len(rows)==1 and rows[0]['Pour le lot']==14
    assert rows[0]['Composant']=='Fil' and rows[0]['Stock HDV détaillé']==0
    assert rows[0]['Wowhead']==wowhead_url(1)=='https://www.wowhead.com/forever/fr/item=1'


def test_leveling_data_no_eval():
    with pytest.raises(ValueError):
        leveling_data('<script>alert(1)</script>')


def test_non_numeric_merchant_price_rejected(tmp_path):
    data,rs,items,offers=inputs()
    offers[0]['lot_price_copper']='not-a-price'
    with pytest.raises(sqlite3.IntegrityError):
        publish_database(tmp_path/'test.sqlite',data,rs,items,offers)


def test_french_required_tool_and_trainer_skill():
    from bs4 import BeautifulSoup
    from gold_digger.build_database import french_recipe
    original=inputs()[1][0]
    node=BeautifulSoup("""<li><p class='recipe-title'>Sac</p>
        <p>Composants : Fil</p><p>Requiert Enclume · Marteau de forgeron</p>
        <p>S’apprend auprès des maîtres (compétence 30)</p></li>""",'html.parser').li
    r=french_recipe(original,node,{1:'Fil',2:'Sac',5956:'Marteau de forgeron'},None,'')
    assert r.skill_required==30
    assert r.tools==(Ingredient(5956,1,'Marteau de forgeron'),)
    assert r.ingredients==original.ingredients


def test_item_classification_persists_in_database(tmp_path):
    data,rs,items,offers=inputs()
    items[2].update(class_id=4,subclass_id=3,inventory_type=8)
    publish_database(tmp_path/'items.sqlite',data,rs,items,offers)
    loaded,_=load_database(tmp_path/'items.sqlite')
    assert loaded['items'][2]['class_id']==4
    assert loaded['items'][2]['subclass_id']==3
    assert loaded['items'][2]['inventory_type']==8
    assert loaded['items'][1]['class_id'] is None


def test_disenchant_database_roundtrip_and_material_foreign_key(tmp_path):
    data,rs,items,offers=inputs()
    items[2].update(class_id=4,quality=2,item_level=10)
    data['disenchant_reference']={
        'game':'wow-forever','schema_version':1,'source':'https://source/de','build':'old',
        'evidence':'Estimation','provenance':'Tranches Forever, probabilités Classic',
        'tables':{'1':[dict(item_id=1,probability=1.0,min_quantity=1,max_quantity=2)]},
        'brackets':[dict(class_id=4,quality=2,min_level=5,max_level=15,table_id=1)],
        'overrides':{},'never':[]}
    path=tmp_path/'de.sqlite'
    publish_database(path,data,rs,items,offers)
    loaded,_=load_database(path)
    assert loaded['items'][2]['item_level']==10 and loaded['items'][2]['quality']==2
    de=loaded['disenchant'][2]
    assert de['source']=='https://source/de' and de['build']=='old'
    assert de['evidence']=='Estimation'
    assert de['outcomes'][0]['max_quantity']==2
    original=path.read_bytes()
    data['disenchant_reference']['tables']['1'][0]['item_id']=999
    with pytest.raises(sqlite3.IntegrityError):
        publish_database(path,data,rs,items,offers)
    assert path.read_bytes()==original
