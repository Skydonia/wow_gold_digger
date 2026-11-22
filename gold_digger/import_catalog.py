"""Import explicite et reproductible des pages publiques Endgame Tools."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import ssl
import certifi
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup
from .models import Ingredient, Recipe
from .market import parse_market

BASE = "https://endgametools.com/en/wow-forever"
PROFESSIONS = {
    "alchemy": "Alchimie", "blacksmithing": "Forge", "enchanting": "Enchantement",
    "engineering": "Ingénierie", "herbalism": "Herboristerie", "leatherworking": "Travail du cuir",
    "mining": "Minage", "skinning": "Dépeçage", "tailoring": "Couture",
    "cooking": "Cuisine", "first-aid": "Secourisme", "fishing": "Pêche", "poisons": "Poisons",
}


def item_ref(anchor):
    match = re.search(r"/items/(\d+)(?:$|[?#])", anchor.get("href", ""))
    if not match:
        raise ValueError("Lien objet absent")
    text = anchor.get_text(" ", strip=True)
    quantity = re.match(r"^(\d+)\s*×\s*(.*)$", text)
    if re.match(r"^\d+\s*[-–]\s*\d+\s*×", text):
        raise ValueError("Rendement variable non modélisé")
    return Ingredient(int(match[1]), int(quantity[1]) if quantity else 1,
                      quantity[2] if quantity else text)


def parse_profession(html, slug):
    soup = BeautifulSoup(html, "html.parser")
    build_match = re.search(r"build\s+(\d+\.\d+\.\d+\.\d+)", soup.get_text(" ", strip=True), re.I)
    if not build_match:
        raise ValueError(f"Build du jeu absent : {slug}")
    build = build_match[1]
    nodes = soup.select("#recipes li.recipe")
    if not nodes:
        raise ValueError(f"Aucune recette reconnue : {slug}")
    recipes = []
    for node in nodes:
        raw_id = node.get("id", "")
        if not re.fullmatch(r"r\d+", raw_id):
            raise ValueError("Identifiant de recette invalide")
        title = node.select_one(".recipe-title")
        if title is None:
            raise ValueError(f"Titre absent : {raw_id}")
        output_line = next((p for p in node.select('p') if p.get_text(' ',strip=True).startswith(('Makes ', 'Fabrique '))), None)
        output_links = (output_line or title).select('a[href*="/items/"]')
        name = title.get_text(" ", strip=True)
        ingredients, outputs, restrictions = [], [], []
        exclusion = ""
        try:
            if output_links:
                outputs = [item_ref(a) for a in output_links]
                name = outputs[0].name
            else:
                exclusion = "Résultat objet ou rendement non documenté"
            reagent_line = next((p for p in node.select("p") if p.get_text(strip=True).startswith("Reagents:")), None)
            if reagent_line is not None:
                ingredients = [item_ref(a) for a in reagent_line.select("a")]
            if not ingredients:
                exclusion = exclusion or "Composants non documentés"
        except ValueError as exc:
            exclusion = str(exc)
        for p in node.select("p"):
            if p is title or p is output_line or "recipe-skill" in p.get("class", []):
                continue
            text = p.get_text(" ", strip=True)
            if text and not text.startswith("Reagents:"):
                restrictions.append(text)
        category = node.find_parent("section")
        category_name = category.select_one("h2").get_text(" ", strip=True) if category else ""
        if category_name.startswith("Camping"):
            exclusion = "Construction de camp : résultat vendable non confirmé"
        # Le silence de la source ne signifie pas absence de cooldown.
        cooldown = None
        for text in restrictions:
            match = re.search(r"(?:Cooldown|cooldown):?\s*(\d+)\s*(day|hour|min|sec)", text)
            if match:
                cooldown = int(match[1]) * {"day":86400,"hour":3600,"min":60,"sec":1}[match[2]]
        recipes.append(Recipe(f"{slug}:{raw_id[1:]}", name, PROFESSIONS[slug],
            tuple(ingredients), tuple(outputs), f"{BASE}/professions/{slug}#{raw_id}", build,
            tuple(restrictions), cooldown, exclusion))
    return build, recipes


def parse_vendor_price(html, item_id, build):
    soup = BeautifulSoup(html, "html.parser")
    canonical = soup.select_one('link[rel="canonical"]')
    if not canonical or canonical.get("href", "").rstrip("/") != f"{BASE}/items/{item_id}":
        return None
    fields = {dt.get_text(" ", strip=True): dt.find_next_sibling("dd").get_text(" ", strip=True)
              for dt in soup.select("dt") if dt.find_next_sibling("dd")}
    if fields.get("Client build") != build or fields.get("Item ID") != str(item_id):
        return None
    sell_line = next((p for p in soup.select("p") if p.get_text(" ", strip=True).startswith("Sell price")), None)
    if sell_line is None:
        return None
    # Les unités sont portées par le texte accessible, une seule fois par pièce.
    coins = re.findall(r"(\d[\d,]*)\s+(Gold|Silver|Copper)", sell_line.get_text(" ", strip=True))
    if not coins:
        return None
    amount = sum(int(q.replace(",", "")) * {"Gold":10000,"Silver":100,"Copper":1}[unit] for q, unit in coins)
    modified = None
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or "{}")
            for entry in payload.get("@graph", []):
                if entry.get("@type") == "WebPage":
                    modified = entry.get("dateModified")
        except (ValueError, AttributeError):
            pass
    return {"sell_copper": amount, "source": f"{BASE}/items/{item_id}", "build": build,
            "build_basis": "Client build vérifié sur la fiche objet",
            "source_modified": modified}


def fetch(url, cache, refresh=False):
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / (hashlib.sha256(url.encode()).hexdigest() + ".html")
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")
    request = Request(url, headers={"User-Agent": "GoldDigger/0.1 (local profession analysis)"})
    with urlopen(request, timeout=35, context=ssl.create_default_context(cafile=certifi.where())) as response:
        html = response.read().decode("utf-8")
    path.write_text(html, encoding="utf-8")
    time.sleep(0.15)
    return html


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/catalog/forever.json"))
    parser.add_argument("--market", type=Path, default=Path("data/input/export_hdv.csv"))
    parser.add_argument("--cache", type=Path, default=Path("data/cache/endgame"))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--vendor-limit", type=int, default=0, help="Nombre maximal de fiches PNJ à compléter ; 0 = aucune")
    args = parser.parse_args()
    records, coverage, failures = [], [], []
    for slug, name in PROFESSIONS.items():
        try:
            build, recipes = parse_profession(fetch(f"{BASE}/professions/{slug}", args.cache, args.refresh), slug)
            records.extend(asdict(r) for r in recipes)
            coverage.append({"profession": name, "recipes": len(recipes), "build": build, "status": "Importé"})
            print(f"{name}: {len(recipes)} recettes, build {build}", flush=True)
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            coverage.append({"profession": name, "recipes": 0, "build": "", "status": str(exc)})
            print(f"Échec {name}: {exc}", flush=True)
    if not records:
        raise SystemExit("Aucun catalogue importé ; le fichier existant est conservé.")
    prices = {}
    if args.output.exists():
        prices = {k: v for k, v in json.loads(args.output.read_text()).get("vendor_prices", {}).items()
                  if v.get("build_basis") == "Client build vérifié sur la fiche objet"}
    market = parse_market(args.market.read_bytes()).items if args.market.exists() else {}
    needed = {}
    for r in records:
        if not r["exclusion"]:
            for output in r["outputs"]:
                i = output["item_id"]
                if (i not in market or market[i].npc is None) and (args.refresh or str(i) not in prices or prices[str(i)].get("build") != r["build"]):
                    needed[i] = r["build"]
    now = datetime.now(timezone.utc).isoformat()
    data = {"schema_version": 1, "game": "wow-forever", "imported_at": now,
            "source": BASE + "/professions", "coverage_verified": False,
            "limitations": ["Catalogue issu du client ; disponibilité réelle en jeu non garantie.",
                           "Cooldowns non systématiquement documentés ; volumes conditionnels.",
                           "Prix PNJ complémentaires : fiches Forever du même build ; le CSV reste prioritaire."],
            "coverage": coverage, "import_errors": failures, "recipes": records, "vendor_prices": prices}
    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(args.output)

    if failures and args.output.exists():
        raise SystemExit("Import de métiers incomplet ; catalogue existant conservé. " + "; ".join(failures))
    save()  # Le catalogue est utilisable même si la collecte PNJ est interrompue.

    def lookup(item_id, build):
        html = fetch(f"{BASE}/items/{item_id}", args.cache, args.refresh)
        return parse_vendor_price(html, item_id, build)

    lookups = list(needed.items())[:max(0, args.vendor_limit)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        pending = {executor.submit(lookup, item_id, build): item_id for item_id, build in lookups}
        for index, future in enumerate(as_completed(pending), 1):
            item_id = pending[future]
            try:
                record = future.result()
                if record:
                    prices[str(item_id)] = record
            except Exception as exc:
                failures.append(f"Objet {item_id}: {exc}")
            if index % 40 == 0:
                save()
                print(f"PNJ: {index}/{len(lookups)} fiches consultées", flush=True)
    save()
    print(f"Catalogue sauvegardé : {len(records)} recettes, {len(prices)} prix PNJ complémentaires. {len(failures)} erreurs.")


if __name__ == "__main__":
    main()
