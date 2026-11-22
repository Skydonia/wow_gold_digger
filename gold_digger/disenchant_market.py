"""Analyse de tout le scan HDV, indépendante des recettes et des métiers."""
from .categories import catalog_category, item_category
from .disenchant import estimate_direct_disenchant
from .presentation import item_name


def analyze_disenchant_market(market, items, profiles, fee_percent=5, seconds_per_item=3.0):
    records=[]
    for item_id,offer in market.items():
        item=items.get(item_id,{})
        category=catalog_category(item) or item_category(offer.item_type)
        if category!='Équipement':
            continue
        estimate=estimate_direct_disenchant(item_id,market,profiles,fee_percent,seconds_per_item)
        roi=estimate.profit/estimate.purchase_cost*100 if estimate.profit is not None and estimate.purchase_cost else None
        status=('Rentable' if estimate.profit>0 else 'Non rentable') if estimate.profit is not None else 'Non calculable'
        records.append({'item_id':item_id,'name':item_name(item_id,items,market),'item_level':item.get('item_level'),
                        'estimate':estimate,'roi':roi,'status':status,
                        'stock':sum(t.quantity for t in offer.tiers),
                        'purchase_cost':min((t.price for t in offer.tiers if t.quantity>0),default=None)})
    return records
