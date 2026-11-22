"""Stockage SQLite normalisé. Publication atomique d'un instantané validé."""
import json
import sqlite3
from pathlib import Path
from .models import Ingredient, Recipe
from .disenchant import validate_reference, item_profile

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL) STRICT;
CREATE TABLE sources(id INTEGER PRIMARY KEY,url TEXT NOT NULL,build TEXT NOT NULL,description TEXT NOT NULL,UNIQUE(url,build)) STRICT;
CREATE TABLE professions(id TEXT PRIMARY KEY,name_fr TEXT NOT NULL) STRICT;
CREATE TABLE items(id INTEGER PRIMARY KEY CHECK(id>0),name_fr TEXT NOT NULL,name_en TEXT NOT NULL,wowhead_url TEXT NOT NULL,source_id INTEGER NOT NULL REFERENCES sources(id),class_id INTEGER CHECK(class_id>=0),subclass_id INTEGER CHECK(subclass_id>=0),inventory_type INTEGER CHECK(inventory_type>=0),quality INTEGER CHECK(quality>=0),item_level INTEGER CHECK(item_level>=0)) STRICT;
CREATE TABLE recipes(id TEXT PRIMARY KEY,profession_id TEXT NOT NULL REFERENCES professions(id),name_fr TEXT NOT NULL,skill_required INTEGER CHECK(skill_required>=0),skill_basis TEXT NOT NULL,skill_source_id INTEGER REFERENCES sources(id),cooldown_seconds INTEGER CHECK(cooldown_seconds>=0),exclusion TEXT NOT NULL,source_id INTEGER NOT NULL REFERENCES sources(id)) STRICT;
CREATE TABLE recipe_items(recipe_id TEXT NOT NULL REFERENCES recipes(id),item_id INTEGER NOT NULL REFERENCES items(id),role TEXT NOT NULL CHECK(role IN ('ingredient','output','tool')),quantity INTEGER NOT NULL CHECK(quantity>0),PRIMARY KEY(recipe_id,item_id,role)) STRICT;
CREATE TABLE recipe_conditions(recipe_id TEXT NOT NULL REFERENCES recipes(id),position INTEGER NOT NULL,text_fr TEXT NOT NULL,PRIMARY KEY(recipe_id,position)) STRICT;
CREATE TABLE sell_prices(item_id INTEGER NOT NULL REFERENCES items(id),copper INTEGER NOT NULL CHECK(copper>=0),source_id INTEGER NOT NULL REFERENCES sources(id),PRIMARY KEY(item_id,source_id)) STRICT;
CREATE TABLE merchant_offers(id INTEGER PRIMARY KEY,item_id INTEGER NOT NULL REFERENCES items(id),vendor_name TEXT NOT NULL,lot_price_copper INTEGER NOT NULL CHECK(lot_price_copper>0),lot_quantity INTEGER NOT NULL CHECK(lot_quantity>0),unlimited INTEGER NOT NULL CHECK(unlimited IN(0,1)),source_id INTEGER NOT NULL REFERENCES sources(id),source_line INTEGER,UNIQUE(item_id,vendor_name,lot_price_copper,lot_quantity)) STRICT;
CREATE INDEX recipes_by_profession_skill ON recipes(profession_id,skill_required);
CREATE INDEX recipe_items_by_item ON recipe_items(item_id);
CREATE INDEX offers_by_item ON merchant_offers(item_id,unlimited);
CREATE TABLE recipe_timings(recipe_id TEXT PRIMARY KEY REFERENCES recipes(id),cast_time_ms INTEGER NOT NULL CHECK(cast_time_ms>=0),source_id INTEGER NOT NULL REFERENCES sources(id)) STRICT;
CREATE TABLE disenchant_profiles(id TEXT PRIMARY KEY,source_id INTEGER NOT NULL REFERENCES sources(id),evidence TEXT NOT NULL) STRICT;
CREATE TABLE disenchant_outcomes(profile_id TEXT NOT NULL REFERENCES disenchant_profiles(id),item_id INTEGER NOT NULL REFERENCES items(id),probability REAL NOT NULL CHECK(probability>0 AND probability<=1),min_quantity INTEGER NOT NULL CHECK(min_quantity>0),max_quantity INTEGER NOT NULL CHECK(max_quantity>=min_quantity),PRIMARY KEY(profile_id,item_id)) STRICT;
CREATE TABLE item_disenchant(item_id INTEGER PRIMARY KEY REFERENCES items(id),profile_id TEXT REFERENCES disenchant_profiles(id),reason TEXT NOT NULL) STRICT;
PRAGMA user_version=5;
"""


def wowhead_url(item_id):
    return f"https://www.wowhead.com/forever/fr/item={int(item_id)}"


def publish_database(path, data, recipes, items, offers):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.building.sqlite')
    if temporary.exists():
        temporary.unlink()
    connection = sqlite3.connect(temporary)
    try:
        connection.executescript(SCHEMA)
        def source(url, build, description):
            connection.execute('INSERT OR IGNORE INTO sources(url,build,description) VALUES(?,?,?)', (url,build,description))
            return connection.execute('SELECT id FROM sources WHERE url=? AND build=?',(url,build)).fetchone()[0]
        with connection:
            for key, value in {**data,"schema_version":5}.items():
                if key not in ('recipes','vendor_prices','items','merchant_offers','disenchant_reference','disenchant'):
                    connection.execute('INSERT INTO metadata VALUES(?,?)',(key,json.dumps(value,ensure_ascii=False)))
            for item_id, item in items.items():
                sid=source(item['source'],item['build'],'Noms et classes du client français')
                connection.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?)',(item_id,item['name_fr'],item.get('name_en',''),wowhead_url(item_id),sid,item.get('class_id'),item.get('subclass_id'),item.get('inventory_type'),item.get('quality'),item.get('item_level')))
            if data.get('disenchant_reference'):
                de=data['disenchant_reference']
                validate_reference(de)
                sid=source(de['source'],de['build'],de['provenance'])
                for profile_id,outcomes in de['tables'].items():
                    connection.execute('INSERT INTO disenchant_profiles VALUES(?,?,?)',(profile_id,sid,de['evidence']))
                    for o in outcomes:
                        connection.execute('INSERT INTO disenchant_outcomes VALUES(?,?,?,?,?)',(profile_id,o['item_id'],o['probability'],o['min_quantity'],o['max_quantity']))
                for item_id,item in items.items():
                    if item.get('class_id') in (2,4):
                        profile_id,reason=item_profile(item_id,item,de)
                        connection.execute('INSERT INTO item_disenchant VALUES(?,?,?)',(item_id,profile_id,reason))
            for r in recipes:
                slug=r.id.split(':')[0]
                connection.execute('INSERT OR IGNORE INTO professions VALUES(?,?)',(slug,r.profession))
                sid=source(r.source,r.build,'Recette du client Forever, français')
                skill_sid=source(r.skill_source,r.build,'Compétence requise') if r.skill_source else None
                connection.execute('INSERT INTO recipes VALUES(?,?,?,?,?,?,?,?,?)',(r.id,slug,r.name,r.skill_required,r.skill_basis,skill_sid,r.cooldown_seconds,r.exclusion,sid))
                if r.cast_time_ms is not None:
                    if not r.timing_source or not r.timing_build:
                        raise ValueError('Provenance de durée manquante : '+r.id)
                    tid=source(r.timing_source,r.timing_build,'Durée de fabrication du client Forever')
                    connection.execute('INSERT INTO recipe_timings VALUES(?,?,?)',(r.id,r.cast_time_ms,tid))
                for role, components in [('ingredient',r.ingredients),('output',r.outputs),('tool',r.tools)]:
                    quantities={}
                    for component in components:
                        quantities[component.item_id]=quantities.get(component.item_id,0)+component.quantity
                    for item_id,quantity in quantities.items():
                        connection.execute('INSERT INTO recipe_items VALUES(?,?,?,?)',(r.id,item_id,role,quantity))
                for position,text in enumerate(r.restrictions):
                    connection.execute('INSERT INTO recipe_conditions VALUES(?,?,?)',(r.id,position,text))
            for item_id, record in data.get('vendor_prices',{}).items():
                if int(item_id) in items:
                    sid=source(record['source'],record['build'],'Prix de revente PNJ')
                    connection.execute('INSERT INTO sell_prices VALUES(?,?,?)',(int(item_id),record['sell_copper'],sid))
            for o in offers:
                if o['item_id'] not in items:
                    continue
                sid=source(o['source'],o['observed_builds'],o['price_basis'])
                connection.execute('INSERT INTO merchant_offers(item_id,vendor_name,lot_price_copper,lot_quantity,unlimited,source_id,source_line) VALUES(?,?,?,?,?,?,?) ON CONFLICT(item_id,vendor_name,lot_price_copper,lot_quantity) DO NOTHING',
                    (o['item_id'],o['vendor'],o['lot_price_copper'],o['lot_quantity'],int(o['unlimited']),sid,o.get('source_line')))
        if connection.execute('PRAGMA foreign_key_check').fetchall() or connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('Base invalide : intégrité ou références')
    except Exception:
        connection.close()
        temporary.unlink(missing_ok=True)
        raise
    connection.close()
    temporary.replace(path)


def load_database(path):
    connection=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    connection.row_factory=sqlite3.Row
    try:
        version=connection.execute('PRAGMA user_version').fetchone()[0]
        if version not in (2,3,4,5):
            raise ValueError('Version de base SQLite incompatible')
        data={r['key']:json.loads(r['value']) for r in connection.execute('SELECT * FROM metadata')}
        items={r['id']:dict(r) for r in connection.execute('SELECT * FROM items')}
        relations={}
        for row in connection.execute('SELECT * FROM recipe_items ORDER BY recipe_id,item_id'):
            relations.setdefault((row['recipe_id'],row['role']),[]).append(Ingredient(row['item_id'],row['quantity'],items[row['item_id']]['name_fr']))
        conditions={}
        for row in connection.execute('SELECT * FROM recipe_conditions ORDER BY recipe_id,position'):
            conditions.setdefault(row['recipe_id'],[]).append(row['text_fr'])
        timings={r['recipe_id']:dict(r) for r in connection.execute('SELECT t.*,s.url,s.build FROM recipe_timings t JOIN sources s ON s.id=t.source_id')} if version>=3 else {}
        recipes=[]
        for row in connection.execute('SELECT r.*,p.name_fr AS profession,s.url,s.build,ss.url AS skill_url FROM recipes r JOIN professions p ON p.id=r.profession_id JOIN sources s ON s.id=r.source_id LEFT JOIN sources ss ON ss.id=r.skill_source_id ORDER BY r.id'):
            timing=timings.get(row['id'],{})
            recipes.append(Recipe(row['id'],row['name_fr'],row['profession'],tuple(relations.get((row['id'],'ingredient'),[])),tuple(relations.get((row['id'],'output'),[])),row['url'],row['build'],tuple(conditions.get(row['id'],[])),row['cooldown_seconds'],row['exclusion'],row['skill_required'],row['skill_basis'],row['skill_url'] or '',tuple(relations.get((row['id'],'tool'),[])),timing.get('cast_time_ms'),timing.get('url',''),timing.get('build','')))
        data['vendor_prices']={str(r['item_id']):{'sell_copper':r['copper'],'source':r['url'],'build':r['build']} for r in connection.execute('SELECT p.*,s.url,s.build FROM sell_prices p JOIN sources s ON s.id=p.source_id')}
        offers={}
        for row in connection.execute('SELECT o.*,s.url AS source,s.build AS observed_builds,s.description AS price_basis FROM merchant_offers o JOIN sources s ON s.id=o.source_id'):
            offers.setdefault(row['item_id'],[]).append(dict(row))
        data['merchant_offers']=offers
        data['items']=items
        data['disenchant']={}
        if version>=5:
            outcomes={}
            for row in connection.execute('SELECT * FROM disenchant_outcomes ORDER BY profile_id,item_id'):
                outcomes.setdefault(row['profile_id'],[]).append(dict(row))
            for row in connection.execute('SELECT d.*,p.evidence,s.url AS source,s.build FROM item_disenchant d LEFT JOIN disenchant_profiles p ON p.id=d.profile_id LEFT JOIN sources s ON s.id=p.source_id'):
                data['disenchant'][row['item_id']]={**dict(row),'outcomes':outcomes.get(row['profile_id'],[])}
        return data,recipes
    finally:
        connection.close()
