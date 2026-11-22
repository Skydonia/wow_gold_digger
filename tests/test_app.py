from pathlib import Path
import pytest
import pandas as pd
from bs4 import BeautifulSoup
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]


def ranking_frame(app):
    html=next(m.proto.srcdoc for m in app.get('iframe') if '<table class="item-table">' in m.proto.srcdoc)
    soup=BeautifulSoup(html,'html.parser')
    headers=[cell.get_text() for cell in soup.select('thead th')]
    assert 'Wowhead' not in headers
    assert soup.select_one('tbody td a')['href'].startswith('https://www.wowhead.com/forever/fr/item=')
    frame=pd.DataFrame([[cell.get_text() for cell in row.select('td')] for row in soup.select('tbody tr')],columns=headers)
    for key in ('Compétence requise','Rentabilité (%)','Rentabilité HDV estimée (%)','Rentabilité PNJ (%)','Bénéfice PNJ (po/min)','Bénéfice HDV estimé (po/min)','Bénéfice désenchantement estimé (po/min)','Durée / fabrication (s)'):
        frame[key]=pd.to_numeric(frame[key],errors='coerce')
    return frame


def test_french_app_filters_percentage_and_merchants():
    if not (ROOT/'data/catalog/forever.sqlite').exists():
        pytest.skip('Base locale absente')
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=60).run()
    assert not app.exception
    assert app.title[0].value=='Gold Digger'
    assert app.sidebar.selectbox(key='sort').value=='Rentabilité (%)'
    assert app.sidebar.checkbox(key='use_merchants').value
    initial=ranking_frame(app)
    assert 'Fabrications retenues' not in initial
    assert all(w.key!='craft_limit' for w in app.sidebar.number_input)
    results=app.selectbox(key='recipe_detail').options
    assert results
    assert 'Bénéfice PNJ / fabrication' in initial and 'Bénéfice HDV estimé / fabrication' in initial
    app.sidebar.selectbox(key='status').set_value('Toutes les recettes').run()
    initial=ranking_frame(app).set_index('Identifiant').sort_index()
    app.sidebar.number_input(key='auction_fee').set_value(100).run()
    charged=ranking_frame(app).set_index('Identifiant').sort_index()
    assert charged['Bénéfice PNJ / fabrication'].tolist()==initial['Bénéfice PNJ / fabrication'].tolist()
    estimates=[v for v in charged['Bénéfice HDV estimé / fabrication'] if v!='—']
    assert estimates and all(v.startswith('−') for v in estimates)
    app.sidebar.number_input(key='auction_fee').set_value(5).run()
    app.sidebar.multiselect(key='professions').set_value(['Couture']).run()
    app.sidebar.number_input(key='max_skill').set_value(75).run()
    assert not app.exception
    app.sidebar.selectbox(key='status').set_value('Toutes les recettes').run()
    frame=ranking_frame(app)
    assert set(frame['Métier'])=={'Couture'}
    assert frame['Compétence requise'].max()<=75
    percentages=frame['Rentabilité (%)'].dropna().tolist()
    assert percentages==sorted(percentages,reverse=True)
    app.sidebar.text_input(key='search').set_value('aucun-objet-ne-porte-ce-nom').run()
    assert any('Aucune recette' in x.value for x in app.info)
    app.sidebar.text_input(key='search').set_value('fil').run()
    app.sidebar.checkbox(key='use_merchants').set_value(False).run()
    assert not app.exception


def test_gold_per_minute_sort():
    if not (ROOT/'data/catalog/forever.sqlite').exists():
        pytest.skip('Base locale absente')
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=60).run()
    app.sidebar.selectbox(key='sort').set_value('Bénéfice PNJ (po/min)').run()
    app.sidebar.checkbox(key='timed_only').set_value(True).run()
    assert not app.exception
    frame=ranking_frame(app)
    values=frame['Bénéfice PNJ (po/min)'].dropna().tolist()
    assert values and values==sorted(values,reverse=True)
    assert (frame['Durée / fabrication (s)']>0).all()


def test_auction_rate_sort_and_commission():
    if not (ROOT/'data/catalog/forever.sqlite').exists():
        pytest.skip('Base locale absente')
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=60).run()
    app.sidebar.selectbox(key='sort').set_value('Bénéfice HDV estimé (po/min)').run()
    assert not app.exception
    frame=ranking_frame(app)
    values=frame['Bénéfice HDV estimé (po/min)'].dropna().tolist()
    assert values and values==sorted(values,reverse=True)
    app.sidebar.number_input(key='auction_fee').set_value(100).run()
    assert not app.exception
    values=ranking_frame(app)['Bénéfice HDV estimé (po/min)'].dropna().tolist()
    assert values and all(v<0 for v in values)
    assert values==sorted(values,reverse=True)


def test_hdv_profitable_recipes_are_visible_without_pnj_profit():
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=60).run()
    assert not app.exception
    initial=ranking_frame(app)
    hdv_only=initial[initial['Statut']=='Rentable HDV']
    assert len(hdv_only)>0
    assert (hdv_only['Rentabilité HDV estimée (%)']>0).all()
    assert (hdv_only['Rentabilité PNJ (%)'].fillna(0)<=0).all()
    app.sidebar.selectbox(key='status').set_value('Rentables HDV').run()
    frame=ranking_frame(app)
    assert (frame['Rentabilité HDV estimée (%)']>0).all()
    assert set(hdv_only['Identifiant'])<=set(frame['Identifiant'])
    app.sidebar.number_input(key='min_roi').set_value(50).run()
    assert (ranking_frame(app)['Rentabilité HDV estimée (%)']>=50).all()
    app.sidebar.number_input(key='auction_fee').set_value(100).run()
    assert not app.exception
    assert any('Aucune recette' in x.value for x in app.info)


def test_search_and_skill_range():
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=60).run()
    app.sidebar.selectbox(key='status').set_value('Toutes les recettes').run()
    app.sidebar.number_input(key='min_skill').set_value(75).run()
    app.sidebar.number_input(key='max_skill').set_value(150).run()
    app.sidebar.text_input(key='search').set_value('  COUTURE  ').run()
    assert not app.exception
    frame=ranking_frame(app)
    assert len(frame)>0 and set(frame['Métier'])=={'Couture'}
    assert frame['Compétence requise'].between(75,150).all()
    app.sidebar.number_input(key='min_skill').set_value(151).run()
    assert not app.exception
    assert any('minimale' in error.value for error in app.error)
    app.sidebar.number_input(key='min_skill').set_value(75).run()
    assert not app.error and not app.exception
    assert len(ranking_frame(app))>0


def test_recipe_type_filter_combines_with_search_and_skill():
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=60).run()
    app.sidebar.selectbox(key='status').set_value('Toutes les recettes').run()
    checkboxes=[box for box in app.sidebar.checkbox if box.key.startswith('recipe_type_')]
    assert checkboxes and all(box.value for box in checkboxes)
    app.sidebar.checkbox(key='recipe_type_Équipement').set_value(False).run()
    assert not ranking_frame(app)['Type de recette'].str.contains('Équipement').any()
    for box in app.sidebar.checkbox:
        if box.key.startswith('recipe_type_'):
            box.set_value(box.key=='recipe_type_Équipement')
    app.run()
    assert not app.exception
    frame=ranking_frame(app)
    assert frame['Type de recette'].str.contains('Équipement').all()
    app.sidebar.number_input(key='max_skill').set_value(150).run()
    app.sidebar.text_input(key='search').set_value('couture').run()
    frame=ranking_frame(app)
    assert (frame['Compétence requise']<=150).all()
    assert frame['Type de recette'].str.contains('Équipement').all()
    assert set(frame['Métier'])=={'Couture'}
    app.sidebar.text_input(key='search').set_value('').run()
    for box in app.sidebar.checkbox:
        if box.key.startswith('recipe_type_'):
            box.set_value(box.key in ('recipe_type_Composants','recipe_type_Nourriture et boissons'))
    app.run()
    frame=ranking_frame(app)
    assert all(set(value.split(', ')) & {'Composants','Nourriture et boissons'} for value in frame['Type de recette'])
    for box in app.sidebar.checkbox:
        if box.key.startswith('recipe_type_'):
            box.set_value(box.key=='recipe_type_Non renseigné')
    app.run()
    assert ranking_frame(app)['Type de recette'].str.contains('Non renseigné').all()

    for box in app.sidebar.checkbox:
        if box.key.startswith('recipe_type_'):
            box.set_value(False)
    app.run()
    assert not app.exception
    assert any('Aucune recette' in x.value for x in app.info)


def test_disenchant_filter_rate_links_and_commission():
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=60).run()
    assert not app.exception
    assert any('Classic' in w.value for w in app.warning)
    initial=ranking_frame(app)
    app.sidebar.selectbox(key='status').set_value('Rentables désenchantement')
    app.sidebar.selectbox(key='sort').set_value('Bénéfice désenchantement estimé (po/min)').run()
    frame=ranking_frame(app)
    assert not app.exception and len(frame)>0
    assert set(frame['Identifiant'])<=set(initial['Identifiant'])
    assert frame['Type de recette'].str.contains('Équipement').all()
    values=frame['Bénéfice désenchantement estimé (po/min)'].dropna().tolist()
    assert values and all(v>0 for v in values)
    assert values==sorted(values,reverse=True)
    assert frame['Désenchantement : chances et quantités'].str.contains('%').all()
    soup=BeautifulSoup(next(m.proto.srcdoc for m in app.get('iframe') if 'Désenchantement : chances' in m.proto.srcdoc),'html.parser')
    headers=[c.get_text() for c in soup.select('th')]
    assert headers[1:4]==['Bénéfice PNJ (po/min)','Bénéfice HDV estimé (po/min)','Bénéfice désenchantement estimé (po/min)']
    chance_index=headers.index('Désenchantement : chances et quantités')
    assert soup.select_one('tbody tr').select('td')[chance_index].select_one('a')['href'].startswith('https://www.wowhead.com/forever/fr/item=')
    app.sidebar.number_input(key='disenchant_seconds').set_value(6.0).run()
    slowed=ranking_frame(app).set_index('Identifiant')
    for _,row in frame.iterrows():
        if pd.notna(row['Bénéfice désenchantement estimé (po/min)']):
            assert slowed.loc[row['Identifiant'],'Bénéfice désenchantement estimé (po/min)']<=row['Bénéfice désenchantement estimé (po/min)']
    app.sidebar.number_input(key='auction_fee').set_value(100).run()
    assert not app.exception and any('Aucune recette' in x.value for x in app.info)


def test_direct_disenchant_column_sort_filter_and_fee():
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=60).run()
    general=ranking_frame(app)
    app.sidebar.selectbox(key='status').set_value('Rentables désenchantement seul')
    app.sidebar.selectbox(key='sort').set_value('Désenchantement seul (po/min)').run()
    assert not app.exception
    frame=ranking_frame(app)
    assert set(frame['Identifiant'])<=set(general['Identifiant'])
    direct_only=general[general['Statut']=='Rentable désenchantement seul']
    assert len(direct_only)>0
    assert (direct_only['Rentabilité (%)']>0).all()
    rates=pd.to_numeric(frame['Désenchantement seul (po/min)'],errors='coerce').dropna().tolist()
    assert rates and all(v>0 for v in rates) and rates==sorted(rates,reverse=True)
    app.sidebar.number_input(key='min_roi').set_value(10).run()
    frame=ranking_frame(app)
    assert (frame['Rentabilité (%)']>=10).all()
    app.sidebar.number_input(key='auction_fee').set_value(100).run()
    assert not app.exception and any('Aucune recette' in x.value for x in app.info)
