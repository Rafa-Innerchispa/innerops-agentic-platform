"""Errores hackathon — configuración e integraciones reales."""


class HackathonConfigError(Exception):
    """Falta configuración obligatoria en .env."""

    def __init__(self, missing: list[str], hint: str = ""):
        self.missing = missing
        self.hint = hint
        msg = "Configuración hackathon incompleta. Variables faltantes: " + ", ".join(missing)
        if hint:
            msg += f"\n{hint}"
        super().__init__(msg)


class HackathonIntegrationError(Exception):
    """Fallo en API externa (Band, Featherless, AIML)."""

    def __init__(self, service: str, detail: str):
        self.service = service
        self.detail = detail
        super().__init__(f"[{service}] {detail}")
