# Cómo no perder RALF IA v2.0

**Tres capas** (no dependas de una sola):

| Capa | Qué guarda | Esfuerzo |
|------|------------|----------|
| **1. GitHub** | Código, docs, portal, scripts | Automático tras cada push |
| **2. Backup diario** | MongoDB + .env + código + Docker compose → Google Drive | Automático 1:30 AM |
| **3. Notion** | Memoria humana, decisiones, mapa del negocio | Copiar `docs/NOTION_EXPORT_RALPHI_V2.md` |

---

## Un comando para restaurar

```bash
restaura-a-ralphia
```

Desde máquina nueva sin backup local:

```bash
BACKUP_FROM_CLOUD=1 restaura-a-ralphia
```

Con archivo concreto:

```bash
restaura-a-ralphia /home/rlopez/backups/disaster_recovery/disaster_recovery_YYYYMMDD_HHMMSS.tar.gz
```

Hace: extrae código → Docker → MongoDB → venv → npm → systemd.

---

## Respaldo manual ahora

```bash
/home/rlopez/projects/backup_disaster_recovery.sh
```

Sube a: `Ralphi-IA-Gdrive:RalphiIA_Backups/disaster_recovery/`

---

## GitHub (código fuente)

Repo: `rafagye/innerspark-swarm-os-cursor-local` (privado)

```bash
cd /home/rlopez/projects/innerspark-swarm-os-cursor-local
git pull
```

**Nunca** subas `.env` ni tokens — ya están en `.gitignore`.

---

## Qué NO se pierde si sigues esto

- Portal `:8800`, admin `:5173`, API `:8100`, FileBrowser `:8081`
- Multiempresa PC Doctor + InnerChispa
- Catálogo MongoDB (clientes, inventario, servicios IA)
- Logos en `assets/branding/`
- Scripts systemd

---

## Si el servidor muere

1. Ubuntu + Docker en máquina nueva
2. `rclone` configurado con `Ralphi-IA-Gdrive` (o copia manual del `.tar.gz`)
3. `restaura-a-ralphia`
4. Abrir `http://IP:8800`

---

## Notion

Cursor no tiene Notion conectado en este entorno para escribir solo. Usa el archivo **`docs/NOTION_EXPORT_RALPHI_V2.md`**: Import → Markdown en Notion, o pégalo en una página del OS Central.
