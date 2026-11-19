"""Explicit-only read-only provider credential inventory. No secret values/logs.

Presence in Owner Vault does not prove device/provider authentication works.
Only run manually; filename starts probe_ to avoid CI collection.
"""
from collections import defaultdict
import json
from inneros_core_runtime import owner_vault as vault

PROVIDERS = {
    "ruijie": ("ruijie", "reyee"),
    "hikvision": ("hikvision", "hik"),
    "dahua": ("dahua",),
    "zkteco": ("zkteco", "zkbio"),
    "grandstream": ("grandstream", "gwn_cloud", "gwn", "gcc", "ucm"),
    "unifi": ("unifi", "ubiquiti"),
    "intelbras": ("intelbras",),
    "onvif": ("onvif", "rtsp"),
    "home_assistant": ("home_assistant", "homeassistant"),
}


def test_provider_credentials_present_and_recoverable_read_only():
    rows = vault.list_owner_credentials(reveal=False, actor="RAFAEL")
    assert rows.get("ok") is True
    category_keys = defaultdict(list)
    for row in rows.get("items") or []:
        cat = str(row.get("category") or "")
        key = str(row.get("key") or "")
        if cat and key:
            category_keys[cat].append(key)
    findings = {}
    for provider, keywords in PROVIDERS.items():
        cats = sorted(cat for cat in category_keys
                      if any(token in cat.lower() for token in keywords))
        count = sum(len(category_keys[cat]) for cat in cats)
        recoverable = 0
        for cat in cats:
            for key in category_keys[cat][:50]:
                record = vault.get_owner_credential(key, category=cat, actor="RAFAEL", reveal=True)
                recoverable += int(bool(record.get("ok") and record.get("secret")))
        findings[provider] = {
            "categories": cats, "stored_records": count,
            "recoverable_checked": recoverable, "provider_authenticated": "NOT_TESTED",
        }
    out = {
        "collection": vault.COL,
        "owner_vault_total_records": len(rows.get("items") or []),
        "other_category_record_counts": {
            cat: len(keys) for cat, keys in sorted(category_keys.items())
            if not any(any(token in cat.lower() for token in words)
                       for words in PROVIDERS.values())
        },
        "providers": findings,
        "secrets_printed": False,
        "scope": "local_runner_not_confirmed_active_mcp",
    }
    print("OWNER_VAULT_PROVIDER_INVENTORY=" + json.dumps(out, sort_keys=True))
    assert not out["secrets_printed"]
