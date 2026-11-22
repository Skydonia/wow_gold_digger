from collections import defaultdict
from .models import Recipe, MarketItem, Result


def purchase(tiers, quantity):
    """Coût exact d'un préfixe de paliers, sans extrapolation."""
    cost, used = 0, []
    for tier in tiers:
        take = min(quantity, tier.quantity)
        if take:
            cost += take * tier.price
            used.append({"unit_price": tier.price, "quantity": take, "cost": take * tier.price})
            quantity -= take
        if not quantity:
            break
    if quantity:
        raise ValueError("Stock connu insuffisant")
    return cost, used


def _analyze_ah(recipe: Recipe, market: dict[int, MarketItem], vendor_prices=None) -> Result:
    result = Result(recipe, "Données insuffisantes")
    if recipe.exclusion:
        result.status, result.reason = "Exclue", recipe.exclusion
        return result
    if not recipe.outputs or not recipe.ingredients:
        result.status, result.reason = "Exclue", "Résultat vendable ou composants non documentés"
        return result
    vendor_prices = vendor_prices or {}
    revenue = 0
    for output in recipe.outputs:
        item = market.get(output.item_id)
        price = item.npc if item else None
        source = "CSV HDV"
        if price is None:
            record = vendor_prices.get(str(output.item_id))
            if record and record.get("source") and record.get("build") == recipe.build:
                price, source = record["sell_copper"], record["source"]
        if price is None:
            result.reason = f"Prix PNJ absent : {output.name or output.item_id}"
            return result
        revenue += output.quantity * price
        result.price_sources.append(f"{output.item_id} : {source}")
    result.revenue = revenue
    if revenue == 0:
        result.status, result.reason = "Exclue", "Résultat sans valeur de revente PNJ"
        return result
    needed = defaultdict(int)
    for ingredient in recipe.ingredients:
        needed[ingredient.item_id] += ingredient.quantity
    missing = [str(i) for i in needed if i not in market or not market[i].tiers]
    if missing:
        result.reason = "Paliers HDV absents pour les composants : " + ", ".join(missing)
        return result
    capacity = min(sum(t.quantity for t in market[i].tiers) // q for i, q in needed.items())
    result.stock_capacity = capacity
    if capacity == 0:
        result.reason = "Stock connu insuffisant pour une fabrication entière"
        return result

    def cost(n):
        return sum(purchase(market[i].tiers, q * n)[0] for i, q in needed.items())

    result.first_cost = cost(1)
    result.first_profit = revenue - result.first_cost
    result.roi = result.first_profit / result.first_cost * 100
    if result.first_profit <= 0:
        result.status = "Non rentable"
        result.stop_reason = "Bénéfice nul ou négatif dès la première fabrication"
        return result
    # Les coûts marginaux sont croissants : recherche du dernier craft strictement rentable.
    low, high = 1, capacity
    while low < high:
        middle = (low + high + 1) // 2
        if cost(middle) - cost(middle - 1) < revenue:
            low = middle
        else:
            high = middle - 1
    result.crafts = low
    if recipe.cooldown_seconds is not None and recipe.cooldown_seconds > 0:
        result.crafts = 1
        result.status = "Cooldown"
        result.stop_reason = "Une activation ; délai avant la suivante"
    else:
        result.status = "Rentable"
        result.stop_reason = "Paliers connus épuisés" if low == capacity else "Fabrication suivante non rentable"
    result.investment = cost(result.crafts)
    result.profit = result.crafts * revenue - result.investment
    for item_id, per_craft in needed.items():
        _, tiers = purchase(market[item_id].tiers, per_craft * result.crafts)
        result.purchases.extend({"item_id": item_id, "name": market[item_id].name, **t} for t in tiers)
    return result


def merchant_reference(offers, policy='conservative'):
    """Les observations restent des prix observés, jamais des prix de revente × 4."""
    from fractions import Fraction
    valid=[o for o in offers if o.get('unlimited') and o.get('source') and
           type(o.get('lot_price_copper')) is int and o['lot_price_copper']>0 and
           type(o.get('lot_quantity')) is int and o['lot_quantity']>0]
    if not valid:
        return None
    if policy=='best':
        return min(valid,key=lambda o:(Fraction(o['lot_price_copper'],o['lot_quantity']),o['lot_quantity']))
    return max(valid,key=lambda o:(Fraction(o['lot_price_copper'],o['lot_quantity']),-o['lot_quantity']))


def supply_purchase(tiers, quantity, merchant=None):
    """Minimum exact HDV + lots marchands ; seulement les points de rupture sont évalués."""
    if merchant is None:
        cost,rows=purchase(tiers,quantity)
        return cost,[{**r,'channel':'HDV','surplus':0} for r in rows]
    lot=merchant['lot_quantity']
    price=merchant['lot_price_copper']
    ceiling=(quantity+lot-1)//lot
    candidates={0,quantity//lot,ceiling}
    cumulative=0
    for tier in tiers:
        cumulative+=tier.quantity
        k=(quantity-cumulative)//lot
        candidates.update((max(0,min(ceiling,k)),max(0,min(ceiling,k+1))))
    best=None
    for packs in candidates:
        ah_quantity=max(0,quantity-packs*lot)
        try:
            ah_cost,rows=purchase(tiers,ah_quantity)
        except ValueError:
            continue
        cost=ah_cost+packs*price
        surplus=max(0,packs*lot-quantity)
        score=(cost,surplus,ah_quantity)
        if best is None or score<best[0]:
            rows=[{**r,'channel':'HDV','surplus':0} for r in rows]
            if packs:
                rows.append({'unit_price':price//lot if price%lot==0 else None,
                    'quantity':packs*lot,'cost':packs*price,'channel':'Marchand','surplus':surplus,
                    'lot_quantity':lot,'lot_price_copper':price,'packs':packs,
                    'vendor':merchant.get('vendor_name',merchant.get('vendor','Marchand')),
                    'source':merchant['source']})
            best=(score,rows)
    if best is None:
        raise ValueError('Stock insuffisant')
    return best[0][0],best[1]


def analyze(recipe, market, vendor_prices=None, merchant_offers=None, max_crafts=None, merchant_policy='conservative', objective='profit'):
    if max_crafts is not None and (type(max_crafts) is not int or not 1<=max_crafts<=10000):
        raise ValueError("La limite de simulation doit être comprise entre 1 et 10 000")
    requested_limit=max_crafts
    if objective not in ('profit','rate'):
        raise ValueError('Objectif de calcul inconnu')
    if objective=='rate' and not (recipe.cast_time_ms is not None and recipe.cast_time_ms>0):
        objective='profit'
    baseline=_analyze_ah(recipe,market,vendor_prices)
    # Sans offres, préserver l'analyse exacte historique des seuls paliers HDV.
    merchant_offers=merchant_offers or {}
    references={i.item_id:merchant_reference(merchant_offers.get(i.item_id,[]),merchant_policy) for i in recipe.ingredients}
    if not any(references.values()):
        if objective=='rate' and baseline.crafts>1:
            # Sans lots marchands, le coût moyen ne peut qu'augmenter.
            quantities=defaultdict(int)
            for i in recipe.ingredients:
                quantities[i.item_id]+=i.quantity
            low,high=1,min(baseline.crafts,max_crafts or baseline.crafts)
            while low<high:
                n=(low+high+1)//2
                cost=sum(purchase(market[i].tiers,q*n)[0] for i,q in quantities.items())
                if cost==n*baseline.first_cost:
                    low=n
                else:
                    high=n-1
            max_crafts=low
        if max_crafts is not None and baseline.crafts>max_crafts:
            baseline.crafts=max_crafts
            baseline.investment=0
            baseline.purchases=[]
            quantities=defaultdict(int)
            for i in recipe.ingredients:
                quantities[i.item_id]+=i.quantity
            for item_id,q in quantities.items():
                cost,rows=purchase(market[item_id].tiers,q*max_crafts)
                baseline.investment+=cost
                baseline.purchases.extend({'item_id':item_id,'name':market[item_id].name,**r} for r in rows)
            baseline.profit=baseline.crafts*baseline.revenue-baseline.investment
            baseline.stop_reason='Limite de simulation atteinte'
        baseline.batch_roi=baseline.profit/baseline.investment*100 if baseline.investment else baseline.roi
        baseline.analysis_limit=requested_limit
        if objective=='rate' and baseline.crafts and baseline.status!='Cooldown':
            baseline.stop_reason='Lot au meilleur bénéfice par minute dans la simulation'
        return baseline
    if baseline.revenue is None or baseline.revenue==0 or recipe.exclusion:
        return baseline
    if max_crafts is None:
        max_crafts=1000
    if type(max_crafts) is not int or not 1<=max_crafts<=10000:
        raise ValueError('La limite de simulation doit être comprise entre 1 et 10 000')
    result=Result(recipe,'Données insuffisantes',revenue=baseline.revenue,price_sources=baseline.price_sources,analysis_limit=max_crafts)
    needed=defaultdict(int)
    names={}
    for i in recipe.ingredients:
        needed[i.item_id]+=i.quantity
        names[i.item_id]=i.name
    tiers={i:market[i].tiers if i in market else () for i in needed}
    missing=[names[i] or str(i) for i in needed if not tiers[i] and not references[i]]
    if missing:
        result.reason='Composants indisponibles : '+', '.join(missing)
        return result
    finite=[sum(t.quantity for t in tiers[i])//q for i,q in needed.items() if not references[i]]
    result.unlimited_supply=not finite
    capacity=min(finite) if finite else max_crafts
    result.stock_capacity=capacity
    limit=min(capacity,max_crafts)
    cooldown=recipe.cooldown_seconds is not None and recipe.cooldown_seconds>0
    if cooldown:
        limit=min(limit,1)
    if not limit:
        result.reason='Stock connu insuffisant pour une fabrication entière'
        return result
    def cost(n,details=False):
        total=0
        purchases=[]
        for i,q in needed.items():
            amount,rows=supply_purchase(tiers[i],q*n,references[i])
            total+=amount
            if details:
                purchases.extend({'item_id':i,'name':names[i] or (market[i].name if i in market else str(i)),**r} for r in rows)
        return total,purchases
    result.first_cost=cost(1)[0]
    result.first_profit=result.revenue-result.first_cost
    result.roi=result.first_profit/result.first_cost*100
    # Les lots produisent des coûts marginaux non monotones : pas de recherche binaire.
    best=(0,0,0)
    for n in range(1,limit+1):
        investment=cost(n)[0]
        profit=n*result.revenue-investment
        better=(profit>best[0])
        if objective=='rate' and best[1]:
            comparison=profit*best[1]-best[0]*n
            better=comparison>0 or (comparison==0 and profit>best[0])
        if profit>0 and better:
            best=(profit,n,investment)
    result.profit,result.crafts,result.investment=best
    if not result.crafts:
        result.status='Non rentable'
        result.stop_reason='Aucun lot rentable dans la limite simulée'
        result.batch_roi=result.roi
        return result
    result.batch_roi=result.profit/result.investment*100
    result.status='Cooldown' if cooldown else 'Rentable'
    result.stop_reason=('Une activation ; délai avant la suivante' if cooldown else
        'Limite de simulation atteinte' if result.crafts==max_crafts else
        'Stock HDV limitant' if result.crafts==capacity and finite else ('Lot au meilleur bénéfice par minute dans la simulation' if objective=='rate' else 'Lot au bénéfice maximal dans la simulation'))
    _,result.purchases=cost(result.crafts,True)
    return result



def analyze_single(recipe, market, vendor_prices=None, merchant_offers=None, merchant_policy='conservative'):
    """Price one craft independently of whether its output has a PNJ price."""
    result=Result(recipe,'Données insuffisantes',analysis_limit=1)
    if recipe.exclusion or not recipe.outputs or not recipe.ingredients:
        result.status='Exclue'
        result.reason=recipe.exclusion or 'Résultat vendable ou composants non documentés'
        return result
    offers=merchant_offers or {}
    quantities=defaultdict(int)
    names={}
    for ingredient in recipe.ingredients:
        quantities[ingredient.item_id]+=ingredient.quantity
        names[ingredient.item_id]=ingredient.name
    purchases=[]
    cost=0
    for item_id,quantity in quantities.items():
        item=market.get(item_id)
        reference=merchant_reference(offers.get(item_id,[]),merchant_policy)
        try:
            amount,rows=supply_purchase(item.tiers if item else (),quantity,reference)
        except ValueError:
            result.reason=f'Composant indisponible ou stock insuffisant : {names[item_id] or item_id}'
            return result
        cost+=amount
        purchases.extend({'item_id':item_id,'name':names[item_id] or (item.name if item else str(item_id)),**row} for row in rows)
    result.crafts=1
    result.first_cost=result.investment=cost
    result.purchases=purchases
    revenue=0
    for output in recipe.outputs:
        item=market.get(output.item_id)
        price=item.npc if item else None
        source='CSV HDV'
        if price is None:
            record=(vendor_prices or {}).get(str(output.item_id))
            if record and record.get('source') and record.get('build')==recipe.build:
                price,source=record['sell_copper'],record['source']
        if price is None:
            result.profit=None
            result.reason=f'Prix PNJ absent : {output.name or output.item_id}'
            return result
        revenue+=output.quantity*price
        result.price_sources.append(f'{output.item_id} : {source}')
    result.revenue=revenue
    result.profit=result.first_profit=revenue-cost
    result.roi=result.batch_roi=result.profit/cost*100 if cost else None
    cooldown=bool(recipe.cooldown_seconds and recipe.cooldown_seconds>0)
    result.status=('Cooldown' if cooldown else 'Rentable') if result.profit>0 else 'Non rentable'
    result.stop_reason=('Bénéfice PNJ nul ou négatif pour une fabrication' if result.profit<=0 else
                        'Délai de récupération pris en compte' if cooldown else 'Calcul pour une fabrication')
    return result
