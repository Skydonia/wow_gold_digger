from collections import Counter
from datetime import datetime
import csv
import hashlib
import io
from pathlib import Path
import pandas as pd
import streamlit as st
from gold_digger.auction import estimate_auction, profitability, auction_roi, filter_roi
from gold_digger.categories import recipe_categories, catalog_category, item_category
from gold_digger.catalog import load_catalog
from gold_digger.database import wowhead_url
from gold_digger.engine import analyze_single
from gold_digger.disenchant import estimate_disenchant, estimate_direct_disenchant, DisenchantEstimate, outcome_labels
from gold_digger.disenchant_market import analyze_disenchant_market
from gold_digger.market import parse_market, money
from gold_digger.presentation import components_table, item_name, recipe_matches, search_matches, interactive_table, text_link

ROOT=Path(__file__).resolve().parent
st.set_page_config(page_title='Gold Digger · WoW Forever',page_icon='🪙',layout='wide')
st.markdown('''<style>
.block-container{padding-top:2rem;max-width:1700px} h1{letter-spacing:-.04em}
[data-testid="stMetric"]{background:#1b2631;border:1px solid #344352;border-radius:10px;padding:16px}
[data-testid="stSidebar"]{border-right:1px solid #344352}
</style>''',unsafe_allow_html=True)
st.caption('WOW FOREVER / ARTISANAT ET RENTABILITÉ')
st.title('Gold Digger')
st.write('Compare les recettes en pourcentage de rentabilité, avec les composants achetés à l’HDV ou chez les marchands.')


@st.cache_data(show_spinner=False,max_entries=2)
def read_database(path,version):
    return load_catalog(Path(path))


@st.cache_data(show_spinner=False,max_entries=8,ttl=3600)
def calculate(recipes,market,sell_prices,offers,policy):
    return [analyze_single(r,market,sell_prices,offers,policy) for r in recipes]


def table(rows, component_links=None, disenchant_links=None):
    if rows:
        if 'Wowhead' in rows[0]:
            st.iframe(interactive_table(rows,component_links,disenchant_links),height=min(560,60+len(rows)*44),alt='Tableau triable : cliquez sur un titre de colonne pour inverser le tri.')
        else:
            st.dataframe(pd.DataFrame(rows),hide_index=True,width='stretch')


def export_csv(rows):
    if not rows:
        return b''
    output=io.StringIO()
    writer=csv.DictWriter(output,fieldnames=list(rows[0]),delimiter=';')
    writer.writeheader()
    for row in rows:
        writer.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in row.items()})
    return output.getvalue().encode('utf-8-sig')


with st.sidebar:
    st.header('Ton marché')
    uploaded=st.file_uploader('Importer un export HDV',type=['csv'],key='market_upload')
    default=ROOT/'data/input/export_hdv.csv'
    if uploaded:
        content,filename=uploaded.getvalue(),uploaded.name
    elif default.exists():
        content,filename=default.read_bytes(),default.name
        st.caption('L’export du projet est chargé.')
    else:
        st.info('Importe un export HDV pour commencer.')
        st.stop()
    fingerprint=hashlib.sha256(content).hexdigest()
    if st.session_state.get('fingerprint')!=fingerprint:
        st.session_state.fingerprint=fingerprint
        st.session_state.imported_at=datetime.now().astimezone().strftime('%d/%m/%Y à %H:%M:%S %Z')
    st.write(filename)
    st.caption(f'Importé le {st.session_state.imported_at}. Date du scan inconnue.')

report=parse_market(content)
if report.errors or report.warnings:
    with st.expander(f'Contrôle de l’import : {len(report.errors)} erreur(s), {len(report.warnings)} avertissement(s)'):
        st.text('\n'.join(report.errors+report.warnings))
if not report.items:
    st.error('Aucun objet utilisable dans ce fichier.')
    st.stop()
path=ROOT/'data/catalog/forever.sqlite'
if not path.exists():
    st.error('La base française n’est pas encore construite.')
    st.code('.venv/bin/python -m gold_digger.build_database')
    st.stop()
try:
    catalog,recipes=read_database(str(path),path.stat().st_mtime_ns)
except Exception as exc:
    st.error(f'Impossible de lire la base : {exc}')
    st.stop()
items=catalog['items']
categories={r.id:recipe_categories(r,report.items,items) for r in recipes}

with st.sidebar:
    st.divider()
    st.header('Recherche et filtres')
    query=st.text_input('Rechercher une recette, un composant ou un métier',key='search',placeholder='Ex. : couture étoffe',help='Recherche sans distinction de majuscules ou d’accents. Tous les mots saisis doivent être présents.')
    professions=st.multiselect('Métiers',sorted({r.profession for r in recipes}),placeholder='Tous les métiers',key='professions')
    with st.expander('Types de recette',expanded=True):
        selected_types=[category for category in sorted({category for values in categories.values() for category in values})
                        if st.checkbox(category,value=True,key='recipe_type_'+category)]
        st.caption('Décoche un type pour le masquer. Tout décocher masque toutes les recettes. Catégories du catalogue Forever ; export HDV en secours. « Non renseigné » : aucune catégorie disponible.')
    min_skill=st.number_input('Compétence minimale',min_value=1,max_value=450,value=1,step=1,key='min_skill')
    max_skill=st.number_input('Compétence maximale',min_value=1,max_value=450,value=300,step=1,key='max_skill')
    include_unknown=st.checkbox('Inclure les compétences inconnues',value=False,key='include_unknown')
    st.caption('Niveau requis pour apprendre la recette, bornes min/max incluses. Les niveaux inconnus sont affichés seulement si la case est cochée.')
    st.divider()
    st.header('Achats et production')
    use_merchants=st.checkbox('Comparer les prix marchands',value=True,key='use_merchants')
    price_policy=st.selectbox('Tarif marchand', ['Prudent : plus haut prix observé','Meilleur prix observé'],key='price_policy',disabled=not use_merchants)
    policy='conservative' if price_policy.startswith('Prudent') else 'best'
    st.caption('Tous les calculs portent sur une fabrication. Les lots marchands nécessaires sont payés entiers ; les composants restants sont affichés.')
    st.divider()
    auction_fee=st.number_input('Commission HDV simulée (%)',min_value=0,max_value=100,value=5,step=1,key='auction_fee',help='Hypothèse modifiable pour estimer la revente HDV. Les dépôts perdus sur les invendus ne sont pas inclus.')
    disenchant_seconds=st.number_input('Désenchantement : secondes par objet',min_value=0.1,max_value=60.0,value=3.0,step=0.1,key='disenchant_seconds',help='3 secondes de base (Wowhead, sort 13262). Augmente cette durée pour inclure le ramassage ou la latence.')
    minimum_roi=st.number_input('Rentabilité minimale (%)',min_value=0.0,value=0.0,step=1.0,key='min_roi')
    mode=st.selectbox('Afficher',['Rentables','Rentables HDV','Rentables PNJ','Rentables désenchantement','Rentables désenchantement seul','Toutes les recettes','Non rentables','Données insuffisantes','Exclues'],key='status')
    sort_label=st.selectbox('Trier par',['Rentabilité (%)','Bénéfice par fabrication','Bénéfice PNJ (po/min)','Bénéfice HDV estimé (po/min)','Bénéfice désenchantement estimé (po/min)','Désenchantement seul (po/min)'],key='sort')
    timed_only=st.checkbox('Durée de fabrication connue uniquement',value=False,key='timed_only')

eligible=[r for r in recipes if recipe_matches(r,professions,max_skill,include_unknown,min_skill) and set(selected_types).intersection(categories[r.id])]
offers=catalog['merchant_offers'] if use_merchants else {}
with st.spinner('Calcul des coûts HDV et marchands…'):
    results=calculate(eligible,report.items,catalog['vendor_prices'],offers,policy)
auctions={r.recipe.id:estimate_auction(r,report.items,auction_fee) for r in results}
disenchants={r.recipe.id:estimate_disenchant(r,report.items,catalog.get('disenchant',{}),auction_fee,disenchant_seconds) for r in results}
direct_items={i.item_id:estimate_direct_disenchant(i.item_id,report.items,catalog.get('disenchant',{}),auction_fee,disenchant_seconds)
              for r in results for i in r.recipe.outputs}
direct_disenchants={r.recipe.id:(direct_items[r.recipe.outputs[0].item_id] if len({i.item_id for i in r.recipe.outputs})==1
                              else DisenchantEstimate(reason='Recette sans équipement unique à comparer')) for r in results}
statuses={r.recipe.id:profitability(r,auctions[r.recipe.id],disenchants[r.recipe.id],direct_disenchants[r.recipe.id]) for r in results}
counts=Counter(statuses.values())
metrics=st.columns(4)
metrics[0].metric('Recettes analysées',len(eligible))
metrics[1].metric('Recettes rentables',sum(n for s,n in counts.items() if s.startswith('Rentable ')))
metrics[2].metric('Données à compléter',counts['Données insuffisantes'])
metrics[3].metric('Objets dans le scan HDV',len(report.items))
st.caption('Les recettes utilisent les stocks indépendamment. Leurs bénéfices ne s’additionnent pas. Les délais de récupération et l’accès aux recettes restent à vérifier en jeu.')
if use_merchants:
    st.caption('Marchands : stocks illimités observés en jeu. Les tarifs dépendent parfois de la réputation et de l’accès au vendeur ; le mode prudent utilise le prix unitaire le plus élevé relevé.')


def name(r):
    return item_name(r.recipe.outputs[0].item_id,items,report.items,r.recipe.name) if r.recipe.outputs else r.recipe.name


def selected_roi(r):
    return filter_roi(r,auctions[r.recipe.id],mode,disenchants[r.recipe.id],direct_disenchants[r.recipe.id])


def matches(r):
    if timed_only and mode!='Rentables désenchantement seul' and not (r.recipe.cast_time_ms is not None and r.recipe.cast_time_ms>0):
        return False
    text=' '.join([name(r),r.recipe.name,r.recipe.id,r.recipe.profession,*categories[r.recipe.id]]+[item_name(i.item_id,items,report.items,i.name) for i in (*r.recipe.ingredients,*r.recipe.outputs)])
    if not search_matches(query,text):
        return False
    channel_profit={'Rentables HDV':auctions[r.recipe.id].profit,'Rentables PNJ':r.first_profit,'Rentables désenchantement':disenchants[r.recipe.id].profit,'Rentables désenchantement seul':direct_disenchants[r.recipe.id].profit}
    if mode=='Rentables' and not statuses[r.recipe.id].startswith('Rentable '):
        return False
    if mode in channel_profit and (channel_profit[mode] is None or channel_profit[mode]<=0):
        return False
    allowed={'Non rentables':{'Non rentable'},'Données insuffisantes':{'Données insuffisantes'},'Exclues':{'Exclue'}}
    if mode in allowed and statuses[r.recipe.id] not in allowed[mode]:
        return False
    roi=selected_roi(r)
    return minimum_roi==0 or (roi is not None and roi>=minimum_roi)


filtered=[r for r in results if matches(r)]
auction_rates={r.recipe.id:estimate_auction(r,report.items,auction_fee).gold_per_minute for r in filtered}
key={'Bénéfice HDV estimé (po/min)':lambda r:auction_rates[r.recipe.id] if auction_rates[r.recipe.id] is not None else float('-inf'),
     'Bénéfice désenchantement estimé (po/min)':lambda r:disenchants[r.recipe.id].gold_per_minute if disenchants[r.recipe.id].gold_per_minute is not None else float('-inf'),
     'Désenchantement seul (po/min)':lambda r:direct_disenchants[r.recipe.id].gold_per_minute if direct_disenchants[r.recipe.id].gold_per_minute is not None else float('-inf'),
     'Bénéfice PNJ (po/min)':lambda r:r.gold_per_minute if r.gold_per_minute is not None else float('-inf'),
     'Rentabilité (%)':lambda r:selected_roi(r) if selected_roi(r) is not None else float('-inf'),
     'Bénéfice par fabrication':lambda r:r.first_profit if r.first_profit is not None else float('-inf')}[sort_label]
filtered.sort(key=key,reverse=True)


def row(r):
    auction=auctions[r.recipe.id]
    de=disenchants[r.recipe.id]
    roi=selected_roi(r)
    hdv_roi=auction_roi(r,auction)
    return {'Recette':name(r),
        'Bénéfice PNJ (po/min)':round(r.gold_per_minute,6) if r.gold_per_minute is not None else None,
        'Bénéfice HDV estimé (po/min)':round(auction.gold_per_minute,6) if auction.gold_per_minute is not None else None,
        'Bénéfice désenchantement estimé (po/min)':round(de.gold_per_minute,6) if de.gold_per_minute is not None else None,
        'Désenchantement : chances et quantités':'; '.join(prefix+label+suffix for prefix,label,_,suffix in outcome_labels(de,items,report.items)) or '—',
        'Métier':r.recipe.profession,'Compétence requise':r.recipe.skill_required,'Type de recette':', '.join(categories[r.recipe.id]),
        'Rentabilité (%)':round(roi,2) if roi is not None else None,
        'Rentabilité HDV estimée (%)':round(hdv_roi,2) if hdv_roi is not None else None,
        'Rentabilité PNJ (%)':round(r.batch_roi,2) if r.batch_roi is not None else None,
        'Durée / fabrication (s)':r.recipe.cast_time_ms/1000 if r.recipe.cast_time_ms is not None else None,
        'Coût de fabrication':money(r.investment) if r.first_cost is not None else '—',
        'Bénéfice PNJ / fabrication':money(r.profit) if r.first_cost is not None else '—',
        'Bénéfice HDV estimé / fabrication':money(auction.profit),
        'Bénéfice désenchantement estimé / fabrication':money(round(de.profit)) if de.profit is not None else '—',
        'Désenchantement : motif':de.reason or 'Estimation Classic non vérifiée sur Forever',
        'Composants par fabrication':'; '.join(f'{i.quantity} × {item_name(i.item_id,items,report.items,i.name)}' for i in r.recipe.ingredients),
        'Statut':statuses[r.recipe.id],
        'Wowhead':wowhead_url(r.recipe.outputs[0].item_id) if r.recipe.outputs else None,
        'Limite / motif':r.reason or r.stop_reason,'Identifiant':r.recipe.id}


ranking,disenchant_market_tab,coverage,method=st.tabs(['Classement','Désenchantement HDV','Base de données','Méthode'])
with ranking:
    if min_skill>max_skill:
        st.error('La compétence minimale doit être inférieure ou égale à la compétence maximale.')
    st.subheader(f'{len(filtered)} recette(s)')
    st.caption('Désenchantement seul : achat d’un équipement au prix unitaire HDV le plus bas disponible, puis revente moyenne des matériaux après commission. Le temps compte uniquement un désenchantement. Valeur positive = achat rentable en moyenne ; valeur négative = perte. Le filtre « Rentables désenchantement seul » inclut ces opportunités même si le craft est impossible ou déficitaire ; son seuil en % est calculé sur le prix de l’équipement. Le filtre général « Rentables » et les statuts incluent également cette voie. Cette colonne couvre les équipements des recettes affichées, pas tous les équipements du marché.')
    st.caption('Désenchantement : valeur moyenne des matériaux × chances d’obtention, moins commission HDV et coût du craft. Quantités et chances affichées par objet désenchanté ; quantités moyennes supposées uniformes dans chaque intervalle. Le débit inclut la fabrication et le désenchantement de tous les objets produits, avec le délai de récupération si celui-ci est plus long. Un résultat individuel peut être déficitaire. Bonus de désenchantement non inclus.')
    st.warning('Probabilités de désenchantement estimées : tables Classic utilisées par Professions_Forever, tranches de niveaux issues du client Forever. Les taux, exceptions et exclusions ne sont pas confirmés pour tous les objets sur Forever.')
    st.caption('« Rentables » inclut toute ligne bénéficiaire dans au moins une des quatre voies, y compris le désenchantement seul. Le filtre « Rentables désenchantement » et le tri dédié permettent de les isoler. Le seuil de rentabilité utilise le canal sélectionné, ou le meilleur des quatre.')
    st.caption('Tous les résultats portent sur une fabrication, qui peut produire plusieurs objets. Rentabilité PNJ = bénéfice ÷ coût des achats nécessaires × 100.')
    st.caption('Or/min : bénéfice net, temps de fabrication et délais de récupération connus. Achats, déplacements, vente, latence et bonus personnels non inclus. Les durées inconnues ou instantanées n’ont pas de débit calculé.')
    st.caption(f'HDV : estimation pour une fabrication, au plus bas prix unitaire des annonces du scan, moins {auction_fee} % de commission simulée et le coût des composants. Vente non garantie ; dépôts perdus sur les invendus non inclus. « — » : donnée manquante ou calcul non applicable. Le débit HDV utilise le même temps de référence que le PNJ, sans inclure le temps nécessaire pour vendre. Sans durée de fabrication positive connue, les débits sont indisponibles.')
    if not filtered:
        st.info('Aucune recette ne correspond à ces filtres.')
    else:
        table([row(r) for r in filtered],component_links=[
            [(i.quantity,item_name(i.item_id,items,report.items,i.name),i.item_id) for i in r.recipe.ingredients]
            for r in filtered],disenchant_links=[outcome_labels(disenchants[r.recipe.id],items,report.items) for r in filtered])
        exports=[]
        for r in filtered:
            exports.append({**row(r),'investissement_cuivre':r.investment,'benefice_cuivre':r.profit,'benefice_hdv_estime_cuivre':estimate_auction(r,report.items,auction_fee).profit,'commission_hdv_pourcent':auction_fee,'source':r.recipe.source,'build':r.recipe.build,'duree_reference_ms':r.reference_time_ms,'source_duree':r.recipe.timing_source,'build_duree':r.recipe.timing_build})
            exports[-1].update(benefice_desenchantement_estime_cuivre=disenchants[r.recipe.id].profit,duree_cycle_desenchantement_ms=disenchants[r.recipe.id].duration_ms,secondes_desenchantement_par_objet=disenchant_seconds,source_desenchantement=catalog.get('disenchant_info',{}).get('source'),preuve_desenchantement=catalog.get('disenchant_info',{}).get('evidence'))
            direct=direct_disenchants[r.recipe.id]
            exports[-1].update(achat_equipement_cuivre=direct.purchase_cost,benefice_desenchantement_seul_cuivre=direct.profit,motif_desenchantement_seul=direct.reason)
        st.download_button('Exporter le classement',export_csv(exports),'gold_digger_classement.csv','text/csv')
        st.divider()
        chosen=st.selectbox('Détailler une recette',filtered,format_func=lambda r:f'{name(r)} · {r.recipe.profession} · {r.recipe.id}',key='recipe_detail')
        st.markdown('<h3>'+text_link(name(chosen),wowhead_url(chosen.recipe.outputs[0].item_id) if chosen.recipe.outputs else None)+'</h3>',unsafe_allow_html=True)
        st.write(f'**{chosen.recipe.profession}** · Compétence requise : **{chosen.recipe.skill_required if chosen.recipe.skill_required is not None else "inconnue"}**')
        st.write(chosen.reason or chosen.stop_reason)
        st.write('**Tous les composants consommés**')
        components=components_table(chosen.recipe,items,report.items,offers,1,policy)
        components=[{k:v for k,v in component.items() if k!='Pour le lot'} for component in components]
        table(components)
        st.download_button('Exporter la liste des composants',export_csv(components),'gold_digger_composants.csv','text/csv')
        st.write('**Objets fabriqués**')
        table([{'Objet':item_name(i.item_id,items,report.items,i.name),'Par fabrication':i.quantity,'Wowhead':wowhead_url(i.item_id)} for i in chosen.recipe.outputs])
        st.write('**Désenchantement des équipements fabriqués**')
        direct=direct_disenchants[chosen.recipe.id]
        if direct.profit is not None:
            st.write(f'**Achat HDV → désenchantement seul (1 objet)** : achat **{money(direct.purchase_cost)}**, matériaux après commission **{money(round(direct.net))}**, bénéfice moyen **{money(round(direct.profit))}**, soit **{direct.gold_per_minute:.6f} po/min**.')
        else:
            st.caption('Désenchantement seul : '+direct.reason)
        de=disenchants[chosen.recipe.id]
        if de.outcomes:
            loot=[]
            for o in de.outcomes:
                material=report.items.get(o['item_id'])
                unit=min(t.price for t in material.tiers) if material and material.tiers else None
                loot.append({'Équipement':item_name(o['output_id'],items),
                    'Composant':item_name(o['item_id'],items),
                    'Chance par objet (%)':o['probability']*100,
                    'Quantité minimale si obtenu':o['min_quantity'],
                    'Quantité maximale si obtenu':o['max_quantity'],
                    'Quantité moyenne / fabrication':o['output_quantity']*o['probability']*(o['min_quantity']+o['max_quantity'])/2,
                    'Prix unitaire HDV':money(unit),'Wowhead':wowhead_url(o['item_id']),
                    'Fiabilité':o['evidence'],'Source':o['source']})
            table(loot)
            st.download_button('Exporter le désenchantement',export_csv(loot),'gold_digger_desenchantement.csv','text/csv')
        if de.profit is not None:
            st.write(f'Valeur moyenne brute des matériaux : **{money(round(de.gross))}**. Bénéfice moyen après commission et coût du craft : **{money(round(de.profit))}**.')
            if de.gold_per_minute is not None:
                st.write(f'Bénéfice moyen : **{de.gold_per_minute:.6f} po/min**, pour un cycle de **{de.duration_ms/1000:g} secondes**.')
        elif de.reason:
            st.caption(de.reason)
        if chosen.recipe.tools:
            st.write('**Outils réutilisables à posséder**')
            table([{'Outil':item_name(i.item_id,items,report.items,i.name),'Quantité':i.quantity,'Wowhead':wowhead_url(i.item_id)} for i in chosen.recipe.tools])
            st.caption('Les outils ne sont pas consommés et ne sont pas rachetés à chaque fabrication.')
        if chosen.purchases:
            st.write('**Achats nécessaires pour une fabrication**')
            shopping=[]
            for p in chosen.purchases:
                shopping.append({'Composant':item_name(p['item_id'],items,report.items,p['name']),
                    'Acheter chez':p.get('channel','HDV'),'Vendeur':p.get('vendor','HDV'),
                    'Quantité achetée':p['quantity'],'Restant après fabrication':p.get('surplus',0),
                    'Coût':money(p['cost']),'Wowhead':wowhead_url(p['item_id']),'Source':p.get('source')})
            table(shopping)
            st.download_button('Exporter les achats optimisés',export_csv(shopping),'gold_digger_achats.csv','text/csv')
        with st.expander('Détail du calcul et conditions'):
            auction=estimate_auction(chosen,report.items,auction_fee)
            if auction.profit is None:
                st.write('Revente HDV : '+auction.reason)
            else:
                st.write(f'Revente HDV estimée par fabrication : **{money(auction.gross)}** brut, **{money(auction.net)}** après commission simulée de {auction_fee} %. Bénéfice après achat des composants : **{money(auction.profit)}**.')
            if auction.gold_per_minute is not None:
                st.write(f'Bénéfice HDV estimé : **{auction.gold_per_minute:.6f} po/min** pour une fabrication.')
            if chosen.recipe.cast_time_ms is None:
                st.write('Durée de fabrication non documentée : bénéfice par minute indisponible.')
            elif chosen.recipe.cast_time_ms==0:
                st.write('La source indique une fabrication instantanée. Aucun bénéfice par minute n’est calculé sans durée de cycle mesurable.')
            else:
                st.write(f'Durée de base : **{chosen.recipe.cast_time_ms/1000:g} s par fabrication** (une fabrication peut produire plusieurs objets).')
                if chosen.gold_per_minute is not None:
                    st.write(f'Bénéfice net : **{chosen.gold_per_minute:.6f} po/min** · Temps de fabrication : **{chosen.crafting_time_ms/60000:.3f} min**.')
                if chosen.recipe.cooldown_seconds:
                    st.write(f'Délai de récupération : {chosen.recipe.cooldown_seconds} s. Le débit utilise des cycles de réutilisation : le plus grand du temps de fabrication et du délai, y compris après la dernière activation.')
            if chosen.recipe.timing_source:
                st.markdown(f'[Source de la durée]({chosen.recipe.timing_source}) · build {chosen.recipe.timing_build}')
            st.write(f'Première fabrication : achat {money(chosen.first_cost)}, revente {money(chosen.revenue)}, bénéfice {money(chosen.first_profit)}.')
            st.write(f'Seuil de compétence : {chosen.recipe.skill_basis}.')
            if chosen.recipe.skill_source:
                st.markdown(f'[Source du niveau requis]({chosen.recipe.skill_source})')
            for condition in chosen.recipe.restrictions:
                st.write('• '+condition)
            st.markdown(f'[Recette complète en français]({chosen.recipe.source})')
            st.caption('Prix de revente : '+' ; '.join(chosen.price_sources))

with disenchant_market_tab:
    st.subheader('Acheter à l’HDV puis désenchanter')
    st.caption('Tous les équipements identifiés dans le scan HDV, avec ou sans recette. Les filtres de métier, compétence et recette ne s’appliquent pas ici. L’export HDV, la commission et la durée de désenchantement de la barre latérale sont partagés.')
    st.caption('Calcul pour un seul objet acheté au plus bas prix unitaire disponible : valeur moyenne des matériaux après commission − prix d’achat. Le débit compte uniquement le désenchantement ; achats, ramassage, déplacements et délai de vente ne sont pas chronométrés. Le stock affiché couvre tous les paliers connus, pas uniquement le prix le plus bas.')
    st.warning('Les probabilités restent des estimations Classic appliquées aux tranches Forever, avec les mêmes exceptions et limites que le classement. Une moyenne positive ne garantit pas un gain sur chaque objet.')
    market_records=analyze_disenchant_market(report.items,items,catalog.get('disenchant',{}),auction_fee,disenchant_seconds)
    market_counts=Counter(record['status'] for record in market_records)
    summary=st.columns(3)
    summary[0].metric('Équipements du scan',len(market_records))
    summary[1].metric('Achats rentables',market_counts['Rentable'])
    summary[2].metric('Non calculables',market_counts['Non calculable'])
    unknown_types=sum(catalog_category(items.get(i,{})) is None and item_category(m.item_type)=='Non renseigné' for i,m in report.items.items())
    if unknown_types:
        st.caption(f'{unknown_types} objet(s) du scan sans catégorie identifiable ne peuvent pas être classés comme équipements.')
    controls=st.columns(3)
    with controls[0]:
        de_query=st.text_input('Rechercher un équipement ou un matériau',key='de_market_search')
    with controls[1]:
        de_mode=st.selectbox('Équipements à afficher',['Rentables','Tous les équipements','Non rentables','Non calculables'],key='de_market_status')
    with controls[2]:
        de_sort=st.selectbox('Trier les équipements par',['Bénéfice (po/min)','Rentabilité (%)','Bénéfice par objet','Prix d’achat croissant'],key='de_market_sort')
    de_min_roi=st.number_input('Rentabilité minimale des achats (%)',min_value=0.0,value=0.0,step=1.0,key='de_market_min_roi')
    de_filtered=[]
    for record in market_records:
        expected_status={'Rentables':'Rentable','Non rentables':'Non rentable','Non calculables':'Non calculable'}.get(de_mode)
        if expected_status and record['status']!=expected_status:
            continue
        if de_min_roi and (record['roi'] is None or record['roi']<de_min_roi):
            continue
        text=' '.join([record['name'],str(record['item_id'])]+[item_name(o['item_id'],items,report.items) for o in record['estimate'].outcomes])
        if search_matches(de_query,text):
            de_filtered.append(record)
    def market_sort_key(record):
        value={'Bénéfice (po/min)':record['estimate'].gold_per_minute,'Rentabilité (%)':record['roi'],
               'Bénéfice par objet':record['estimate'].profit,'Prix d’achat croissant':record['purchase_cost']}[de_sort]
        return (value is None, 0 if value is None else value if de_sort=='Prix d’achat croissant' else -value)
    de_filtered.sort(key=market_sort_key)
    st.write(f'**{len(de_filtered)} équipement(s)**')
    if not de_filtered:
        st.info('Aucun équipement ne correspond à ces filtres.')
    else:
        de_rows=[]
        for record in de_filtered:
            estimate=record['estimate']
            de_rows.append({'Objet':record['name'],
                'Désenchantement seul (po/min)':round(estimate.gold_per_minute,6) if estimate.gold_per_minute is not None else None,
                'Prix d’achat HDV':money(record['purchase_cost']),
                'Valeur moyenne nette des matériaux':money(round(estimate.net)) if estimate.net is not None else '—',
                'Bénéfice moyen par objet':money(round(estimate.profit)) if estimate.profit is not None else '—',
                'Rentabilité (%)':round(record['roi'],2) if record['roi'] is not None else None,
                'Désenchantement : chances et quantités':'; '.join(prefix+label+suffix for prefix,label,_,suffix in outcome_labels(estimate,items,report.items)) or '—',
                'Niveau d’objet':record['item_level'],'Stock HDV connu':record['stock'],
                'Statut':record['status'],'Motif':estimate.reason,'Identifiant':record['item_id'],
                'Wowhead':wowhead_url(record['item_id'])})
        table(de_rows,disenchant_links=[outcome_labels(r['estimate'],items,report.items) for r in de_filtered])
        de_exports=[{**row,'achat_cuivre':record['purchase_cost'],'valeur_nette_moyenne_cuivre':record['estimate'].net,
                     'benefice_moyen_cuivre':record['estimate'].profit,'commission_hdv_pourcent':auction_fee,
                     'secondes_par_objet':disenchant_seconds,'source':catalog.get('disenchant_info',{}).get('source'),
                     'fiabilite':catalog.get('disenchant_info',{}).get('evidence')} for row,record in zip(de_rows,de_filtered)]
        st.download_button('Exporter les équipements HDV',export_csv(de_exports),'gold_digger_desenchantement_hdv.csv','text/csv',key='de_market_export')

with coverage:
    st.subheader('Catalogue français')
    de_info=catalog.get('disenchant_info',{})
    if de_info:
        st.write(f"**{sum(bool(p['outcomes']) for p in catalog['disenchant'].values())} objets avec une table de désenchantement estimée** (pas uniquement les objets fabriqués).")
        st.markdown(f"[Source des tables de désenchantement]({de_info['source']}) · tranches client {de_info['build']} · {de_info['evidence']}.")
        if de_info.get('local_policy'):
            st.caption(de_info['local_policy'])
        st.markdown(f"[Durée de base du désenchantement]({de_info['timing_source']}) : {de_info['cast_time_ms']/1000:g} s par objet, modifiable dans les filtres.")
    if catalog.get('last_audit'):
        audit=catalog['last_audit']
        st.caption(f"Dernier audit : {audit['checked_at'][:10]} · {audit['summary']['wowhead_skill_reviews']} niveaux recoupés sur Wowhead Forever. Les autres niveaux proviennent des sources d’apprentissage du catalogue ; ce contrôle ne certifie pas chaque donnée en jeu.")
    known_times=sum(r.cast_time_ms is not None and r.cast_time_ms>0 for r in recipes)
    st.write(f'**{known_times} recettes avec durée positive documentée**, {sum(r.cast_time_ms==0 for r in recipes)} instantanées, {sum(r.cast_time_ms is None for r in recipes)} sans durée associée.')
    timing_builds=sorted({r.timing_build for r in recipes if r.timing_build})
    if timing_builds:
        st.caption('Durées issues du client Forever : '+', '.join(timing_builds)+'. Source antérieure au catalogue : seuls les sorts aux composants et productions concordants sont associés ; les changements de vitesse ultérieurs ne sont pas vérifiés.')
    st.write(f'**{len(items):,} objets · {len(recipes):,} recettes · {sum(r.skill_required is not None for r in recipes):,} compétences requises connues**'.replace(',',' '))
    st.write(f'**{len(catalog["merchant_offers"])} composants marchands**, avec {sum(map(len,catalog["merchant_offers"].values()))} offres à stock illimité. Les autres achats restent limités aux paliers HDV connus.')
    rows=[]
    for profession in sorted({r.profession for r in recipes}):
        group=[r for r in recipes if r.profession==profession]
        rows.append({'Métier':profession,'Recettes':len(group),'Compétence connue':sum(r.skill_required is not None for r in group),'Compétence inconnue':sum(r.skill_required is None for r in group)})
    table(rows)
    st.caption('Build : '+', '.join(sorted({r.build for r in recipes}))+'. Base publiée : '+catalog['imported_at'])
    st.markdown(f'[Source des observations marchandes]({catalog["merchant_source"]}) · Capture intégrée : {catalog["merchant_capture"]}')
    st.write('Les observations marchandes couvrent les builds 1.60.1.69913 à 1.60.1.70959. Elles ne constituent pas un inventaire exhaustif des marchands actuels. Les quantités limitées et les achats en monnaies spéciales sont exclus.')
    st.write('Les compétences inconnues sont masquées par défaut. Aucun seuil jaune n’est utilisé comme niveau d’apprentissage.')

with method:
    st.markdown('''
**Le tri initial utilise le meilleur pourcentage de rentabilité connu entre vente PNJ, vente HDV, craft puis désenchantement et achat HDV puis désenchantement, ou celui du canal sélectionné.** Les bénéfices absolus restent disponibles comme tris secondaires.

**Désenchantement : bénéfice moyen = somme(chance × quantité moyenne × prix unitaire HDV × nombre d’objets produits), après commission HDV, moins les achats du craft.** Les quantités moyennes supposent une distribution uniforme entre minimum et maximum. Le calcul conserve les fractions de cuivre jusqu’à l’affichage. Le temps de cycle est le maximum entre le délai de récupération et la somme du temps de craft et des désenchantements. Un prix de matériau manquant rend le bénéfice indisponible, jamais nul. Les chances restent visibles même sans prix.

Les probabilités, exceptions et exclusions proviennent des données Classic utilisées par l’addon Professions_Forever ; seules les tranches de niveaux proviennent du client Forever. Il s’agit d’une simulation non certifiée pour chaque objet Forever. Les matériaux sont vendus directement, sans conversion d’essences ; aucun bonus de désenchantement, dont les bonus de camp, n’est simulé. Les recettes uniquement rentables par cette voie sont incluses dans « Rentables ».

Le moteur compare les paliers HDV connus avec une offre marchande à stock illimité. Il peut acheter une partie à l’HDV et le reste au marchand. Les lots marchands sont payés entiers, les unités restantes sont affichées et ne sont pas revendues fictivement.

Chaque recette est évaluée pour exactement une fabrication, même lorsqu’elle est déficitaire. Changer le tri ne modifie pas la quantité ni le coût calculés. Une fabrication peut produire plusieurs objets : toutes les quantités produites sont comptées dans la revente PNJ et HDV.

Le tarif prudent est le plus haut prix unitaire observé pour ce composant. Le meilleur tarif observé est disponible en option ; il peut demander une réputation ou un accès au vendeur particulier. Aucun prix d’achat n’est déduit du prix de revente au PNJ.

**Or/minute = bénéfice net par fabrication en or × 60 / durée de référence en secondes.** Sans délai connu, la durée vaut celle d’une fabrication. Avec un délai connu, le calcul utilise le plus grand du délai et de la durée de fabrication par cycle : c’est un débit de réutilisation, qui inclut l’attente après la dernière activation. Les délais inconnus ne peuvent pas être pris en compte. Une durée absente ou nulle ne donne jamais une rentabilité infinie. Les bonus de vitesse, les trajets, les achats et la vente ne sont pas chronométrés.

La liste des composants contient les quantités consommées ; les outils réutilisables sont présentés séparément. Les composants intermédiaires sont achetés directement. L’apprentissage, les outils déjà possédés, les bonus personnels et les temps de déplacement ne sont pas inclus dans le coût de fabrication.

Les recettes sont analysées indépendamment, sans partage de budget ni de stock. La disponibilité réelle des recettes, les délais inconnus et les accès marchands restent à vérifier en jeu.
''')
