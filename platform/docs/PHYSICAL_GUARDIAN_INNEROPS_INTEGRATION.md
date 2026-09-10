# Physical Guardian in InnerOS / InnerOps

## Canonical product map

```text
InnerOS
  -> ARIA / identity / policy / routing / tools / evidence
  -> InnerOps
       -> Workforce
       -> Physical Guardian
       -> QuoteOps
       -> future business modules
```

Physical Guardian is a permanent InnerOps product module implemented in:

`Rafa-Innerchispa/inneros-physical-guardian`

The AI Infra Summit repository is a hackathon composition and must not become the commercial source of truth.

## One product, multiple tenants

PC Doctor Lab and Torres Bellini are not separate copies of Guardian. They are independent tenant/site contexts using the same product service.

```text
Tenant: pcdoctor
  Site: pcdoctor-lab
    Recorder family: DH-XVR5208AN-4KL-X

Tenant: bellini
  Site: bellini-t1
    Recorder model: DH-XVR5232AN-I3
  Site: bellini-t2
    Recorder model: DHI-XVR5232AN-S2
```

Only sanitized model identifiers belong in shared configuration. Camera IPs, recorder credentials, serial numbers, private topology and customer footage stay outside this registry in approved site-local secret/config storage.

## Identity and isolation

The portal must resolve tenant identity from an authenticated server-side principal. A query string, browser form field, camera attribute or model output cannot select a customer.

Normal customer session:

```text
authenticated principal
  -> canonical tenant_id
  -> allowed site_ids
  -> enabled InnerOps modules
  -> module launch context
  -> Physical Guardian tenant/site enforcement
```

Internal support may need to operate multiple customers. That is an InnerOS platform capability above Guardian RBAC and requires an explicit `platform_support` role plus an allowlist of tenants. It is not a global bypass inside Physical Guardian.

## Storage and compute

The intended commercial model remains one logical storage namespace/database per customer while compute may be shared:

```text
PC Doctor DB/namespace ----\
                           +--> shared Guardian service / AMD compute fabric
Bellini DB/namespace ------/
```

Shared compute never means shared identity, policy, evidence or storage.

## Bellini edge profile

Bellini phase 1 uses the existing permanent Guardian hybrid-edge design. The preferred first mode is `tunnel-only`: Bellini initiates outbound encrypted connectivity and central Guardian performs decode/inference. The existing recording/VMS path remains independent.

The two known Bellini recorder models are now recorded in the sanitized tenant profile. Capacity, substream profile, recorder session limits and real WAN/latency still need to be measured during the pilot rather than assumed.

## PC Doctor lab profile

PC Doctor Lab is the integration test tenant. It is where live Dahua event/RTSP/detector/Guardian tests can be exercised before Bellini expansion. It must use the same contracts as customer deployments, not a privileged single-tenant shortcut.

## Portal integration contract

`inneros_core_runtime.product_modules` provides the first stable contract for the InnerOS portal:

- module registry;
- tenant/site profiles;
- enabled modules per tenant;
- server-derived module launch context;
- site restrictions;
- explicit support-operator cross-tenant allowlist;
- sanitized portal catalog.

The production Panel de Control can consume this contract to render Physical Guardian beside the rest of InnerOps. Deployment of the portal change is deliberately separated from this contract so it can be tested before touching the active service.

## Test order

1. Contract isolation tests in `platform/tests/test_product_modules.py`.
2. PC Doctor Lab live Guardian test against the known lab recorder.
3. Portal preview showing the correct tenant/module catalog.
4. Bellini tunnel-only connectivity test with no central video consumers.
5. Bellini 4-camera pilot and resource measurements.
6. Expand to 8, 16/32 and eventually both towers only if measured gates pass.
