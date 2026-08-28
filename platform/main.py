"""Entrypoint uvicorn — RaphiIA-OpenAI :8099."""

import uvicorn

from raphiia_openai.settings import RAPHI_IA_OPENAI_HOST, RAPHI_IA_OPENAI_PORT

if __name__ == "__main__":
    uvicorn.run("raphiia_openai.app:app", host=RAPHI_IA_OPENAI_HOST, port=RAPHI_IA_OPENAI_PORT, reload=False)
