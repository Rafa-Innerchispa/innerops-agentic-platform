# AG-22: Collector Agent (Colector de Oportunidades)

Este agente se encarga de buscar, extraer y normalizar convocatorias públicas, hackatones y programas de aceleración o créditos de diversas fuentes (incluyendo Devpost, Lablab.ai, y portales de créditos cloud).

## Responsabilidades
- Rastrear nuevas oportunidades de forma regular.
- Normalizar los campos en el esquema unificado.
- Evitar duplicados comparando URLs y títulos.
- Guardar la información en la base de datos de MongoDB.
