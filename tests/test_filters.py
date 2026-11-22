from dataclasses import replace
from gold_digger.models import Recipe
from gold_digger.presentation import recipe_matches, search_matches


def test_skill_range_inclusive_and_unknown():
    recipe=Recipe('id','Recette','Couture',(),(),'source','build',skill_required=75)
    assert recipe_matches(recipe,['Couture'],150,False,75)
    assert recipe_matches(recipe,[],75,False,75)
    assert not recipe_matches(recipe,[],150,False,76)
    assert not recipe_matches(recipe,[],74,False,1)
    unknown=replace(recipe,skill_required=None)
    assert not recipe_matches(unknown,[],150,False,75)
    assert recipe_matches(unknown,[],150,True,75)
    assert not recipe_matches(unknown,[],75,True,150)
    assert not recipe_matches(recipe,['Forge'],150,False,75)


def test_search_words_accents_and_case():
    text='Couture : Étoffe en lin et fil renforcé'
    assert search_matches('  ETOFFE   couture ',text)
    assert search_matches('renforce',text)
    assert search_matches('   ',text)
    assert not search_matches('étoffe cuivre',text)
