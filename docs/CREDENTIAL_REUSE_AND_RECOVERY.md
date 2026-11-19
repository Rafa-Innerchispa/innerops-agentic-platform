# InnerOS credential continuity: owner-vault is canonical

## Current operational evidence (23 Oct 2026)

Owner Vault exists at Mongo collection `ralfia_owner_vault`. The
encrypted key is loaded from `OWNER_VAULT_KEY` or
`/home/rlopez/.config/ralfia/vault.key`; the local runner verified the
key-file permission as 0600. Do **not** copy or print this key.

Read-only inventory returned **58** Owner Vault entries; twelve Ruijie
entries are duplicates across the aliases `ruijie_reyee`,
`ruijie_cloud`, `reyee_cloud`, each containing the same four recoverable
values. Two GWN Cloud entries also decrypt. No categories directly
identifying Hikvision, Dahua, ZKTeco, Intelbras, UniFi or ONVIF were
found in this Vault. These may exist in other installed service stores:
that absence alone does not prove the credentials never existed.

Ruijie read-only login using existing credentials against
`cloud-la.ruijienetworks.com` returned HTTP 200 and provider code 1
(invalid app identifier); `device_fabric_inventory` still reports
`ruijie_live.login_failed` for Bellini group 9927074. Saving another
account password will not repair an invalid App ID.

## Implemented protections (isolated PR, not in production)

- If a vault key is unavailable and any owner credential already exists,
  fail closed; never silently generate a new key.
- If MongoDB cannot be checked, never assume the vault is empty.
- Initialize a brand-new empty vault using exclusive, mode-0600 key
  creation; don't overwrite an existing key during a race.
- Refuse overwriting an encrypted credential when the active key cannot
  decrypt the previous value.
- A decryption failure must report `vault_decryption_failed`, not an
  apparent successful read with an empty string.
- Ruijie uses complete canonical Vault first and only falls back to
  legacy environment variables when necessary. A metadata-only function
  reports conflicts without exposing credential values.
- Authentication errors distinguish provider code 1 and never return
  arbitrary vendor text that may echo credentials.
- A rotated Ruijie credential changes the session cache key.

## Required follow-up for **all** devices

1. Discover existing service credential locations on AMD and Intel without
   logging raw values. Label each with provider, tenant, site, asset ID,
   credential type, read/write scope and last successful authentication.
2. Import and **verify** each credential directly into Owner Vault through
   an authenticated owner-only path. Do not import placeholders or rotate
   healthy credentials. Keep one canonical reference per account/site.
3. Use `owner_vault_bridge.credential_bundle_status` and the Device Fabric
   provider's read-only login before claiming the connection works.
4. Deliver provider operations through an authenticated MCP/Capability
   Gateway with caller identity and least-privilege policies, never plaintext
   credentials in agent prompts. `actor="RAFAEL"` from untrusted callers
   is not sufficient proof of identity.
5. For Intel, explicitly verify that its runtime can recover a credential
   through the authorized broker, without installing the master key on
   arbitrary agents. Establish key recovery and restore drills.
6. Wire credential health/status monitoring and service-reload checks.
   Failures should say MISSING, KEY_UNAVAILABLE, UNDECRYPTABLE,
   PROVIDER_AUTH_FAILED, PROVIDER_APP_ID_INVALID, or PERMISSION_DENIED.
   Do not conflate credential storage with live provider authentication.
7. Validate Ruijie App ID registration/region in provider portal with
   minimal read-only authentication. Only after provider code 0, verify
   group 9927074, switch ES228GS-LP and a second authorized MCP
   consumer (Nebius). No VLAN/PoE/camera mutations.

## Tests and security

`platform/tests/test_owner_vault_ruijie_reliability.py` tests the branch
module explicitly, never the separately installed service copy.
`platform/tests/probe_owner_vault_provider_inventory_readonly.py` is
opt-in and prints presence/recoverability metadata only.

No claim of production rollout is made by a passing branch test.
Protected main approval and actual hash/service verification remain gates.
