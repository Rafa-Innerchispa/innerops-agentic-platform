# Cursor — conexión Remote SSH a Ralphi IA

Guía para que Cursor (y los agentes) trabajen **directamente en el servidor**, sin depender de SSH desde Windows en cada turno.

---

## Por qué fallaba antes

- Workspace en **Windows** (`C:\Users\...`) con rutas Linux en el prompt → archivos no encontrados.
- El agente intentaba `ssh rlopez@192.168.1.4` en cada operación → lento, bloqueos, CRLF.
- MongoDB y MCP corren en **127.0.0.1 del servidor**, no en tu PC.

**Solución:** abrir el proyecto **dentro** del servidor vía Remote SSH.

---

## Configuración SSH (Windows → 192.168.1.4)

Archivo `C:\Users\TU_USUARIO\.ssh\config`:

```
Host ralphi-ia
    HostName 192.168.1.4
    User rlopez
    IdentityFile ~/.ssh/id_rsa
```

Probar en PowerShell:

```powershell
ssh ralphi-ia "hostname && ls /home/rlopez/projects/raphiia-openai"
```

---

## Abrir proyecto en Cursor

1. `Ctrl+Shift+P` → **Remote-SSH: Connect to Host** → `ralphi-ia` (o `rlopez@192.168.1.4`).
2. Cuando cargue la ventana remota: **Open Folder** → `/home/rlopez/projects/raphiia-openai`.
3. Confirmar barra inferior: **`SSH: 192.168.1.4`**.

### Prompt para chat nuevo (copiar)

```
Workspace: /home/rlopez/projects/raphiia-openai (SSH 192.168.1.4)
Lee docs/CONEXION.md, docs/HANDOFF.md y docs/MCP_CHATGPT.md.
Trabaja SOLO en el servidor — no uses SSH desde Windows.
```

---

## Terminal integrada (servidor)

Todo comando debe ejecutarse **en la terminal remota**:

```bash
cd /home/rlopez/projects/raphiia-openai
source venv/bin/activate
./run_mcp.sh
```

Si `hostname` devuelve `ralphi-ia-ver-10` (o similar), estás en el lugar correcto.

---

## FileBrowser (opcional)

Subir archivos sin SCP: http://192.168.1.4:8081  
Ruta destino: `/home/rlopez/projects/raphiia-openai/`

---

## Checklist agente / chat nuevo

- [ ] Barra inferior dice `SSH: 192.168.1.4`
- [ ] `pwd` = `/home/rlopez/projects/raphiia-openai`
- [ ] `docs/CONEXION.md` leído
- [ ] `.env` existe con `MCP_API_KEY`
- [ ] `./run_mcp.sh` responde en `:8102`
- [ ] No se usa `OPENAI_API_KEY` en `.env`
