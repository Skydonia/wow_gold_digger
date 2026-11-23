"""Audit reproductible de la copie des données, sans certifier les taux en jeu.

python -m gold_digger.audit_disenchant --upstream data/cache/disenchant/audit-upstream.lua
Le Lua est lu comme du texte, jamais exécuté. Le rapport JSON va sur stdout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .disenchant import item_profile, validate_reference


def canonical(outcomes):
    return sorted((o['item_id'], o['probability'], o['min_quantity'], o['max_quantity'])
                  for o in outcomes)


def audit(root, upstream):
    reference = json.loads((root / 'data/sources/disenchant.json').read_text())
    comparison = json.loads((root / 'data/sources/disenchant_comparison.json').read_text())
    validate_reference(reference)
    raw = upstream.read_bytes()
    lua = raw.decode()
    tables = {}
    for table, encoded in re.findall(r'\[(\d+)\] = "([\d,;.]+)"', lua):
        tables[table] = [dict(zip(('item_id', 'probability', 'min_quantity', 'max_quantity'),
                                  (int(a), float(b)/100, int(c), int(d))))
                         for a, b, c, d in (row.split(',') for row in encoded.split(';'))]
    brackets = []
    section = lua.split('FP.DisenchantBrackets = {')[1].split('-- [item id]')[0]
    class_id = None
    for line in section.splitlines():
        header = re.fullmatch(r'    \[(\d+)\] = \{', line)
        if header:
            class_id = int(header[1])
        quality = re.match(r'        \[(\d+)\] =', line)
        if quality:
            for low, high, table in re.findall(r'\{ (\d+), (\d+), (\d+) \}', line):
                brackets.append(dict(class_id=class_id, quality=int(quality[1]),
                                     min_level=int(low), max_level=int(high), table_id=int(table)))
    overrides = dict((k, int(v)) for k, v in re.findall(
        r'\[(\d+)\] = (\d+)', lua.split('FP.DisenchantOverride = {')[1].split('}')[0]))
    never = list(map(int, re.search(r'FP.DisenchantNever = ",([\d,]+),"', lua)[1].split(',')))
    key = lambda b: (b['class_id'], b['quality'], b['min_level'], b['max_level'])
    checks = {
        'source_blob': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == reference['source_blob'],
        'tables': tables == reference['tables'],
        'brackets': sorted(brackets, key=key) == sorted(reference['brackets'], key=key),
        'overrides': overrides == reference['overrides'],
        'exclusions': sorted(never) == sorted(reference['never']),
    }
    db = sqlite3.connect(f"file:{root / 'data/catalog/forever.sqlite'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    stored = {}
    for row in db.execute('SELECT * FROM disenchant_outcomes'):
        stored.setdefault(row['profile_id'], []).append(dict(row))
    checks['sqlite_outcomes'] = ({k: canonical(v) for k, v in stored.items()} ==
                                 {k: canonical(v) for k, v in reference['tables'].items()})
    associations = list(db.execute('SELECT i.*, d.profile_id, d.reason FROM items i JOIN item_disenchant d ON i.id=d.item_id'))
    checks['sqlite_associations'] = all(item_profile(r['id'], dict(r), reference) ==
                                       (r['profile_id'], r['reason']) for r in associations)
    checks['sqlite_equipment_coverage'] = len(associations) == db.execute(
        'SELECT count(*) FROM items WHERE class_id IN (2,4)').fetchone()[0]
    compared = {key(b): b for b in comparison['brackets']}
    checks['comparison_coverage'] = set(compared) == {key(b) for b in brackets}
    differences = []
    for b in reference['brackets']:
        other = compared.get(key(b))
        ours = reference['tables'][str(b['table_id'])]
        if other and canonical(ours) != canonical(other['outcomes']):
            differences.append({**b, 'local': ours, 'comparison': other['outcomes']})
    example = dict(db.execute('SELECT i.*, d.profile_id FROM items i JOIN item_disenchant d ON i.id=d.item_id WHERE i.id=15930').fetchone())
    db.close()
    return {
        'qualification': 'Conformité technique à la source uniquement ; taux Forever non certifiés.',
        'checks': checks, 'tables': len(tables), 'outcomes': sum(map(len, tables.values())),
        'brackets': len(brackets), 'overrides': len(overrides), 'exclusions': len(never),
        'associations_checked': len(associations),
        'comparison_source': comparison['source'], 'divergent_brackets': differences,
        'non_unit_probability_sums': {k: sum(o['probability'] for o in v) for k, v in tables.items()
                                      if abs(sum(o['probability'] for o in v)-1) > 1e-8},
        'wowhead_15930': {'item': example, 'local_outcomes': tables[example['profile_id']],
                          'status': 'Tableau Wowhead non vérifié. Règle locale : les objets verts tenus en main gauche utilisent la tranche armure, sans les exceptions Classic de type arme.'},
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', type=Path, required=True)
    args = parser.parse_args()
    report = audit(Path(__file__).resolve().parents[1], args.upstream)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if all(report['checks'].values()) else 1)
