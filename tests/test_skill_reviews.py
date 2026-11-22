from copy import deepcopy
from dataclasses import replace
import pytest
from gold_digger.models import Recipe,Ingredient
from gold_digger.skill_reviews import apply_skill_reviews


def fixture():
    recipe=Recipe('engineering:3931','Dynamite','Ingénierie',(Ingredient(1,3),),(Ingredient(2,2),),'source','build',skill_required=65,
                  restrictions=('S’apprend auprès des maîtres (compétence 65)','Requiert Enclume'))
    review=dict(recipe_id=recipe.id,skill_required=75,previous_skill_required=65,matched_catalog_build='build',
                checked_on='2026-11-22',source='https://www.wowhead.com/forever/spell=3931/coarse-dynamite',evidence='Quick Facts : Engineering 75',
                ingredients=[vars(i) for i in recipe.ingredients],outputs=[vars(i) for i in recipe.outputs])
    return recipe,dict(game='wow-forever',schema_version=1,reviews=[review])


def test_review_corrects_skill_without_changing_recipe_and_removes_stale_requirement():
    r,p=fixture()
    corrected=apply_skill_reviews([r],p)[0]
    assert corrected.skill_required==75 and corrected.skill_source==p['reviews'][0]['source']
    assert corrected.ingredients==r.ingredients and corrected.outputs==r.outputs
    assert corrected.restrictions==('Requiert Enclume',)
    assert apply_skill_reviews([corrected],p)==[corrected]


@pytest.mark.parametrize('field,value',[('build','other'),('skill_required',80),('outputs',(Ingredient(2,3),))])
def test_review_rejects_changed_catalog(field,value):
    r,p=fixture()
    with pytest.raises(ValueError):apply_skill_reviews([replace(r,**{field:value})],p)


def test_review_rejects_classic_source_duplicates_and_bool_rank():
    r,p=fixture()
    bad=deepcopy(p);bad['reviews'][0]['source']='https://www.wowhead.com/classic/spell=3931'
    with pytest.raises(ValueError):apply_skill_reviews([r],bad)
    bad=deepcopy(p);bad['reviews']*=2
    with pytest.raises(ValueError):apply_skill_reviews([r],bad)
    bad=deepcopy(p);bad['reviews'][0]['skill_required']=True
    with pytest.raises(ValueError):apply_skill_reviews([r],bad)
