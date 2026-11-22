"""Modèle de présentation partagé par l'interface et les exports."""
from html import escape
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit
from .database import wowhead_url
from .engine import merchant_reference
from .market import money


def item_name(item_id,items,market=None,fallback=''):
    if item_id in items:
        return items[item_id]['name_fr']
    if market and item_id in market:
        return market[item_id].name
    return fallback or f'Objet {item_id}'


def recipe_matches(recipe, professions, max_skill, include_unknown, min_skill=1):
    if min_skill>max_skill:
        return False
    if professions and recipe.profession not in professions:
        return False
    return include_unknown if recipe.skill_required is None else min_skill<=recipe.skill_required<=max_skill


def components_table(recipe,items,market,offers,quantity=1,policy='conservative'):
    rows=[]
    for component in recipe.ingredients:
        m=market.get(component.item_id)
        vendor=merchant_reference(offers.get(component.item_id,[]),policy)
        rows.append({'Composant':item_name(component.item_id,items,market,component.name),
            'Par fabrication':component.quantity,'Pour le lot':component.quantity*quantity,
            'Stock HDV détaillé':sum(t.quantity for t in m.tiers) if m else 0,
            'Meilleur prix HDV':money(m.tiers[0].price) if m and m.tiers else 'Absent',
            'Prix marchand':f"{money(vendor['lot_price_copper'])} / {vendor['lot_quantity']} unité(s)" if vendor else 'Non documenté',
            'Stock marchand':'Illimité' if vendor else '—',
            'Wowhead':wowhead_url(component.item_id)})
    return rows


def text_link(label, url):
    """Escape imported labels and allow only web links."""
    label=escape(str(label))
    if not url or urlsplit(str(url)).scheme not in ('https','http'):
        return label
    return f'<a href="{escape(str(url),quote=True)}" target="_blank" rel="noopener noreferrer">{label}</a>'


def linked_table(rows, component_links=None):
    """Render names as links, keeping plain rows intact for CSV exports.

    component_links contains (quantity, name, item_id) tuples for each row.
    """
    if not rows:
        return ''
    columns=[key for key in rows[0] if key!='Wowhead']
    header=''.join(f'<th scope="col">{escape(key)}</th>' for key in columns)
    body=[]
    for index,row in enumerate(rows):
        cells=[]
        for key in columns:
            value=row.get(key)
            label='—' if value is None else str(value)
            if key in ('Recette','Composant','Objet','Outil'):
                content=text_link(label,row.get('Wowhead'))
            elif key=='Source' and value:
                content=text_link('Consulter',value)
            elif key=='Composants par fabrication' and component_links is not None:
                content='; '.join(f'{escape(str(qty))} × {text_link(name,wowhead_url(item_id))}'
                                 for qty,name,item_id in component_links[index])
            else:
                content=escape(label)
            cells.append(f'<td>{content}</td>')
        body.append('<tr>'+''.join(cells)+'</tr>')
    return '<div class="item-table-scroll" tabindex="0"><table class="item-table"><thead><tr>'+header+'</tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'


def interactive_table(rows, component_links=None):
    markup=linked_table(rows,component_links)
    script=Path(__file__).with_name('table.js').read_text()
    return """<!doctype html><html lang="fr"><head><meta charset="utf-8"><style>
body{margin:0;background:#10171e;color:#edf1f5;font-family:system-ui,sans-serif;font-size:14px}
.item-table-scroll{overflow:auto;max-height:540px;border:1px solid #344352;border-radius:8px}
table{border-collapse:collapse;width:100%}th,td{padding:10px 14px;text-align:left;border-bottom:1px solid #344352;white-space:nowrap}
th{position:sticky;top:0;background:#1b2631;z-index:1}
button{font:inherit;font-weight:600;color:inherit;background:none;border:0;padding:0;cursor:pointer;text-align:left}
button:hover,a:hover{color:#fff}button:focus-visible,a:focus-visible{outline:2px solid #e5b85c;outline-offset:3px}
a{color:#e5b85c;text-decoration:underline;text-underline-offset:3px}
</style></head><body>"""+markup+'<script>'+script+'</script></body></html>'


def search_matches(query, text):
    """All query words must match; accents, case and outer whitespace are ignored."""
    def normalize(value):
        return ''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(c))
    haystack=normalize(text)
    return all(word in haystack for word in normalize(query).split())
