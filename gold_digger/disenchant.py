"""Espérance de revente des composants de désenchantement, pour un craft."""
from dataclasses import dataclass
from math import isfinite
from .market import money


def validate_reference(data):
    if data.get('game') != 'wow-forever' or data.get('schema_version') != 1:
        raise ValueError('Référence de désenchantement incompatible')
    if not all(data.get(key) for key in ('source', 'build', 'evidence', 'provenance')):
        raise ValueError('Provenance du désenchantement manquante')
    for outcomes in data['tables'].values():
        ids = set()
        for o in outcomes:
            if (type(o['item_id']) is not int or o['item_id'] <= 0 or o['item_id'] in ids
                    or not 0 < o['probability'] <= 1
                    or type(o['min_quantity']) is not int or type(o['max_quantity']) is not int
                    or not 1 <= o['min_quantity'] <= o['max_quantity']):
                raise ValueError('Résultat de désenchantement invalide')
            ids.add(o['item_id'])
        if not outcomes or sum(o['probability'] for o in outcomes) > 1.00000001:
            raise ValueError('Probabilités de désenchantement invalides')
    for b in data['brackets']:
        if (b['class_id'] not in (2, 4) or b['quality'] not in (2, 3, 4)
                or not 0 < b['min_level'] <= b['max_level']
                or str(b['table_id']) not in data['tables']):
            raise ValueError('Tranche de désenchantement invalide')
    for i, a in enumerate(data['brackets']):
        for b in data['brackets'][i+1:]:
            if (a['class_id'], a['quality']) == (b['class_id'], b['quality']) and max(a['min_level'], b['min_level']) <= min(a['max_level'], b['max_level']):
                raise ValueError('Tranches de désenchantement superposées')
    if any(str(t) not in data['tables'] for t in data['overrides'].values()):
        raise ValueError('Exception de désenchantement invalide')


def item_profile(item_id, item, data):
    """Never guess from the character's required level or the profession skill."""
    if item.get('class_id') not in (2, 4):
        return None, 'Objet hors armes et armures'
    if item.get('quality') is None or item.get('item_level') is None:
        return None, 'Qualité ou niveau d’objet inconnu'
    if item['quality'] not in (2, 3, 4):
        return None, 'Qualité hors des tables de désenchantement'
    if item_id in data['never']:
        return None, 'Exclu par la référence Classic ; désenchantabilité Forever à vérifier'
    table = data['overrides'].get(str(item_id))
    if table is None:
        table = next((b['table_id'] for b in data['brackets']
                      if b['class_id'] == item['class_id'] and b['quality'] == item['quality']
                      and b['min_level'] <= item['item_level'] <= b['max_level']), None)
    if table is None:
        return None, 'Niveau d’objet hors des tables documentées'
    outcomes = data['tables'][str(table)]
    # A partial table must never become a misleading complete expected value.
    if abs(sum(o['probability'] for o in outcomes)-1) > 1e-8:
        return None, 'Table de désenchantement incomplète'
    return str(table), ''


@dataclass(frozen=True)
class DisenchantEstimate:
    gross: float | None = None
    net: float | None = None
    profit: float | None = None
    gold_per_minute: float | None = None
    duration_ms: float | None = None
    outcomes: tuple = ()
    reason: str = ''
    purchase_cost: int | None = None


def estimate_direct_disenchant(item_id, market, profiles, fee_percent=5, seconds_per_item=3.0):
    """Buy exactly one listed equipment item; no craft inputs, time or cooldown."""
    if type(fee_percent) is not int or not 0 <= fee_percent <= 100:
        raise ValueError('Commission HDV invalide')
    if not isfinite(seconds_per_item) or seconds_per_item <= 0:
        raise ValueError('Durée de désenchantement invalide')
    profile = profiles.get(item_id)
    if not profile or not profile.get('outcomes'):
        return DisenchantEstimate(reason=(profile or {}).get('reason', 'Désenchantement non documenté'))
    outcomes = tuple({**o, 'output_id': item_id, 'output_quantity': 1,
                      'source': profile['source'], 'evidence': profile['evidence']}
                     for o in profile['outcomes'])
    equipment = market.get(item_id)
    tiers = [t for t in equipment.tiers if t.quantity > 0] if equipment else []
    if not tiers:
        return DisenchantEstimate(outcomes=outcomes, reason='Équipement absent des annonces HDV disponibles')
    cost = min(t.price for t in tiers)
    gross = 0.0
    for o in outcomes:
        material = market.get(o['item_id'])
        if not material or not material.tiers:
            return DisenchantEstimate(outcomes=outcomes, purchase_cost=cost,
                                     reason=f"Prix HDV absent : composant {o['item_id']}")
        gross += o['probability'] * (o['min_quantity']+o['max_quantity'])/2 * min(t.price for t in material.tiers)
    net = gross * (100-fee_percent)/100
    profit = net-cost
    duration = seconds_per_item*1000
    return DisenchantEstimate(gross, net, profit, profit*6/duration, duration, outcomes, purchase_cost=cost)


def estimate_disenchant(result, market, profiles, fee_percent=5, seconds_per_item=3.0):
    if type(fee_percent) is not int or not 0 <= fee_percent <= 100:
        raise ValueError('Commission HDV invalide')
    if not isfinite(seconds_per_item) or seconds_per_item <= 0:
        raise ValueError('Durée de désenchantement invalide')
    outcomes = []
    for output in result.recipe.outputs:
        profile = profiles.get(output.item_id)
        if not profile or not profile.get('outcomes'):
            return DisenchantEstimate(reason=(profile or {}).get('reason', 'Désenchantement non documenté'))
        for o in profile['outcomes']:
            outcomes.append({**o, 'output_id': output.item_id, 'output_quantity': output.quantity,
                             'source': profile['source'], 'evidence': profile['evidence']})
    if not outcomes:
        return DisenchantEstimate(reason='Aucun équipement produit')
    details = tuple(outcomes)
    if result.status == 'Exclue' or result.first_cost is None or result.crafts != 1:
        return DisenchantEstimate(outcomes=details, reason='Une fabrication calculable est nécessaire')
    gross = 0.0
    for o in outcomes:
        material = market.get(o['item_id'])
        if not material or not material.tiers:
            return DisenchantEstimate(outcomes=details, reason=f"Prix HDV absent : composant {o['item_id']}")
        expected_quantity = o['probability'] * (o['min_quantity']+o['max_quantity']) / 2
        gross += o['output_quantity'] * expected_quantity * min(t.price for t in material.tiers)
    # This is an expectation, not an actual stack sale: retain fractional copper.
    net = gross * (100-fee_percent)/100
    profit = net-result.investment
    cast = result.recipe.cast_time_ms
    duration = None
    if cast is not None and cast > 0:
        active = cast + sum(o.quantity for o in result.recipe.outputs)*seconds_per_item*1000
        duration = max(active, (result.recipe.cooldown_seconds or 0)*1000)
    return DisenchantEstimate(gross, net, profit, profit*6/duration if duration else None, duration, details)


def outcome_labels(estimate, items, market=None):
    """Chance, quantity and lowest listed unit price; missing prices stay explicit."""
    labels = []
    multiple = len({o['output_id'] for o in estimate.outcomes}) > 1
    for o in estimate.outcomes:
        name = items.get(o['item_id'], {}).get('name_fr', f"Objet {o['item_id']}")
        amount = str(o['min_quantity']) if o['min_quantity'] == o['max_quantity'] else f"{o['min_quantity']}–{o['max_quantity']}"
        prefix = items.get(o['output_id'], {}).get('name_fr', str(o['output_id'])) + ' → ' if multiple else ''
        material=(market or {}).get(o['item_id'])
        price=min((t.price for t in material.tiers),default=None) if material else None
        price_label=f'{money(price)} / unité' if price is not None else 'prix HDV absent'
        labels.append((prefix, name, o['item_id'], f" ({price_label}) : {o['probability']*100:g} % × {amount}"))
    return labels
