"""Compare two database snapshots and validate the current French source corpus."""
import argparse
import csv
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from bs4 import BeautifulSoup
from .database import load_database as load_catalog
from .build_database import FR,LEVELING,leveling_data,french_recipe
from .import_catalog import PROFESSIONS,item_ref
from .skill_reviews import apply_skill_reviews


def audit(before,after,cache,reviews_path):
    old,previous=load_catalog(Path(before))
    data,recipes=load_catalog(Path(after))
    manifest=[]
    def read(url):
        path=Path(cache)/(hashlib.sha256(url.encode()).hexdigest()+'.html')
        content=path.read_bytes()
        manifest.append({'url':url,'file':str(path),'sha256':hashlib.sha256(content).hexdigest()})
        return content.decode('utf-8')
    fr=json.loads(read(FR+'/items/search.json'))
    en=json.loads(read(FR.replace('/fr/','/en/')+'/items/search.json'))
    assert fr['build']==en['build']
    names={i[0]:i[1] for i in fr['rows']}
    english={i[0]:i[1] for i in en['rows']}
    assert len(names)==len(fr['rows'])==len(data['items'])
    for item_id,item in data['items'].items():
        assert item['name_fr']==names[item_id] and item['name_en']==english[item_id],item_id
        assert item['wowhead_url']==f'https://www.wowhead.com/forever/fr/item={item_id}'
    reviewed=json.loads(Path(reviews_path).read_text())
    reviewed_ids={r['recipe_id'] for r in reviewed['reviews']}
    expected=[]
    checked_recipes=[]
    variable=[]
    source_ids=set()
    for slug in PROFESSIONS:
        url=FR+'/professions/'+slug
        soup=BeautifulSoup(read(url),'html.parser')
        assert fr['build'] in soup.get_text(' ',strip=True)
        nodes={n['id']:n for n in soup.select('#recipes li.recipe[id]')}
        source_ids.update(slug+':'+rid[1:] for rid in nodes)
        level={}
        if slug in LEVELING:
            guide=read(FR+'/leveling/'+slug)
            assert fr['build'] in BeautifulSoup(guide,'html.parser').get_text(' ',strip=True)
            level={r['id']:r for r in leveling_data(guide)['recipes']}
        for r in recipes:
            if not r.id.startswith(slug+':'):
                continue
            assert r.build==fr['build']
            node=nodes['r'+r.id.split(':')[1]]
            title=node.select_one('.recipe-title')
            produced=next((p for p in node.select('p') if p.get_text(' ',strip=True).startswith('Fabrique ')),title)
            reagent=next((p for p in node.select('p') if p.get_text(' ',strip=True).startswith('Composants')),None)
            try:
                outputs=[item_ref(a) for a in produced.select('a[href*="/items/"]')]
                ingredients=[item_ref(a) for a in reagent.select('a[href*="/items/"]')] if reagent else []
            except ValueError:
                assert r.exclusion
                variable.append(r.id)
            else:
                pairs=lambda parts:sorted((i.item_id,i.quantity) for i in parts)
                assert pairs(outputs)==pairs(r.outputs),(r.id,'outputs')
                assert pairs(ingredients)==pairs(r.ingredients),(r.id,'ingredients')
                checked_recipes.append(r.id)
            # Recreate source skill before applying explicitly reviewed overrides.
            expected.append(french_recipe(r,node,names,level.get(int(r.id.split(':')[1])),FR+'/leveling/'+slug))
    assert source_ids=={r.id for r in recipes}
    skill_expected={r.id:r for r in apply_skill_reviews(expected,reviewed)}
    for r in recipes:
        assert r.skill_required==skill_expected[r.id].skill_required,r.id
    with sqlite3.connect(Path(after).resolve().as_uri()+'?mode=ro',uri=True) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert data['vendor_prices']==old['vendor_prices'],'Prix PNJ modifiés involontairement'
    def offers(values):
        return {item_id:[{k:v for k,v in row.items() if k not in ('id','source_id')} for row in rows] for item_id,rows in values.items()}
    assert offers(data['merchant_offers'])==offers(old['merchant_offers']),'Offres marchandes modifiées involontairement'
    prior={r.id:r for r in previous}
    changes=[]
    fields=('name','ingredients','outputs','exclusion','skill_required','cast_time_ms','cooldown_seconds')
    for r in recipes:
        if r.id not in prior:
            changes.append({'recipe_id':r.id,'name':r.name,'field':'added','before':None,'after':asdict(r),'source':r.source})
            continue
        prev=asdict(prior[r.id]);current=asdict(r)
        for field in fields:
            if prev[field]!=current[field]:
                changes.append({'recipe_id':r.id,'name':r.name,'field':field,'before':prev[field],'after':current[field],
                                'source':r.skill_source if field=='skill_required' else r.source})
    unknown=[{'recipe_id':r.id,'name':r.name,'profession':r.profession,'source':r.source} for r in recipes if r.skill_required is None]
    return {
        'checked_at':datetime.now(timezone.utc).isoformat(),'game':'wow-forever','catalog_build':fr['build'],
        'summary':{'items':len(data['items']),'items_added':len(data['items'].keys()-old['items'].keys()),'recipes':len(recipes),
                   'recipes_added':len(source_ids-prior.keys()),'recipes_quantities_checked_against_french_source':len(checked_recipes),
                   'variable_or_unreadable_recipes_excluded':len(variable),
                   'existing_recipes_with_corrected_output':sum(c['field']=='outputs' for c in changes),
                   'skills_corrected':sum(c['field']=='skill_required' and c['before'] is not None for c in changes),
                   'skills_completed':sum(c['field']=='skill_required' and c['before'] is None for c in changes),
                   'wowhead_skill_reviews':len(reviewed_ids),'unknown_skills':len(unknown),
                   'known_positive_timings':sum(r.cast_time_ms is not None and r.cast_time_ms>0 for r in recipes)},
        'limits':['Les 21 983 noms/identifiants et les recettes sont comparés au corpus Endgame Forever : ce contrôle ne constitue pas une confirmation indépendante de chaque donnée du jeu.',
                  'Wowhead recoupé sur 28 niveaux seulement ; accès HTML direct refusé (403), consultation des fiches et résultats indexés. Commentaires utilisateurs non utilisés.',
                  'Les références Classic de Wowcalc ne corrigent pas automatiquement les niveaux Forever. Les seuils jaunes ne sont pas des seuils d’apprentissage.',
                  'Les seuils non documentés restent inconnus. Disponibilité en jeu, recettes liées, changements serveur et exhaustivité du catalogue non certifiés.',
                  'Prix PNJ et offres marchandes conservés, pas de nouveau contrôle exhaustif des prix. Les catégories du filtre restent issues du CSV HDV.',
                  'Durées réassociées au corpus Wowcalc antérieur (1.60.1.70888), seulement lorsque composants et produits concordent.'],
        'source_manifest':manifest,'skill_reviews':reviewed['reviews'],'changes':changes,'unknown_skills':unknown,
        'unreadable_or_variable_recipe_ids':variable,
        'unresolved_skill_candidates':[{'recipe_id':rid,'reason':reason} for rid,reason in [
            ('blacksmithing:3292','Source actuelle 95 ; référence Classic Wowcalc 90. Aucune confirmation Forever exploitable trouvée.'),
            ('blacksmithing:3491','Source actuelle 105 ; référence Classic 100 et ancien commentaire Wowhead : insuffisant pour corriger.'),
            ('enchanting:7428','Source apprentissage automatique 1 ; référence Classic 20, non appliquée.'),
            ('leatherworking:7153','Patron Forever 160 ; référence Classic 125 non appliquée.'),
            ('tailoring:3755','Apprentissage automatique 1 selon la source ; référence Classic 45 non appliquée.'),
            ('tailoring:23664','Patron Forever 290, guide Wowhead 255 ; valeur du patron conservée.')]],
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before',type=Path,required=True)
    p.add_argument('--after',type=Path,required=True)
    p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--reviews',type=Path,default=Path('data/sources/skill_reviews.json'))
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    report=audit(args.before,args.after,args.cache,args.reviews)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    for filename,rows in [('corrections.csv',report['changes']),('competences_inconnues.csv',report['unknown_skills'])]:
        with (args.output.parent/filename).open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else [],delimiter=';')
            writer.writeheader()
            writer.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in row.items()} for row in rows)
    print(json.dumps(report['summary'],ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
