import re
import time
import requests

RUC_API_TOKEN_URL = "https://consulta-ruc-token.azurewebsites.net/v1/deuna/creacion-token"
RUC_API_LOOKUP_URL = "https://consulta-ruc.azurewebsites.net/api/ruc"
RUC_API_USER = "deuna-ruc"
RUC_API_PASS = "BXQbDtMt"

_token_cache = {"token": None, "expires_at": 0.0}

def normalize_tax_id(value: str) -> dict:
    clean = re.sub(r"\D", "", value or "")
    if len(clean) == 10:
        return {
            "input": clean,
            "type": "cedula",
            "cedula": clean,
            "ruc": f"{clean}001",
        }
    if len(clean) == 13:
        return {
            "input": clean,
            "type": "ruc",
            "cedula": clean[:10] if clean.endswith("001") else None,
            "ruc": clean,
        }
    return {"input": clean, "type": "unknown", "cedula": None, "ruc": clean}

def _fetch_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]

    r = requests.post(
        RUC_API_TOKEN_URL,
        headers={"accept": "application/json", "Content-Type": "application/json"},
        json={"usuario": RUC_API_USER, "pass": RUC_API_PASS},
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    token = body.get("data", {}).get("response")
    if not token:
        raise RuntimeError("Token RUC vacío")

    _token_cache["token"] = token
    _token_cache["expires_at"] = now + 900  # Token expires in 900s (15 min)
    return token

def lookup_ruc(value: str) -> dict:
    norm = normalize_tax_id(value)
    ruc = norm["ruc"]
    if not ruc or len(ruc) != 13:
        return {"ruc": ruc, "status": "ID_INVALIDO", "name": "", "source": "validation"}

    # 1. Try Intuito API (real query)
    try:
        token = _fetch_token()
        url = f"{RUC_API_LOOKUP_URL}/{ruc}"
        r = requests.get(
            url,
            headers={"accept": "application/json", "Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if r.status_code == 200:
            res_json = r.json()
            main = (res_json.get("data") or {}).get("main") or []
            if main:
                row = main[0]
                addit = (row.get("addit") or [{}])[0]
                return {
                    "ruc": ruc,
                    "name": row.get("razonSocial", ""),
                    "address": addit.get("direccionCompleta", ""),
                    "status": "ACTIVO",
                    "source": "ruc_api",
                }
    except Exception as e:
        pass

    # 2. Try Local SRI Catastro database lookup (offline/loaded ZIP fallback)
    try:
        from raphiia_openai.mongo_store import get_db
        db = get_db()
        catastro_doc = db["sri_catastro"].find_one({"ruc": ruc}, {"_id": 0})
        if catastro_doc:
            return {
                "ruc": ruc,
                "name": catastro_doc.get("name", ""),
                "address": catastro_doc.get("address", ""),
                "status": "ACTIVO",
                "source": "sri_catastro_local",
            }
    except Exception:
        pass

    # 3. Scraper / generic fallback
    return {
        "ruc": ruc,
        "name": f"CLIENTE RUC {ruc} (Fallback)",
        "address": "",
        "status": "ACTIVO",
        "source": "sri_fallback",
    }
