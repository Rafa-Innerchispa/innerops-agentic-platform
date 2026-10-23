# Proyecto: InnerOS Incident Room

**Objetivo:** competir en **Best Business Workflow** demostrando que una persona y agentes de IA pueden resolver juntos un incidente operativo **dentro de una sala de Switch conectada a un chat de equipo**.

## Problema real

En edificios, empresas y operaciones de campo, una alerta salta entre chats, herramientas de monitoreo y técnicos. Nadie sabe quién está actuando, quién autorizó cambios ni si el incidente quedó resuelto. Una IA que solo responde preguntas no cambia esa situación.

## Propuesta

Switch ofrece la sala colaborativa. RalphiIA/InnerOS aporta razonamiento, memoria, herramientas locales y coordinación. FieldOps aporta el patrón de aprobación, ejecución limitada, verificación y comprobante. Nuestra demostración se basa en un caso **inventado e inspirado en una incidencia típica de CCTV**. Bellini figura como contexto histórico de la experiencia operativa, **no** como afirmación de conectividad real o autorización del cliente.

## Aporte diferenciador

- Aprobación humana visible en el mismo hilo donde el agente propuso la acción.
- Cierre verificable: una confirmación de comando no es éxito; hay lectura posterior independiente.
- Separación explícita: dato real / dato real capturado / dato sintético.
- Reutiliza el sistema local de InnerOS; evita gastos de APIs y despliegues innecesarios.
- Separa Switch (colaboración) de InnerOS (políticas, estado, herramientas y modelos).

## Estado comprobado al 22 de octubre de 2026

- Repositorios InnerOS y FieldOps identificados en GitHub.
- Biblioteca Python sintética offline implementada y probada.
- La integración real con Switch **NO** está hecha.
- El flujo concursante **NO** está hecho; debe crearse durante el evento.
- Registro del participante y envío final son actos humanos requeridos por las reglas.

## Entrega propuesta

Repositorio público mínimo reproducible; README y documentación clara; video de 2 a 3 minutos con la sala de Switch y colaboración visible; evidencia de prueba de autorización denegada y concedida; y tabla de componentes reutilizados frente a componentes desarrollados durante el evento.
