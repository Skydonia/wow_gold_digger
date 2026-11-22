import pytest
from gold_digger.categories import item_category, recipe_categories
from gold_digger.market import parse_market
from gold_digger.models import Ingredient, MarketItem, Recipe


@pytest.mark.parametrize('raw,expected',[
    ('Armure/Tissu','Équipement'),('Arme/Dagues','Équipement'),
    ('Artisanat/Cuisine','Composants'),('Divers/Réactif','Composants'),
    ('Consommable/Nourriture & boissons','Nourriture et boissons'),
    ('Consommable/Élixirs','Potions, élixirs et flacons'),
    ('Consommable/Bandages','Bandages'),('Conteneur','Sacs et conteneurs'),
    ('Projectile/Flèche','Munitions'),('Recette/Forge','Plans et recettes'),
    ('Consommable/Autre','Autres consommables'),('Quête','Autres'),('', 'Non renseigné'),
])
def test_categories(raw,expected):
    assert item_category(raw)==expected


def test_import_preserves_type_and_accepts_old_exports():
    header='id;name;npc;first;quantity;min'
    row='1;Test;1;1x1;1;1'
    report=parse_market((header+';type\n'+row+';Armure/Tissu\n').encode())
    assert not report.errors and report.items[1].item_type=='Armure/Tissu'
    report=parse_market((header+'\n'+row+'\n').encode())
    assert not report.errors and report.items[1].item_type==''


def test_only_outputs_define_recipe_categories():
    recipe=Recipe('id','Nom','Métier',(Ingredient(1,1),),(Ingredient(2,1),Ingredient(3,1)),'s','b')
    market={1:MarketItem(1,'I',1,(),0,'Armure/Tissu'),2:MarketItem(2,'O',1,(),0,'Artisanat/Cuisine')}
    assert recipe_categories(recipe,market)==('Composants','Non renseigné')


@pytest.mark.parametrize('item_id,slot',[(7915,1),(3484,8)])
def test_mail_equipment_with_empty_or_missing_auction_type(item_id,slot):
    recipe=Recipe('id','Nom','Forge',(),(Ingredient(item_id,1),),'s','b')
    items={item_id:{'class_id':4,'subclass_id':3,'inventory_type':slot}}
    empty={item_id:MarketItem(item_id,'Objet',1,(),0,'')}
    assert recipe_categories(recipe,empty,items)==('Équipement',)
    assert recipe_categories(recipe,{},items)==('Équipement',)
    wrong={item_id:MarketItem(item_id,'Objet',1,(),0,'Artisanat/Autre')}
    assert recipe_categories(recipe,wrong,items)==('Équipement',)


def test_catalog_food_and_missing_class_fallback():
    recipe=Recipe('id','Nom','Cuisine',(),(Ingredient(117,1),),'s','b')
    assert recipe_categories(recipe,{}, {117:{'class_id':0,'subclass_id':5}})==('Nourriture et boissons',)
    market={117:MarketItem(117,'Viande',1,(),0,'Consommable/Nourriture & boissons')}
    assert recipe_categories(recipe,market,{117:{'name_fr':'Viande'}})==('Nourriture et boissons',)
