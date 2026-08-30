# Peer Wi-Fi credentials (local only)

JSON files in this directory are written at runtime by `peer_secret_store_wifi` and
similar tools. They contain SSID/password pairs for managed nodes.

- Pattern: `wifi_<node>_<hash>.json`
- **Never commit** real JSON payloads — root `.gitignore` blocks `*.json` here.
- Restore from the owner vault or re-pair Wi-Fi if a node is reprovisioned.
