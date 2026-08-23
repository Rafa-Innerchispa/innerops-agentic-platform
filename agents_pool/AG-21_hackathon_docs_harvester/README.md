# hackathon_docs_harvester (AG-21)

Espejo local de recursos Devpost + docs del sponsor. Complementa a **AG-12 project_provisioner**.

## Ejecución (sin LLM — script determinista)

Desde la raíz del proyecto hackathon:

```bash
python3 scripts/bootstrap_hackathon_project.py
```

Requisitos en `docs/metadata.json`:

```json
{
  "hackathon_url": "https://uipath-agenthack.devpost.com/"
}
```

## Salida

- `docs/hackathon_resources/INDEX.md` — páginas descargadas
- `docs/hackathon_resources/DISCOVERED_LINKS.md` — enlaces encontrados aún no bajados
- `docs/hackathon_resources/raw/*.md` — contenido extraído
- `.cursor/rules/*.mdc` — reglas Cursor (si no existían)

## Cursor Skill global

Skill personal: `~/.cursor/skills/hackathon-project-bootstrap/SKILL.md`
