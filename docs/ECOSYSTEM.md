# Ecosistema `/home/rlopez/projects/`

Documentación relacionada (fuera del repo):

- `~/data/ai_coordination/PROJECTS_REGISTRY.md` — registro de repos y puertos
- `~/data/ai_coordination/HUB/ECOSYSTEM_STRUCTURE_V1.md` — estructura objetivo v1

## Repositorio canónico de plataforma

| Repo GitHub | Ruta local | Rol |
|-------------|------------|-----|
| [ralfi-ia-platform](https://github.com/Rafa-Innerchispa/ralfi-ia-platform) | `ralfi-ia-platform/` | Kernel multi-empresa, `ENTITIES_CANONICAL.yaml`, nomenclatura |

### Clonar en un nodo nuevo

Requiere acceso al repo privado (misma cuenta GitHub / deploy key).

```bash
mkdir -p /home/rlopez/projects
cd /home/rlopez/projects
git clone https://github.com/Rafa-Innerchispa/ralfi-ia-platform.git
```

### Sincronizar en un nodo ya configurado

Idempotente (clone si no existe, `git pull` si ya hay `.git`):

```bash
if [ -d ~/projects/ralfi-ia-platform/.git ]; then
  cd ~/projects/ralfi-ia-platform && git pull
else
  cd ~/projects && git clone https://github.com/Rafa-Innerchispa/ralfi-ia-platform.git
fi
```

Ejemplo remoto (nodo Intel `192.168.1.4`):

```bash
ssh rlopez@192.168.1.4 'if [ -d ~/projects/ralfi-ia-platform/.git ]; then cd ~/projects/ralfi-ia-platform && git pull; else cd ~/projects && git clone https://github.com/Rafa-Innerchispa/ralfi-ia-platform.git; fi'
```

## Registro ecosistema

Actualizar también `~/data/ai_coordination/PROJECTS_REGISTRY.md` al añadir módulos o repos satélite.

## Legacy (sin mover)

| Ruta | Notas |
|------|--------|
| `raphiia-openai/` | legacy, migración → ralfi-ia-platform · código Python operativo actual |

Actualizado: 2026-08-05
