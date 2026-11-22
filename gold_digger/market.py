import csv
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from .models import MarketItem, Tier


@dataclass
class ImportReport:
    items: dict[int, MarketItem] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rows: int = 0


def copper(value: str) -> int:
    try:
        number = Decimal(value.strip()) * 10000
    except InvalidOperation as exc:
        raise ValueError("prix invalide") from exc
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        raise ValueError("prix négatif, non fini ou inférieur à la précision d'un cuivre")
    return int(number)


def money(value: int | None) -> str:
    if value is None:
        return "—"
    sign = "−" if value < 0 else ""
    gold, rest = divmod(abs(value), 10000)
    silver, bronze = divmod(rest, 100)
    return f"{sign}{gold:,} po {silver:02d} pa {bronze:02d} pc".replace(",", " ")


def parse_market(content: bytes) -> ImportReport:
    report = ImportReport()
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")), delimiter=";")
        required = {"id", "name", "npc", "first", "quantity", "min"}
        if not required.issubset(reader.fieldnames or []):
            report.errors.append("Colonnes manquantes : " + ", ".join(sorted(required - set(reader.fieldnames or []))))
            return report
        seen = set()
        for line, row in enumerate(reader, 2):
            report.rows += 1
            try:
                if None in row or any(row.get(k) is None for k in required):
                    raise ValueError("nombre de colonnes incorrect")
                item_id = int(row["id"])
                if item_id <= 0 or not row["name"].strip():
                    raise ValueError("identifiant ou nom invalide")
                if item_id in seen:
                    raise ValueError(f"identifiant dupliqué : {item_id}")
                seen.add(item_id)
                total = int(row["quantity"])
                if total < 0:
                    raise ValueError("quantité négative")
                npc = copper(row["npc"]) if row["npc"].strip() else None
                tiers = {}
                for token in row["first"].split():
                    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)x([0-9]+)", token)
                    if not match:
                        raise ValueError(f"palier invalide : {token}")
                    price, count = copper(match[1]), int(match[2])
                    if price <= 0 or count <= 0:
                        raise ValueError("prix et quantité des paliers doivent être positifs")
                    tiers[price] = tiers.get(price, 0) + count
                if sum(tiers.values()) > total:
                    raise ValueError("quantités des paliers supérieures au stock total")
                minimum = copper(row["min"])
                if tiers and minimum != min(tiers):
                    report.warnings.append(f"Ligne {line} : min différent du premier palier ; seuls les paliers sont utilisés.")
                report.items[item_id] = MarketItem(item_id, row["name"].strip(), npc,
                    tuple(Tier(p, q) for p, q in sorted(tiers.items())), total, (row.get("type") or "").strip())
            except (ValueError, TypeError) as exc:
                report.errors.append(f"Ligne {line} : {exc}")
                # Un doublon rend l'identifiant entier ambigu.
                if "identifiant dupliqué" in str(exc):
                    report.items.pop(item_id, None)
    except (UnicodeDecodeError, csv.Error) as exc:
        report.errors.append(f"CSV UTF-8 illisible : {exc}")
    return report
