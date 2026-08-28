# Acceso de red — Windows vs servidor Ralphi

**Servidor:** `ralphi-ia-ver-10` — IP **`192.168.1.4`**  
**Tu PC:** Windows (sin MongoDB, sin Ollama local para este proyecto)

---

## Regla simple

| Desde dónde | Qué URL usar |
|-------------|--------------|
| **Tu Windows** (navegador, curl, Postman) | `http://192.168.1.4:PUERTO` |
| **Dentro del servidor** (scripts Python, `.env`) | `http://127.0.0.1:PUERTO` |

MongoDB **no está en tu Windows**. Está en **192.168.1.4:27017**, pero solo accesible desde la red local (o túnel SSH). La app Swarm-OS en el servidor se conecta con `127.0.0.1:27017` porque Mongo corre **en la misma máquina**.

---

## Puertos (todos en 192.168.1.4)

| Servicio | Puerto | Desde Windows |
|----------|--------|---------------|
| **Swarm-OS API** | 8100 | `http://192.168.1.4:8100/status` |
| MongoDB | 27017 | Compass: `192.168.1.4:27017` (si firewall permite) |
| Ollama | 11434 | Solo uso interno del servidor |
| Whisper | 9001 | Solo uso interno del servidor |
| n8n | 5678 | `http://192.168.1.4:5678` |

---

## ¿Dónde se creó la base de datos?

**En el servidor 192.168.1.4**, base `pcdoctor_swarm`, **62 colecciones**.

Se creó ejecutando en el servidor:

```bash
cd /home/rlopez/projects/innerspark-swarm-os-cursor-local
source venv/bin/activate
python scripts/init_mongodb_schema.py
```

Comprobar desde Windows:

```bash
curl http://192.168.1.4:8100/status
```

---

## Por qué `.env` dice 127.0.0.1

El archivo `.env` vive **en el servidor** y lo lee Python **en el servidor**:

```
MONGO_URI=mongodb://127.0.0.1:27017/    ← correcto EN EL SERVIDOR
OLLAMA_BASE_URL=http://127.0.0.1:11434  ← correcto EN EL SERVIDOR
```

`127.0.0.1` en el servidor = la propia máquina 192.168.1.4. **No cambiar a 192.168.1.4 en .env** salvo que Mongo estuviera en otra máquina (no es el caso).

---

## Cursor en Windows conectado por SSH

Si editas código por SSH en `192.168.1.4`:

- Los scripts que ejecutes **en la terminal remota** usan `127.0.0.1` → Mongo del servidor ✓
- Si abres un navegador **en Windows**, usa `192.168.1.4` ✓

---

## MongoDB Compass desde Windows

Conexión:

```
mongodb://192.168.1.4:27017/pcdoctor_swarm
```

Si no conecta, el firewall del servidor puede bloquear 27017 desde la LAN. Alternativa: túnel SSH:

```bash
ssh -L 27017:127.0.0.1:27017 rlopez@192.168.1.4
```

Luego en Compass: `mongodb://127.0.0.1:27017/pcdoctor_swarm` (el túnel redirige al servidor).
