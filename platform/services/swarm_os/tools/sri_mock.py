"""Consulta RUC — mock local. Reemplazar por API SRI cuando esté lista."""

MOCK_SRI = {
    "0991386866001": {
        "ruc": "0991386866001",
        "name": "ASOCIACION DE PROPIETARIOS URB. PARQUES DEL RIO (ASOPAR)",
        "address": "Av. Samborondón 608 y Abelardo García, Samborondón",
        "city": "Samborondón",
        "status": "ACTIVO",
    },
    "1790012345001": {
        "ruc": "1790012345001",
        "name": "URBANIZACION CIUDADELA EJEMPLO CIA. LTDA.",
        "address": "Guayaquil",
        "city": "Guayaquil",
        "status": "ACTIVO",
    },
}


def lookup_ruc(ruc: str) -> dict:
    clean = "".join(c for c in ruc if c.isdigit())
    if clean in MOCK_SRI:
        return {**MOCK_SRI[clean], "source": "sri_mock"}
    return {
        "ruc": clean,
        "name": f"CLIENTE RUC {clean}",
        "address": "",
        "city": "",
        "status": "PENDIENTE_VERIFICACION",
        "source": "sri_mock_fallback",
    }
