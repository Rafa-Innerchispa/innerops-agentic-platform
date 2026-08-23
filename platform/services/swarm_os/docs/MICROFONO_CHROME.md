# Micrófono en Chrome — Ralphi IA v2.0

Chrome bloquea el micrófono en `http://192.168.1.4` porque no es HTTPS. Hay **dos formas** de habilitarlo (la que usaste antes):

## Opción A — Flag de Chrome (recomendada en red local)

1. En Chrome abre: `chrome://flags/#unsafely-treat-insecure-origin-as-secure`
2. En el cuadro de texto pega **exactamente**:
   ```
   http://192.168.1.4:5173,http://192.168.1.4:8800,http://192.168.1.4:8100
   ```
3. Cambia a **Enabled**
4. Pulsa **Relaunch** (reiniciar Chrome)
5. Abre de nuevo: http://192.168.1.4:5173/datacenter
6. Al pulsar **Micrófono**, acepta el permiso

## Opción B — Permiso por sitio

1. `chrome://settings/content/microphone`
2. En **Permitir** agrega: `[*.]192.168.1.4:5173`
3. Recarga la página del Centro de Datos

## Si sigue sin funcionar

- Cierra pestañas duplicadas del admin
- Prueba ventana de incógnito **después** del flag (a veces incógnito ignora flags)
- El candado junto a la URL → Permisos del sitio → Micrófono → Permitir

## Alternativa sin Chrome

- Botón **Subir audio** (siempre funciona)
- Futuro: HTTPS con certificado en el servidor (solución definitiva)
