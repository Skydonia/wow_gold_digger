import json
from pathlib import Path
from .models import Ingredient, Recipe


def load_catalog(path: Path):
    if path.suffix in {".sqlite", ".db"}:
        from .database import load_database
        return load_database(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("game") != "wow-forever":
        raise ValueError("Catalogue incompatible : schéma 1 et jeu wow-forever requis")
    recipes, seen = [], set()
    for raw in data["recipes"]:
        fields = dict(raw)
        for key in ("ingredients", "outputs"):
            fields[key] = tuple(Ingredient(**item) for item in raw[key])
            if any(type(i.item_id) is not int or i.item_id <= 0 or type(i.quantity) is not int or i.quantity <= 0 for i in fields[key]):
                raise ValueError(f"Quantité ou identifiant invalide : {raw['id']}")
        fields["restrictions"] = tuple(fields.get("restrictions", []))
        recipe = Recipe(**fields)
        if recipe.id in seen:
            raise ValueError(f"Recette dupliquée : {recipe.id}")
        if not recipe.source or not recipe.build:
            raise ValueError(f"Source ou build manquant : {recipe.id}")
        if recipe.cooldown_seconds is not None and (type(recipe.cooldown_seconds) is not int or recipe.cooldown_seconds < 0):
            raise ValueError(f"Cooldown invalide : {recipe.id}")
        seen.add(recipe.id)
        recipes.append(recipe)
    for item_id, record in data.get("vendor_prices", {}).items():
        if int(item_id) <= 0 or type(record.get("sell_copper")) is not int or record["sell_copper"] < 0 or not record.get("source") or not record.get("build"):
            raise ValueError(f"Prix PNJ invalide : {item_id}")
    return data, recipes
