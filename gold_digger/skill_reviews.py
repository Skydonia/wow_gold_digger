"""Explicit, build-scoped skill reviews; never infer learning rank from skill-up colors."""
from dataclasses import replace
from urllib.parse import urlsplit
from .collect_timings import quantities


def apply_skill_reviews(recipes,payload):
    if payload.get('game')!='wow-forever' or payload.get('schema_version')!=1:
        raise ValueError('Révisions de compétences incompatibles')
    lookup={r.id:r for r in recipes}
    seen=set()
    for review in payload['reviews']:
        rid=review['recipe_id']
        if rid in seen or rid not in lookup:
            raise ValueError('Révision dupliquée ou recette absente : '+rid)
        seen.add(rid)
        r=lookup[rid]
        url=urlsplit(review.get('source',''))
        rank=review.get('skill_required')
        if (url.scheme!='https' or url.netloc!='www.wowhead.com' or not url.path.startswith('/forever/')
            or type(rank) is not int or not 0<=rank<=450 or not review.get('checked_on') or not review.get('evidence')):
            raise ValueError('Révision non sourcée ou niveau invalide : '+rid)
        if (r.build!=review['matched_catalog_build'] or
            quantities([vars(i) for i in r.ingredients])!=quantities(review['ingredients']) or
            quantities([vars(i) for i in r.outputs])!=quantities(review['outputs']) or
            r.skill_required not in (review['previous_skill_required'],rank)):
            raise ValueError('La recette a changé : révision à recontrôler pour '+rid)
        restrictions=r.restrictions
        if r.skill_required!=rank:
            restrictions=tuple(t for t in restrictions if not ('compétence' in t and t.startswith(('S’apprend','S\'apprend'))))
        lookup[rid]=replace(r,skill_required=rank,skill_basis='Seuil d’apprentissage recoupé sur Wowhead Forever le '+review['checked_on'],skill_source=review['source'],restrictions=restrictions)
    return [lookup[r.id] for r in recipes]
