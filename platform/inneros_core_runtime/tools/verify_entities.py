#!/usr/bin/env python3
"""Verifica entidades Mongo vs ENTITIES_CANONICAL.yaml."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from raphiia_openai import mongo_store

CANON = Path(__file__).resolve().parents[3] / "ralfi-ia-platform" / "companies" / "ENTITIES_CANONICAL.yaml"

REQUIRED = {
    "ent_ralfia": "Ralfi IA",
    "ent_pcdoctor": "PC Doctor S.A.",
    "ent_innerchispa": "InnerChispa",
    "ent_innerspark": "InnerSpark",
    "ent_domotika": "Domotika",
    "ent_rafael_personal": "Rafael López",
    "ent_iskcon": "ISKCON",
    "ent_creatoros": "CreatorOS",
}

FORBIDDEN_NAMES = {"Ralphi IA", "Héctor Rafael López", "ISCOM"}


def main() -> int:
    db = mongo_store.get_db()
    errors: list[str] = []

    for eid, expected in REQUIRED.items():
        doc = db.entities.find_one({"entity_id": eid}, {"_id": 0, "name": 1})
        if not doc:
            errors.append(f"FALTA en Mongo: {eid}")
            continue
        name = doc.get("name", "")
        if name != expected:
            errors.append(f"{eid}: nombre='{name}' esperado='{expected}'")
        if name in FORBIDDEN_NAMES:
            errors.append(f"{eid}: nombre prohibido '{name}'")

    bad = list(db.entities.find({"name": {"$in": list(FORBIDDEN_NAMES)}}, {"_id": 0, "entity_id": 1, "name": 1}))
    for doc in bad:
        errors.append(f"Entidad con nombre incorrecto: {doc}")

    if CANON.exists():
        data = yaml.safe_load(CANON.read_text())
        plat = data.get("platform", {})
        if plat.get("name") != "Ralfi IA":
            errors.append(f"CANON platform.name debe ser 'Ralfi IA', es {plat.get('name')!r}")

    if errors:
        print("ERRORES entidades:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("OK — entidades canónicas verificadas (Mongo + YAML)")
    for eid in sorted(REQUIRED):
        doc = db.entities.find_one({"entity_id": eid}, {"_id": 0, "entity_id": 1, "name": 1, "slug": 1})
        print(f"  {doc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
