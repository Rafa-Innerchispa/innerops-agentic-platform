"""RaphiIA-OpenAI — puente ChatGPT ↔ RalfyIA ↔ MongoDB editorial."""

# Stable submodule attributes for legacy imports and test patch paths.
try:  # pragma: no cover - import availability is exercised by integration tests
    from . import module_contract as module_contract
except Exception:
    module_contract = None  # type: ignore[assignment]
