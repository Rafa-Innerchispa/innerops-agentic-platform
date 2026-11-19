# InnerOS Managed Mail: SMTP2GO

Servicio interno para que PC Doctor administre salida de correo por cliente. Usa la API real de SMTP2GO y el owner vault existente. No levanta otro servidor HTTP ni publica claves de administraciÃ³n. No requiere modelos de IA, polling periÃ³dico, SMS, IP dedicada ni archivado de pago.

## QuÃ© ofrece

- Consultar subcuentas, cupos contratados, dominios, usuarios y actividad de entrega.
- Crear subcuentas y registrar las existentes sin duplicarlas.
- AÃ±adir/verificar dominios y obtener los registros DNS que exige el proveedor.
- Crear un usuario de relay por cliente, con contraseÃ±a aleatoria persistida en el vault antes de crear el usuario.
- Comprobar SMTP AUTH por STARTTLS 587 con verificaciÃ³n de certificado.
- Actualizar nombre y cupo del cliente cuando el propietario haya aprobado el cambio.
- Auditar operaciones y conservar reservas de aprovisionamiento para no repetir mutaciones cuyo resultado se desconoce.

El conector no tiene operaciones de borrado ni cierre de cuentas. La credencial del proveedor debe excluir igualmente esos endpoints. Tampoco puede administrar otras claves API, activar SMS o comprar IPs. Las consultas de estadÃ­sticas que SMTP2GO no admite con una clave del padre deben obtenerse con la credencial del cliente o con la consulta de subcuentas; no se presentan como estadÃ­sticas cero.

## Acceso y persistencia

Solo operaciones internas del propietario o tareas que hayan pasado la autorizaciÃ³n canÃ³nica de InnerOS deben ejecutar la CLI con `--apply`. La CLI local no sustituye la autenticaciÃ³n ni es un endpoint pÃºblico para clientes. Las modificaciones sin `--apply` son vistas previas, claramente marcadas `dry_run`; no confundirlas con ejecuciÃ³n.

- Vault privado: categorÃ­a `smtp2go`, clave `admin_api_key`.
- ContraseÃ±as SMTP: `<client_id>_smtp_password`, sin incluirlas en respuestas ni cÃ³digo.
- Base Mongo existente, sin base nueva: colecciones `ralfia_smtp2go_clients`, `ralfia_smtp2go_audit`, `ralfia_smtp2go_provisioning`.
- Las reservas pendientes tras timeout requieren reconciliaciÃ³n con el proveedor; no relanzar creaciÃ³n ni borrar reservas automÃ¡ticamente.
- Los IDs de cliente y el dominio quedan vinculados de forma inmutable. Los Ã­ndices Ãºnicos y las reservas evitan carreras de aprovisionamiento.

La consola y los agentes internos pueden importar `inneros_core_runtime.smtp2go_service.ManagedMail`; no necesitan recibir la clave maestra. El catÃ¡logo descriptivo se encuentra en `config/services/smtp2go-managed-mail.json`. Este cambio no reinicia MCP/Router ni aÃ±ade una herramienta pÃºblica sin control de acceso.

## Uso

Desde `platform`, con el entorno existente y su `.env` protegido:

```bash
venv/bin/python scripts/smtp2go_managed_mail.py list-clients
venv/bin/python scripts/smtp2go_managed_mail.py register cliente --subaccount-id ID_REAL --domain example.com --apply
venv/bin/python scripts/smtp2go_managed_mail.py status cliente
venv/bin/python scripts/smtp2go_managed_mail.py ensure-domain cliente --apply
venv/bin/python scripts/smtp2go_managed_mail.py ensure-smtp-user cliente --apply
venv/bin/python scripts/smtp2go_managed_mail.py auth-check cliente
venv/bin/python scripts/smtp2go_managed_mail.py activity cliente
venv/bin/python scripts/smtp2go_managed_mail.py create-client nuevo --name 'Cliente nuevo' --domain example.net --cycle-limit 5000
```

El Ãºltimo comando solo prepara una vista previa. Crear una subcuenta real requiere `--apply` despuÃ©s de validar el contrato y el cupo disponible. No incluye invitaciones automÃ¡ticas a correos ajenos ni cambios del plan maestro. El proveedor impone sus cupos: no existe envÃ­o ilimitado por eliminar un lÃ­mite interno.

## Outlook sin cambios

La ruta buscada es `Outlook -> hosting actual -> relay SMTP2GO -> destinatario`. IMAP, buzones, contraseÃ±as de Outlook, MX y el nombre del servidor actual se conservan. Los CNAME nuevos autentican el dominio; **por sÃ­ solos no cambian la salida de Outlook**.

Hace falta acceso administrativo WHM/Exim o la intervenciÃ³n del proveedor de hosting para instalar un router exclusivo del dominio. En hosting compartido no se intenta obtener root ni instalar un relay global. Nunca cambiar el MX ni apuntar el nombre compartido de IMAP/SMTP a SMTP2GO para simular esta funciÃ³n.

Requisitos del cambio de Exim:

1. Respaldar la configuraciÃ³n y validar sus ACL y autenticadores actuales.
2. Enviar solo destinatarios remotos del dominio remitente autorizado y solo usuarios autenticados de ese dominio. Conservar entrega local y rutas de otros dominios.
3. Usar `mail.smtp2go.com:587`, autenticaciÃ³n obligatoria, STARTTLS obligatorio y certificado/hostname verificados; sin fallback silencioso a salida directa o sin cifrar.
4. Guardar credenciales fuera del webroot, en archivo legible Ãºnicamente por root/Exim segÃºn el diseÃ±o del proveedor. Nunca incluirlas en tickets de correo o en Git.
5. Validar sintaxis antes de una recarga acotada, probar desde un buzÃ³n real con Outlook sin cambios y comprobar el evento `delivered` y la recepciÃ³n final.
6. Revertir Ãºnicamente el router/transporte nuevo si falla la prueba. No vaciar la cola, reintentar en masa ni cambiar cuotas del servidor global.

La prueba directa por SMTP2GO y una autenticaciÃ³n 235 no certifican este Ãºltimo paso. Los registros operativos deben indicar `hosting_relay_status=not_configured` hasta tener evidencia de la ruta real.

## Fuentes oficiales

- [SMTP2GO con Exim, incluida selecciÃ³n por dominio](https://www.smtp2go.com/setupguide/cpanel-whm/)
- [API y subcuentas](https://developers.smtp2go.com/docs/getting-started)
- [Crear subcuentas](https://developers.smtp2go.com/reference/add-subaccount)
- [Usuarios SMTP](https://developers.smtp2go.com/reference/add-an-smtp-user)
- [ParÃ¡metros TLS de Exim](https://www.exim.org/exim-html-current/doc/html/spec_html/ch-the_smtp_transport.html)

## ValidaciÃ³n

`PYTHONPATH=platform pytest --import-mode=importlib tests/test_smtp2go_managed_mail.py` comprueba aislamiento de cliente, bloqueo de operaciones destructivas, errores sin secretos, TLS, prevenciÃ³n de duplicados y fallo seguro del vault. Con `python -m pytest`, ejecutar desde fuera de la raÃ­z del repositorio y pasar rutas absolutas: el paquete histÃ³rico `platform/` puede ocultar el mÃ³dulo estÃ¡ndar de Python con el mismo nombre. Estas pruebas no consumen cupo del proveedor ni envÃ­an correos. La validaciÃ³n externa debe conservar por separado request IDs, Message-ID, respuesta del destinatario y Authentication-Results; nunca claves ni contraseÃ±as.
