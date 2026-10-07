"""Contifico multi-entity registry (PC Doctor + Domotika/InnerChispa)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from inneros_core_runtime.settings import CONTIFICO_API_KEY


@dataclass(frozen=True)
class ContificoEntity:
    entity_id: str
    label: str
    ruc: str
    legal_name: str
    trade_name: str
    api_key_env: str
    pos_token_env: str
    aliases: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "label": self.label,
            "ruc": self.ruc,
            "legal_name": self.legal_name,
            "trade_name": self.trade_name,
            "aliases": list(self.aliases),
        }


PCDOCTOR = ContificoEntity(
    entity_id="pcdoctor",
    label="PC Doctor S.A.",
    ruc="0992418575001",
    legal_name="PC DOCTOR S.A",
    trade_name="PC Doctor",
    api_key_env="CONTIFICO_PCDOCTOR_API_KEY",
    pos_token_env="CONTIFICO_PCDOCTOR_POS_TOKEN",
)

DOMOTIKA = ContificoEntity(
    entity_id="domotika",
    label="RUP personal — Domotika (InnerChispa soon)",
    ruc="0914832423001",
    legal_name="Hector Rafael Lopez Gutierrez",
    trade_name="Domotika",
    api_key_env="CONTIFICO_DOMOTIKA_API_KEY",
    pos_token_env="CONTIFICO_DOMOTIKA_POS_TOKEN",
    aliases=("innerchispa",),
)

_BY_ID: dict[str, ContificoEntity] = {
    PCDOCTOR.entity_id: PCDOCTOR,
    DOMOTIKA.entity_id: DOMOTIKA,
}
for _ent in (PCDOCTOR, DOMOTIKA):
    for _alias in _ent.aliases:
        _BY_ID[_alias] = _ent

DEFAULT_ENTITY_ID = os.getenv("CONTIFICO_DEFAULT_ENTITY", PCDOCTOR.entity_id).strip().lower() or PCDOCTOR.entity_id


def list_entities() -> list[ContificoEntity]:
    return [PCDOCTOR, DOMOTIKA]


def resolve_entity(entity_id: str | None = None) -> ContificoEntity:
    raw = (entity_id or DEFAULT_ENTITY_ID or PCDOCTOR.entity_id).strip().lower()
    ent = _BY_ID.get(raw)
    if not ent:
        known = sorted({e.entity_id for e in list_entities()} | set(DOMOTIKA.aliases))
        raise ValueError(f"unknown_contifico_entity:{raw}; known={known}")
    return ent


def entity_api_key(entity: ContificoEntity) -> str:
    explicit = (os.getenv(entity.api_key_env) or "").strip()
    if explicit:
        return explicit
    if entity.entity_id == PCDOCTOR.entity_id:
        return (CONTIFICO_API_KEY or "").strip()
    return ""


def entity_pos_token(entity: ContificoEntity) -> str:
    return (os.getenv(entity.pos_token_env) or os.getenv("CONTIFICO_POS_TOKEN") or "").strip()


def entities_registry_public() -> dict[str, Any]:
    return {
        "default_entity_id": DEFAULT_ENTITY_ID,
        "entities": [e.public_dict() for e in list_entities()],
        "env_keys": {
            PCDOCTOR.entity_id: {
                "api_key": PCDOCTOR.api_key_env,
                "legacy_fallback": "CONTIFICO_API_KEY",
                "pos_token": PCDOCTOR.pos_token_env,
            },
            DOMOTIKA.entity_id: {
                "api_key": DOMOTIKA.api_key_env,
                "pos_token": DOMOTIKA.pos_token_env,
                "aliases": list(DOMOTIKA.aliases),
            },
        },
    }
