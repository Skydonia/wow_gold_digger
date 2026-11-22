"""Estimation de la revente HDV de la production évaluée."""
from dataclasses import dataclass

from .models import MarketItem, Result


@dataclass(frozen=True)
class AuctionEstimate:
    gross: int | None = None
    net: int | None = None
    profit: int | None = None
    reason: str = ''
    gold_per_minute: float | None = None


def estimate_auction(result: Result, market: dict[int, MarketItem], fee_percent: int = 5) -> AuctionEstimate:
    """Use lowest listed unit prices, not presumed buyer demand.

    The commission is a simulation parameter. Net proceeds are rounded down
    once for the whole batch, since auction stack sizes are not specified.
    """
    if type(fee_percent) is not int or not 0 <= fee_percent <= 100:
        raise ValueError('La commission doit être un entier entre 0 et 100 %.')
    if result.crafts <= 0 or result.first_cost is None:
        return AuctionEstimate(reason='Aucune fabrication calculable à comparer.')
    if not result.recipe.outputs:
        return AuctionEstimate(reason='Objets fabriqués non documentés.')
    gross = 0
    for output in result.recipe.outputs:
        item = market.get(output.item_id)
        if not item or not item.tiers:
            return AuctionEstimate(reason=f'Prix HDV absent : {output.name or output.item_id}.')
        unit_price = min(t.price for t in item.tiers)
        gross += unit_price * output.quantity * result.crafts
    net = gross * (100 - fee_percent) // 100
    profit = net-result.investment
    duration = result.reference_time_ms
    rate = profit*6/duration if duration else None
    return AuctionEstimate(gross=gross, net=net, profit=profit, gold_per_minute=rate)


def profitability(result, auction, disenchant=None, direct=None):
    """Common classification for the table, counters and filters."""
    if direct is not None and direct.profit is not None and direct.profit>0:
        craft_status=profitability(result,auction,disenchant)
        return (craft_status+' et désenchantement seul' if craft_status.startswith('Rentable ')
                else 'Rentable désenchantement seul')
    if result.status=='Exclue':
        return 'Exclue'
    pnj=result.first_profit is not None and result.first_profit>0
    hdv=auction.profit is not None and auction.profit>0
    de=disenchant is not None and disenchant.profit is not None and disenchant.profit>0
    if de:
        channels=([ 'PNJ' ] if pnj else [])+(['HDV'] if hdv else [])+['désenchantement']
        return 'Rentable '+' et '.join(channels)
    if pnj and hdv:
        return 'Rentable PNJ et HDV'
    if hdv:
        return 'Rentable HDV'
    if pnj:
        return 'Rentable PNJ'
    if result.first_profit is None or auction.profit is None or (disenchant is not None and disenchant.outcomes and disenchant.profit is None):
        return 'Données insuffisantes'
    return 'Non rentable'


def auction_roi(result, auction):
    return auction.profit/result.investment*100 if auction.profit is not None and result.investment>0 else None


def filter_roi(result, auction, mode, disenchant=None, direct=None):
    pnj=result.batch_roi
    hdv=auction_roi(result,auction)
    if mode=='Rentables HDV':
        return hdv
    if mode=='Rentables PNJ':
        return pnj
    de=auction_roi(result,disenchant) if disenchant is not None else None
    if mode=='Rentables désenchantement':
        return de
    direct_roi=direct.profit/direct.purchase_cost*100 if direct is not None and direct.profit is not None and direct.purchase_cost else None
    if mode=='Rentables désenchantement seul':
        return direct_roi
    known=[v for v in (pnj,hdv,de,direct_roi) if v is not None]
    return max(known) if known else None
