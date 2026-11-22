from gold_digger.disenchant_market import analyze_disenchant_market
from gold_digger.models import MarketItem, Tier


def test_scan_equipment_without_any_recipe_and_unknown_profiles():
    market={10:MarketItem(10,'Arme sans recette',None,(Tier(100,1),Tier(200,9)),10),
            11:MarketItem(11,'Armure inconnue',None,(Tier(50,2),),2,'Armure/Tissu'),
            12:MarketItem(12,'Poussière',None,(Tier(500,1),),1)}
    items={10:dict(name_fr='Arme sans recette',class_id=2,item_level=20),12:dict(class_id=7)}
    profiles={10:dict(source='source',evidence='Estimation',outcomes=[dict(item_id=12,probability=1,min_quantity=1,max_quantity=1)])}
    rows=analyze_disenchant_market(market,items,profiles)
    assert {r['item_id'] for r in rows}=={10,11}
    weapon=rows[0]
    assert weapon['purchase_cost']==100 and weapon['stock']==10
    assert weapon['estimate'].profit==375 and weapon['estimate'].gold_per_minute==.75
    assert weapon['roi']==375 and weapon['status']=='Rentable'
    assert rows[1]['status']=='Non calculable'
    assert analyze_disenchant_market(market,items,profiles,100)[0]['status']=='Non rentable'
