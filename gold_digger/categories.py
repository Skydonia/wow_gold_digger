"""Recipe categories from catalog item classes, with HDV type as a fallback."""
import unicodedata


def item_category(item_type):
    normalized=''.join(c for c in unicodedata.normalize('NFKD',item_type.casefold().strip()) if not unicodedata.combining(c))
    if not normalized:
        return 'Non renseigné'
    family,_,subtype=normalized.partition('/')
    if family in ('armure','arme'):
        return 'Équipement'
    if family=='artisanat' or (family=='divers' and subtype=='reactif'):
        return 'Composants'
    if family=='consommable':
        if subtype=='nourriture & boissons':
            return 'Nourriture et boissons'
        if subtype in ('potions','elixirs','flacons'):
            return 'Potions, élixirs et flacons'
        if subtype=='bandages':
            return 'Bandages'
        return 'Autres consommables'
    if family in ('conteneur','carquois'):
        return 'Sacs et conteneurs'
    if family=='projectile':
        return 'Munitions'
    if family=='recette':
        return 'Plans et recettes'
    return 'Autres'



def catalog_category(item):
    """Group client class/subclass IDs documented by the source item browser."""
    cls=item.get('class_id')
    sub=item.get('subclass_id')
    if cls is None:
        return None
    if cls in (2,4):
        return 'Équipement'
    if cls in (5,7) or (cls==15 and sub==1):
        return 'Composants'
    if cls==0:
        if sub==5:
            return 'Nourriture et boissons'
        if sub in (1,2,3):
            return 'Potions, élixirs et flacons'
        if sub==7:
            return 'Bandages'
        return 'Autres consommables'
    if cls in (1,11):
        return 'Sacs et conteneurs'
    if cls==6:
        return 'Munitions'
    if cls==9:
        return 'Plans et recettes'
    return 'Autres'


def recipe_categories(recipe, market, items=None):
    """Use output classes even when the item is absent from the scan."""
    categories=set()
    for output in recipe.outputs:
        category=catalog_category((items or {}).get(output.item_id,{}))
        if category is None:
            category=item_category(market[output.item_id].item_type if output.item_id in market else '')
        categories.add(category)
    return tuple(sorted(categories)) or ('Non renseigné',)
