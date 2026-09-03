# AG-57 DMX Stage Orchestrator

**Numeración:** AG-57 · **ID:** `AG-57_dmx_artnet_orchestrator`
**Dominio:** `home` / `stage`
**Local-First:** Sí (Inferencia y control local 100%)

Orquestador de iluminación escénica profesional DMX512 y Art-Net sobre red local para el nodo **Pknight CR011R** (`192.168.1.10:6454`, Universo 0), coordinando efectos dinámicos, generadores sinusoidales, persecuciones de color y sincronización con Home Assistant.

---

## Mapeo de Hardware

* **Nodo Art-Net:** Pknight CR011R (IP `192.168.1.10:6454`, Universo 0)
* **Pulpo 1 (Eurolite EL-LMH1240WB):** CH 1-19 (Pan/Tilt 540°/Infinite, 2 Barras LED RGBW)
* **Beam 01 (Mini Beam RGBW 12W):** CH 20-25
* **Tacho Escalera (PAR 18x1W RGB):** CH 26-32 (Modo d)
* **Tacho Peces (PAR 18x1W RGB):** CH 33-39 (Modo d)
* **Tacho Central (PAR RGBW + SMD Flash):** CH 40-47 (Modo A)
* **Tacho Plantas (PAR 18x1W RGB):** CH 48-54 (Modo d)
* **Bola Disco (Crystal Magic Ball):** CH 55-62 (Modo A)
* **Beam 02 (Mini Beam RGBW 12W):** CH 63-68
* **Pulpo 2 (Eurolite EL-LMH1240WB):** CH 69-87

---

## Modos Procedurales Disponibles

1. `rainbow`: Barrido espectral continuo y desfasado con movimiento suave.
2. `frenzy`: Modo discoteca de alta velocidad (8-10 Hz) con rotación continua infinita.
3. `police`: Alerta y destello alternado azul/rojo.
4. `fire`: Parpadeo orgánico cálido ámbar/fuego.
5. `chill_lounge`: Iluminación respirable suave y envolvente.
6. `morado_uv`: Luz negra fluorescente (R:45, G:0, B:255).
7. `blackout`: Apagado inmediato de seguridad.

---

## Repositorio y Módulos

* **Código Fuente:** `/home/rlopez/projects/inneros-dmx-engine`
* **GitHub:** [https://github.com/Rafa-Innerchispa/inneros-dmx-engine](https://github.com/Rafa-Innerchispa/inneros-dmx-engine)
* **API REST Local:** `http://0.0.0.0:8096`
