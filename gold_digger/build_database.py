"""Enrichit les recettes en français et publie une base SQLite validée."""
import argparse
from dataclasses import replace
from datetime import datetime,timezone
import json
import re
from pathlib import Path
from bs4 import BeautifulSoup
from .catalog import load_catalog
from .database import publish_database
from .import_catalog import fetch, PROFESSIONS
from .models import Ingredient
from .collect_timings import quantities
from .skill_reviews import apply_skill_reviews

FR='https://endgametools.com/fr/wow-forever'
LEVELING={'alchemy','blacksmithing','enchanting','engineering','leatherworking','tailoring','cooking','first-aid'}


def leveling_data(html):
    payloads=[]
    for raw in re.findall(r'self\.__next_f\.push\((.*?)\)</script>',html,re.S):
        try:
            chunk=json.loads(raw)
            if len(chunk)>1 and isinstance(chunk[1],str):
                payloads.append(chunk[1])
        except ValueError:
            continue
    for line in ''.join(payloads).splitlines():
        if '"recipes":[{' in line:
            try:
                props=json.loads(line.split(':',1)[1])[3]
                if isinstance(props,dict) and 'recipes' in props and 'profession' in props:
                    return props
            except (ValueError,IndexError,TypeError):
                continue
    raise ValueError('Données structurées du guide de compétence introuvables')


def french_recipe(original,node,names,level,level_source):
    if node is None:
        raise ValueError(f'Recette absente de la page française : {original.id}')
    title=node.select_one('.recipe-title')
    label=title.get_text(' ',strip=True)
    components=lambda parts: tuple(Ingredient(i.item_id,i.quantity,names.get(i.item_id,i.name)) for i in parts)
    ingredients=components(original.ingredients)
    outputs=components(original.outputs)
    if outputs:
        label=outputs[0].name
    restrictions=[]
    tools=[]
    skill,skill_basis,skill_source=None,'Inconnue',''
    for p in node.select('p'):
        if p is title or 'recipe-skill' in p.get('class',[]):
            continue
        text=p.get_text(' ',strip=True)
        if text.startswith(('Composants','Reagents')):
            continue
        if text:
            restrictions.append(text)
            if text.startswith('Requiert '):
                stations={'Enclume','Forge','Feu de cuisine','Puits de lune','Rouet','Métier à tisser'}
                for label_tool in text.removeprefix('Requiert ').split(' · '):
                    if label_tool not in stations:
                        ids=[i for i,name in names.items() if name==label_tool]
                        if len(ids)==1:
                            tools.append(Ingredient(ids[0],1,label_tool))
            match=re.search(r'\(compétence\s*(\d+)\)',text,re.I)
            if match:
                skill,skill_basis,skill_source=int(match[1]),'Seuil explicite dans la recette',original.source.replace('/en/','/fr/')
    if level:
        if level.get('kind') in {'auto','pattern'} or level.get('trained'):
            learn=level.get('learn')
            if type(learn) is int and learn>=0:
                skill,skill_basis,skill_source=learn,'Apprentissage documenté',level_source
        # Un seuil jaune n'est pas un seuil d'apprentissage.
        for tool in level.get('tools',[]):
            if isinstance(tool,int) and tool in names:
                tools.append(Ingredient(tool,1,names[tool]))
            elif isinstance(tool,str):
                matches=[i for i,name in names.items() if name==tool]
                if len(matches)==1:
                    tools.append(Ingredient(matches[0],1,tool))
                if tool not in restrictions:
                    restrictions.append('Outil requis : '+tool)
        for place in level.get('needs',[]):
            if isinstance(place,str) and not any(place in text for text in restrictions):
                restrictions.append('Installation requise : '+place)
    return replace(original,name=label,ingredients=ingredients,outputs=outputs,restrictions=tuple(restrictions),source=original.source.replace('/en/','/fr/'),skill_required=skill,skill_basis=skill_basis,skill_source=skill_source,tools=tuple({t.item_id:t for t in tools}.values()))



def attach_timings(recipes,payload):
    if payload.get('game')!='wow-forever' or payload.get('schema_version')!=1:
        raise ValueError('Instantané des durées incompatible')
    records={r['recipe_id']:r for r in payload['timings']}
    if len(records)!=len(payload['timings']):
        raise ValueError('Durées dupliquées')
    enriched=[]
    for recipe in recipes:
        record=records.get(recipe.id)
        if record:
            duration=record.get('cast_time_ms')
            if type(duration) is not int or duration<0 or not record.get('source') or not record.get('build'):
                raise ValueError('Durée ou provenance invalide : '+recipe.id)
            cooldown=record.get('cooldown_seconds')
            if cooldown is not None and (type(cooldown) is not int or cooldown<0):
                raise ValueError('Délai de récupération invalide : '+recipe.id)
            compatible=(record.get('matched_catalog_build')==recipe.build and
                quantities(record['ingredients'])==quantities([vars(i) for i in recipe.ingredients]) and
                quantities(record['outputs'])==quantities([vars(i) for i in recipe.outputs]))
            if compatible:
                recipe=replace(recipe,cast_time_ms=duration,timing_source=record['source'],timing_build=record['build'],
                    cooldown_seconds=cooldown if cooldown is not None else recipe.cooldown_seconds)
        enriched.append(recipe)
    return enriched


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',type=Path,default=Path('data/catalog/forever.json'))
    parser.add_argument('--output',type=Path,default=Path('data/catalog/forever.sqlite'))
    parser.add_argument('--cache',type=Path,default=Path('data/cache/endgame'))
    parser.add_argument('--merchants',type=Path,default=Path('data/sources/merchant_offers.json'))
    parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--skill-reviews',type=Path,default=Path('data/sources/skill_reviews.json'))
    parser.add_argument('--timings',type=Path,default=Path('data/sources/craft_timings.json'))
    parser.add_argument('--disenchant',type=Path,default=Path('data/sources/disenchant.json'))
    args=parser.parse_args()
    data,originals=load_catalog(args.catalog)
    french=json.loads(fetch(FR+'/items/search.json',args.cache,args.refresh))
    english=json.loads(fetch(FR.replace('/fr/','/en/')+'/items/search.json',args.cache,args.refresh))
    builds={r.build for r in originals}
    if builds!={french['build']} or french['build']!=english['build']:
        raise ValueError('Builds incompatibles : actualiser le catalogue de recettes avant la base française')
    names={row[0]:row[1] for row in french['rows']}
    en={row[0]:row[1] for row in english['rows']}
    # Documented by the source's /items/search.js: inventoryType, classId, subclassId.
    item_classes={}
    en_rows={row[0]:row for row in english['rows']}
    for row in french['rows']:
        if len(row)!=9 or any(type(row[i]) is not int or row[i]<0 for i in (2,3,5,6,7)):
            raise ValueError('Format des classes d’objet inattendu')
        if en_rows[row[0]][2:8]!=row[2:8]:
            raise ValueError('Classes françaises et anglaises incompatibles')
        item_classes[row[0]]=dict(inventory_type=row[5],class_id=row[6],subclass_id=row[7],quality=row[2],item_level=row[3])
    updated=[]
    for slug in PROFESSIONS:
        html=fetch(FR+'/professions/'+slug,args.cache,args.refresh)
        soup=BeautifulSoup(html,'html.parser')
        if french['build'] not in soup.get_text(' ',strip=True):
            raise ValueError('Build français incompatible : '+slug)
        nodes={node['id']:node for node in soup.select('#recipes li.recipe[id]')}
        level={}
        if slug in LEVELING:
            guide=fetch(FR+'/leveling/'+slug,args.cache,args.refresh)
            if french['build'] not in BeautifulSoup(guide,'html.parser').get_text(' ',strip=True):
                raise ValueError('Guide de compétence de build différent : '+slug)
            level={r['id']:r for r in leveling_data(guide)['recipes']}
        for recipe in [r for r in originals if r.id.startswith(slug+':')]:
            spell=int(recipe.id.split(':')[1])
            updated.append(french_recipe(recipe,nodes.get('r'+str(spell)),names,level.get(spell),FR+'/leveling/'+slug))
        print(PROFESSIONS[slug]+': français et compétences importés',flush=True)
    # Le catalogue d'objets est indépendant de la présence d'un objet dans le scan HDV.
    items={i:{'name_fr':name,'name_en':en.get(i,''),'source':FR+'/items/search.json','build':french['build'],**item_classes[i]} for i,name in names.items()}
    for recipe in updated:
        for item in recipe.ingredients+recipe.outputs+recipe.tools:
            if item.item_id not in items:
                items[item.item_id]={'name_fr':item.name or f'Objet {item.item_id}','name_en':'','source':recipe.source,'build':recipe.build}
    raw=json.loads(args.merchants.read_text(encoding='utf-8'))
    if raw.get('game')!='wow-forever' or raw.get('schema_version')!=1:
        raise ValueError('Observations marchands incompatibles')
    offers=[{**o,'source':raw['source'],'observed_builds':raw['observed_builds'],'price_basis':raw['price_basis'],'unlimited':True} for o in raw['offers'] if o.get('unlimited') is True]
    if args.timings.exists():
        timing_payload=json.loads(args.timings.read_text(encoding='utf-8'))
        updated=attach_timings(updated,timing_payload)
        data['timings_captured_at']=timing_payload['captured_at']
    if args.skill_reviews.exists():
        reviews=json.loads(args.skill_reviews.read_text(encoding='utf-8'))
        updated=apply_skill_reviews(updated,reviews)
        data['skill_reviews_count']=len(reviews['reviews'])
        data['skill_reviews_checked_on']=max(r['checked_on'] for r in reviews['reviews'])
    data['timings_count']=sum(r.cast_time_ms is not None for r in updated)
    data.update(schema_version=5,imported_at=datetime.now(timezone.utc).isoformat(),merchant_capture=raw['captured_on'],merchant_source=raw['source'],locale='frFR')
    data['disenchant_reference']=json.loads(args.disenchant.read_text(encoding='utf-8'))
    data['disenchant_info']={k:v for k,v in data['disenchant_reference'].items() if k not in ('tables','brackets','overrides','never')}
    publish_database(args.output,data,updated,items,offers)
    print(f'Base publiée : {len(items)} objets, {len(updated)} recettes, {sum(r.skill_required is not None for r in updated)} seuils connus, {len(offers)} offres marchandes.')


if __name__=='__main__':
    main()
