# Flip the Switch 2026 — verificación de preparación (2 noviembre 2026)

**Estado de esta revisión:** documentos y motor sintético reutilizable disponibles; **NO** existe evidencia de una integración Switch end-to-end, de un despliegue Switch/Mattermost, de un video ni de entrega. Este archivo no representa código desarrollado durante el evento.

## Evidencia observada

1. Repo canónico: `Rafa-Innerchispa/innerops-agentic-platform`, rama `prep/flip-the-switch-2026`, carpeta `hackathons/flip-the-switch-2026`. El repositorio independiente `Rafa-Innerchispa/inneros-incident-room-switch-2026` **no aparece** en la búsqueda de repositorios instalados en GitHub al 2 de noviembre.
2. Documentación de arquitectura, estrategia, guion, prueba local y código Python reutilizable existentes en la rama. Última comprobación reportada previamente: 24 pruebas offline satisfactorias. **No se han reejecutado hoy** ni existen evidencias de CI de un repositorio separado.
3. Issue #213 (repositorio) sigue abierto; #214 (host), #215 (Switch), #216 (aprobación), #217 (demo/entrega) también. Tarea interna `ops_c031b56ae0ec` permanece `failed` según estado de InnerOS, consultado el 2 de noviembre; no volver a enviarla sin corregir el flujo de provisión.
4. Correo original de WeMakeDevs contiene confirmación de cupo. El registro adicional en Luma (2 noviembre) incluye una advertencia: **Luma por sí sola no inscribe en el concurso**. Confirmar manualmente cuenta e identidad legales en web principal, y guardar recibo en ámbito privado; nunca publicar nombres/correos de participantes en este repo.

## Hitos oficiales, zona Ecuador UTC-5

- **2 nov, 10:30**: kickoff livestream (15:30 GMT/UK en horario de invierno).
- **3 nov, 13:31**: inicio del período de desarrollo (4 nov 00:01 IST).
- **7 nov, 13:29**: cierre de presentaciones (7 nov 23:59 IST).
- La invitación de Luma muestra un horario inicial distinto al inicio de desarrollo publicado: usar el calendario oficial de WeMakeDevs para construir y entregar.

Agenda: https://www.wemakedevs.org/hackathons/switch/schedule
Reglas: https://www.wemakedevs.org/hackathons/switch/rules
Recursos: https://www.wemakedevs.org/hackathons/switch/resources

## Orden operativo que maximiza la posibilidad de entregar

### PRE-EVENTO
1. Verificar registro en el portal principal y que la identidad usada sea legalmente correcta; esto solo puede hacerlo el participante.
2. Crear repo privado separado si existen permisos apropiados (conector GitHub disponible no expone `create_repository`); no hacer push al `main` del proyecto principal.
3. Preparar equipo aislado y Docker para Switch Console/Mattermost; no modificar el UniFi ni los servicios productivos. Verificar compatibilidad, RAM, disco y puertos antes de instalar.
4. Mantener el código genérico de simulación anterior como `PRE-EXISTING`; documentar la separación.

### DESDE EL INICIO OFICIAL DEL HACKATÓN
1. Instalación de Switch que realmente funcione y respuesta de un agente en la sala Mattermost a un operador humano.
2. Adaptador del agente personalizado para Switch (protocolo según documentación vigente de la versión instalada), primero un agente, después dos.
3. Flujo de incidente sintético con dos fuentes de datos, decisión humana autenticada en la sala, bloqueo por denegación, acción simulada permitida y verificación independiente con recibo en sala.
4. Prueba integral repetible, tratamiento de duplicados, actor no autorizado, reconexión y falla de readback.
5. Auditoría de secretos y licencias, repositorio público separado, README, video de 2–3 minutos con ejecución real, presentación manual y recibo del organizador.

## Limitaciones y seguridad
- No declarar `DONE` por una tarea en cola, una respuesta de un modelo o una prueba solamente offline.
- No divulgar datos de clientes, URLs privadas, cámaras, direcciones IP ni credenciales.
- Priorizar modelos locales, sin consumo de servicios externos si no se necesita.
- Se permite reutilizar agentes y librerías, pero la integración Switch y el workflow participante se construyen durante el período oficial.
- **Sin automatismos de DevSwarm/Temporal como dependencia.** Cada avance debe incluir URL/SHA y logs/test específicos.

Última comprobación disponible: auditoría directa del 2 de noviembre, no prueba de Switch conectado.
