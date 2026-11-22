from dataclasses import dataclass, field


@dataclass(frozen=True)
class Tier:
    price: int
    quantity: int


@dataclass(frozen=True)
class MarketItem:
    id: int
    name: str
    npc: int | None
    tiers: tuple[Tier, ...]
    total_quantity: int
    item_type: str = ""


@dataclass(frozen=True)
class Ingredient:
    item_id: int
    quantity: int
    name: str = ""


@dataclass(frozen=True)
class Recipe:
    id: str
    name: str
    profession: str
    ingredients: tuple[Ingredient, ...]
    outputs: tuple[Ingredient, ...]
    source: str
    build: str
    restrictions: tuple[str, ...] = ()
    cooldown_seconds: int | None = None  # None: non documenté, 0: absence vérifiée
    exclusion: str = ""
    skill_required: int | None = None
    skill_basis: str = "Inconnue"
    skill_source: str = ""
    tools: tuple[Ingredient, ...] = ()
    cast_time_ms: int | None = None
    timing_source: str = ""
    timing_build: str = ""


@dataclass
class Result:
    recipe: Recipe
    status: str
    reason: str = ""
    revenue: int | None = None
    first_cost: int | None = None
    first_profit: int | None = None
    roi: float | None = None
    crafts: int = 0
    investment: int = 0
    profit: int | None = 0
    stock_capacity: int = 0
    stop_reason: str = ""
    purchases: list[dict] = field(default_factory=list)
    price_sources: list[str] = field(default_factory=list)
    batch_roi: float | None = None
    unlimited_supply: bool = False
    analysis_limit: int | None = None


    @property
    def crafting_time_ms(self):
        duration=self.recipe.cast_time_ms
        return self.crafts*duration if self.crafts>0 and duration is not None and duration>0 else None

    @property
    def reference_time_ms(self):
        """Temps de cycles : inclut le délai connu avant réutilisation, même après le dernier."""
        if self.crafting_time_ms is None:
            return None
        cycle=max(self.recipe.cast_time_ms,(self.recipe.cooldown_seconds or 0)*1000)
        return self.crafts*cycle

    @property
    def gold_per_minute(self):
        duration=self.reference_time_ms
        return self.profit*6/duration if duration and self.profit is not None else None
