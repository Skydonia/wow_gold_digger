"""Collecte des durées de sorts de fabrication Forever, avec contrôle des recettes."""
import argparse
from collections import defaultdict
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
import json
from pathlib import Path
import re
from bs4 import BeautifulSoup
from .catalog import load_catalog
from .import_catalog import fetch,PROFESSIONS

BASE='https://wowcalc.net/en/forever/wiki/professions/'


def milliseconds(value):
    if isinstance(value,bool):
        raise ValueError('Durée booléenne invalide')
    try:
        number=Decimal(str(value))*1000
    except InvalidOperation as exc:
        raise ValueError('Durée invalide') from exc
    if not number.is_finite() or number<0 or number!=number.to_integral_value():
        raise ValueError('Durée invalide ou précision inférieure à une milliseconde')
    return int(number)


def parse_timings(html,profession):
    soup=BeautifulSoup(html,'html.parser')
    match=re.search(r'WoW Forever client\s+(1\.60\.\d+\.\d+)',soup.get_text(' ',strip=True))
    if not match:
        raise ValueError('Build du client Forever introuvable')
    chunks=[]
    for raw in re.findall(r'self\.__next_f\.push\((.*?)\)</script>',html,re.S):
        part=json.loads(raw)
        if len(part)>1 and isinstance(part[1],str):
            chunks.append(part[1])
    for line in ''.join(chunks).splitlines():
        if '"recipes"' not in line:
            continue
        try:
            tree=json.loads(line.split(':',1)[1])
        except ValueError:
            continue
        stack=[tree]
        while stack:
            value=stack.pop()
            if isinstance(value,dict):
                if 'recipes' in value and 'profession' in value:
                    if value.get('version')!='forever' or value.get('profession')!=profession:
                        raise ValueError('Version ou métier incompatible')
                    return match[1],value['recipes']
                stack.extend(value.values())
            elif isinstance(value,list):
                stack.extend(value)
    raise ValueError('Durées structurées introuvables')


def quantities(parts,id_field='item_id',quantity_field='quantity'):
    result=defaultdict(int)
    for part in parts:
        result[part[id_field]]+=part[quantity_field]
    return dict(result)


def match_timing(recipe,raw,build):
    if str(raw['id'])!=recipe.id.split(':')[1]:
        raise ValueError('Identifiant de sort différent')
    if quantities([vars(i) for i in recipe.ingredients])!=quantities(raw.get('reagents',[]),'item'):
        raise ValueError('Composants ou quantités différents')
    created=raw.get('creates',[])
    if any(i.get('min')!=i.get('max') for i in created):
        raise ValueError('Production variable')
    if quantities([vars(i) for i in recipe.outputs])!=quantities(created,'item','min'):
        raise ValueError('Produits ou quantités différents')
    if raw.get('castTime') is None:
        raise ValueError('Durée absente')
    cast_ms=milliseconds(raw['castTime'])
    cooldown=None
    if raw.get('cooldown') is not None:
        cooldown_ms=milliseconds(raw['cooldown'])
        if cooldown_ms%1000:
            raise ValueError('Délai de récupération non entier en secondes')
        cooldown=cooldown_ms//1000
    return {'recipe_id':recipe.id,'cast_time_ms':cast_ms,'cooldown_seconds':cooldown,
            'source':BASE+recipe.id.split(':')[0]+'?recipe='+str(raw['id']),
            'build':build,'matched_catalog_build':recipe.build,
            'ingredients':[vars(i) for i in recipe.ingredients],
            'outputs':[vars(i) for i in recipe.outputs]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',type=Path,default=Path('data/catalog/forever.json'))
    parser.add_argument('--output',type=Path,default=Path('data/sources/craft_timings.json'))
    parser.add_argument('--cache',type=Path,default=Path('data/cache/timings'))
    parser.add_argument('--refresh',action='store_true')
    args=parser.parse_args()
    _,recipes=load_catalog(args.catalog)
    timings,unmatched,failures=[],[],[]
    for slug in PROFESSIONS:
        try:
            build,records=parse_timings(fetch(BASE+slug,args.cache,args.refresh),slug)
            lookup={str(r['id']):r for r in records}
            if len(lookup)!=len(records):
                raise ValueError('Identifiants de recette dupliqués')
            count=0
            for recipe in [r for r in recipes if r.id.startswith(slug+':')]:
                try:
                    raw=lookup.get(recipe.id.split(':')[1])
                    if raw is None:
                        raise ValueError('Recette absente de la source')
                    timings.append(match_timing(recipe,raw,build)); count+=1
                except ValueError as exc:
                    unmatched.append({'recipe_id':recipe.id,'reason':str(exc)})
            print(f'{PROFESSIONS[slug]} : {count} durées concordantes',flush=True)
        except Exception as exc:
            failures.append(f'{slug}: {exc}')
    if failures:
        raise SystemExit('Collecte incomplète, instantané existant conservé : '+' ; '.join(failures))
    data={'schema_version':1,'game':'wow-forever','captured_at':datetime.now(timezone.utc).isoformat(),
          'method_source':'https://wowcalc.net/en/how-it-works','timings':timings,'unmatched':unmatched}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temporary=args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(args.output)
    print(f'{len(timings)} durées enregistrées ; {len(unmatched)} recettes non associées.')


if __name__=='__main__':
    main()
