# Servidor de Correo con Twisted

## Introducción
La idea de la tarea es desarrollar un mail server que implemente el protocolo SMTP, que permita recibir, enviar y consultar correo electrónico. Este servidor se debe implementar utilizando la biblioteca Twisted para Python. Además para garantizar la seguridad se debe utilizar una capa segura como TLS, se puede utilizar la herramienta openssl. Se deben filtrar los correos dependiendo si el dominio al que van dirigidos se acepta o se rechaza. También se tiene que permitir la recepción de archivos adjuntos utilizando el estándar MIME.
Para la parte del cliente se recibe una lista de correos electrónicos con su correspondiente destinatario utilizando un archivo separado por comas (CSV), además de eso se recibe el servidor de correo electrónico que se utilizará para el envío de un mensaje. El mensaje se pasa como parámetro, dentro del mensaje se carga el nombre desde el SCV del destinatario como variable. Esto para enviar correos masivos y personalizados.
Un usuario debe poder usar el servidor de pop3 para que pueda acceder y leer su correo electrónico desde cualquier cliente que use ese protocolo. Para probar esto se puede usar thunderbird como cliente de correo electrónico. Además se debe usar cifrado SSL o TLS. Para el servicio de notificaciones se utilizará xmpp para que el usuario sepa que hay nuevo correo electrónico sin leer. Se debe utilizar un dominio, que se puede obtener gratis con Github student pack y namecheap en el que funcione el servicio de correo electrónico.

## Ambiente de desarrollo
El entorno de desarrollo utilizado fue Visual Studio Code, para editar el código, contar con integración con terminal y manejo de extensiones para Python. 
El lenguaje a utilizado fue Python 3, junto con el framework de red Twisted, para facilitar la implementación de servidores como SMTP y POP3.
Para la gestión de dependencias se utilizó un entorno virtual (venv), que permite aislar las bibliotecas del sistemas y evitar conflictos entre proyectos. Las dependencias del proyecto se instalaron mediante pip y se describen en el archivo requirements.txt.
El Debugging se realizó por medio de logs generados por el cliente y servidor como mensajes de info y warning, además de pruebas manuales utilizando herramientas como telnet para verificar el funcionamiento del protocolo POP3, e inspección directa de archivos .eml generados. También con pruebas funcionales completas enviando y recibiendo correos en entorno local y visualización mediante Thunderbird.

## Estructuras de datos usadas y funciones

### Componentes

| Archivo | Función |
|---------|---------|
| `smtpserver.py` | Servidor SMTP/ESMTP — recibe correo entrante |
| `smtpclient.py` | Cliente SMTP masivo — envía correos personalizados desde CSV |
| `pop3server.py` | Servidor POP3 — permite a los clientes descargar su correo |
| `xmpp_notifier.py` | Notificador XMPP/Jabber — alerta al usuario sobre correo nuevo |
| `mailstorage.py` | Capa de almacenamiento compartida en el sistema de archivos |
| `user_manager.py` | Herramienta CLI para administrar cuentas de usuario |
| `generate_certs.sh` | Script para generar certificados TLS autofirmados |

---
**Capa de persistencia (mailstorage.py):** es el núcleo que todos los demás módulos utilizan. Su estructura de datos principal es el índice JSON por buzón: una lista de dicts donde cada entrada guarda metadatos del mensaje (filename, uid, from, subject, size, read: bool). Los correos físicos se almacenan como archivos .eml (bytes RFC-2822 crudos) en una jerarquía base_path/domain/user/. Las funciones clave son save_message() que genera un nombre único con timestamp + hash MD5, delete_message() que actualiza el índice después de borrar el archivo, y mark_as_read() que modifica el flag read en el índice.

---
**Servidor SMTP con Twisted (smtpserver.py):** Tiene tres clases que colaboran. IncomingMessage implementa la interfaz IMessage de Twisted y acumula las líneas del correo entrante en una list[bytes] llamada _lines; cuando llega el fin del mensaje (eomReceived) une las líneas con b"\r\n".join() y llama a MailStorage.save_message(). MailDelivery implementa IMessageDelivery y contiene el accepted_domains: set — en validateTo() revisa si el dominio del destinatario está en ese set y lanza SMTPBadRcpt si no; si acepta, devuelve una lambda que instancia un IncomingMessage. SMTPServerFactory hereda de ServerFactory de Twisted y en buildProtocol() construye un smtp.ESMTP al que inyecta el MailDelivery y, si hay certificados, el contexto SSL para STARTTLS.

---
**Cliente de envío (smtpclient.py):** Funciones completamente independientes, sin clases. parse_message_file() devuelve una tupla (headers: dict, body: str) separando el archivo en la primera línea ---. substitute() usa la expresión regular compilada _VAR_RE = re.compile(r"\{\{(\w+)\}\}") para reemplazar cada {{variable}} con el valor del dict de la fila CSV correspondiente. build_message() construye un MIMEMultipart con MIMEText para el cuerpo y MIMEBase + encoders.encode_base64() para los adjuntos. El main() lee el CSV con csv.DictReader que produce una list[dict] donde las claves son los encabezados de columna, e itera llamando a send_one() por cada destinatario.

---
**Servidor POP3 con Twisted (pop3server.py):** UserMailbox implementa IMailbox y usa dos estructuras centrales: _messages: list[tuple[str, bytes]] (snapshot al inicio de sesión con pares (filename, contenido)) y _deleted: set[int] de índices marcados para borrar. Este patrón es importante: las eliminaciones son diferidas en memoria y solo se aplican físicamente cuando el cliente envía QUIT, momento en que se llama a sync(). JsonFileCredentialsChecker carga users.json en un _data: dict y en requestAvatarId() compara la contraseña contra texto plano o hash SHA-256; devuelve un Deferred de éxito o fallo. MailRealm implementa IRealm de Twisted Cred y en requestAvatar() resuelve el dominio del usuario y construye su UserMailbox.

---
**Notificador XMPP (xmpp_notifier.py):** XMPPNotifier mantiene una conexión Jabber persistente. Usa _pending: list[str] como cola de mensajes que llegan antes de que la autenticación termine, y _user_mapping: dict para mapear direcciones de correo a JIDs XMPP específicos. El patrón de reconexión es interesante: _on_disconnected() programa un reactor.callLater(30, self._connect) para reintentar automáticamente. notify() es la función pública que llama el servidor SMTP; si la conexión está activa envía inmediatamente con _send_raw(), si no, encola en _pending para enviar cuando llegue _on_authenticated().

---
**Gestión de cuentas (user_manager.py):** Trabaja sobre users.json, cuya estructura es dict[str, dict] donde la clave es "user@domain" y el valor contiene password_hash (SHA-256 hex) o password (texto plano, solo para desarrollo). load_creds() filtra claves que empiezan con _ y valores que no sean dict — corrección del bug anterior. hash_password() usa hashlib.sha256. Cada subcomando (cmd_add, cmd_list, cmd_passwd, cmd_info) carga el dict, lo modifica en memoria y lo guarda de vuelta con json.dump.

## Instrucciones para ejectura el programa

### 1 · Generar Certificados TLS
```bash
chmod +x generate_certs.sh
./generate_certs.sh midominio.com ./certs
```

### 2 · Crear Cuentas de Usuario
```bash
# Solicita la contraseña de forma interactiva
python user_manager.py add -u alice@midominio.com -s /var/mail

# Con contraseña explícita (no recomendado en producción)
python user_manager.py add -u bob@midominio.com -p secret123 -s /var/mail

# Listar usuarios
python user_manager.py list

# Ver información del buzón
python user_manager.py info -u alice@midominio.com -s /var/mail
```
Las credenciales se guardan en `users.json`.

### 3 · Iniciar el Servidor SMTP
```bash
# Básico (puerto 2525, sin TLS)
python smtpserver.py -d midominio.com -s /var/mail -p 2525

# Con TLS — SMTPS en el 4650, STARTTLS en el 2525
python smtpserver.py \
    -d midominio.com,mail.midominio.com \
    -s /var/mail \
    -p 2525 \
    --ssl-cert certs/server.crt \
    --ssl-key  certs/server.key \
    --ssl-port 4650 \
    --starttls

# Con notificaciones XMPP
python smtpserver.py -d midominio.com -s /var/mail -p 2525 \
    --xmpp-config examples/xmpp_config.json
```

### 4 · Iniciar el Servidor POP3
```bash
# POP3 sin cifrado
python pop3server.py -s /var/mail -p 1100 --credentials users.json --domain midominio.com

# Con POP3S (TLS implícito)
python pop3server.py \
    -s /var/mail \
    -p 1100 \
    --ssl-cert certs/server.crt \
    --ssl-key  certs/server.key \
    --ssl-port 9950 \
    --credentials users.json \
    --domain midominio.com
```

### 5 · Enviar Correo Masivo Personalizado
```bash
# Vista previa sin enviar
python smtpclient.py \
    -h localhost:2525 \
    -c examples/recipients.csv \
    -m examples/message_template.txt \
    --dry-run

# Envío con STARTTLS
python smtpclient.py \
    -h mail.midominio.com:587 \
    -c destinatarios.csv \
    -m campana.txt \
    --tls \
    -u noreply@midominio.com \
    -P micontrasena

# Envío por SMTPS (TLS implícito, puerto 465)
python smtpclient.py \
    -h mail.midominio.com:465 \
    -c destinatarios.csv \
    -m campana.txt \
    --ssl
```


### Adicionalmente:
---
### Configuración DNS (para un dominio real)

Para que el servidor reciba correo para `midominio.com`, agrega los siguientes registros DNS:

```dns
; Registro MX — indica a Internet dónde entregar el correo
midominio.com.      IN  MX  10  mail.midominio.com.

; Registro A — resuelve el nombre del servidor de correo
mail.midominio.com. IN  A      <IP_PÚBLICA_DE_TU_SERVIDOR>

; Registro PTR — DNS inverso (se configura en el panel de tu VPS)
<IP>.in-addr.arpa.  IN  PTR   mail.midominio.com.

; Opcional: SPF — reduce la clasificación como spam
midominio.com.      IN  TXT   "v=spf1 mx ~all"
```

### Configuración del Notificador XMPP (`examples/xmpp_config.json`)

```json
{
  "jid":       "mailbot@servidor-xmpp.com",
  "password":  "tu_contraseña_xmpp",
  "server":    "servidor-xmpp.com",
  "port":      5222,
  "recipient": "admin@servidor-xmpp.com",
  "user_mapping": {
    "alice@midominio.com": "alice_xmpp@chat.example.org"
  }
}
```


## Actividades realizadas por el estudiante
| Actividad | Tiempo invertido | Fecha |
|---|:---:|:---:|
| Realización del kick-off  | 2 horas | 17/04/2026 |
| Tratar de adquirir del dominio e investigación de xmpp notifier | 1 hora | 17/04/2026 |
| Comienzo del smtp server, mail storage, smtp client | 3 horas | 17/04/2026 |
| Pruebas de los módulos y revisión de errores | 2 horas | 18/04/2026 |
| Arreglos de smtp server y mail storage, desarrollo de pop3 server| 3 horas | 18/04/2026 |
| Probando cosas de SSL/TLS | 1 hora | 18/04/2026 |
| Pruebas de todo en local y correción de errores | 2 horas | 19/04/2026 |
| Finalización de módulos | 3 horas | 20/04/2026 |
| Pruebas finales | 2 horas | 20/04/2026 |
| Documentación | 2 horas | 20/04/2026 |
Total de horas aproximadamente: 20



## Autoevaluación

Se presentaron complicaciones a la hora de desarrollar las funcionaldidades con TLS, esta parte se puede probar pero tiene ciertos bugs que impiden el correcto funcionamiento. Tampoco se pudo implementar el mail server con un dominio propio adquirido, ya que no me fue posible adquirir el dominio de manera gratis a pesar de que lo intenté con el GitHub Student Pack mediante name.com y namecheap, sin embargo, name.com pedía tarjeta de crédito a pesar de ser gratis y no aceptaba mi tarjeta, namecheap decía que la institución no estaba registrada entonces no podía reclamar la oferta de estudiante. Otro problema fue el XMPP Notifier el cuál se intentó probar de manera local con jabber pero no se logró configurar bien. Por otra parte, la mayoría del tiempo estuve trabajando de manera local con visual studio code, por lo que no se realizaron muchos commits al github.

### Rúbrica de evaluación y autoevluación:

| Rubro | Calificación |
|---|:---:|
| kick-off | 10 |
| smtp-server | 10 |
| smtp-client | 10 |
| pop3-server | 10 |
| xmpp-notifier | 5 |
| Modo SSL en el pop3 y smtp-server | 5 |
| smtp-server en dominio | 0 |
| Documentación utilizando latex o markdown | 10 |
| Opcional 1 | 10 |
| Opcional 2 | 0 |

| Rubro | Calificación |
|---|:---:|
| Aprendizaje del protocolo SMTP  | 5 |
| Aprendizaje del protocolo pop3 | 5 |
| Aprendizaje del protocolo xmpp | 3 |
| Aprendizaje de la capa SSL/TLS | 4 |
| Organización de Tiempo | 4 |

---

## Lecciones Aprendidas:

Primero que nada es importante organizar bien el tiempo para cumplir adecuadamente con lo solicitado sin verse con mucho estrés o presión antes de la entrega.
También destaco la importancia de la seguridad en los correos electrónicos ya que es uno los principales vectoresd de ataque en seguridad de software para realizar phishing.
Es importante tener un dominio adquirido con tiempo ya que el Github student pack tarda aproximadamente 3 días en dar los beneficios al estudiante una vez que se aprueba la solicitud.
Es importante conocer los protocolos que hay detrás de cosas que utilizamos todos los días como el correo electrónico, que aún sigue siendo un medio de comunicación super usado, es uno de los principales medios de comunicación formal del mundo.

## Bibliografía:

- Twisted Matrix Labs. (2025). Welcome to the Twisted documentation. https://docs.twisted.org/
- Python Software Foundation. (2025). Python 3 documentation (versión 3.13). https://docs.python.org/3/
- OpenSSL Project Authors. (2024). OpenSSL cryptography and SSL/TLS toolkit (versión 3.3). OpenSSL Library. https://openssl-library.org/
- Python Cryptographic Authority. (2026). pyOpenSSL: Python wrapper module around the OpenSSL library (versión 26.0.0) [Software]. PyPI. https://pypi.org/project/pyOpenSSL/
- Klensin, J. (2008). Simple Mail Transfer Protocol (RFC 5321). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc5321
- Myers, J., & Rose, M. (1996). Post Office Protocol — Version 3 (RFC 1939). Internet Engineering Task Force. https://www.ietf.org/rfc/rfc1939.txt
- Freed, N., & Borenstein, N. (1996a). Multipurpose Internet Mail Extensions (MIME) part one: Format of Internet message bodies (RFC 2045). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc2045
- Saint-Andre, P. (2011). Extensible Messaging and Presence Protocol (XMPP): Core (RFC 6120). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc6120
- The Linux Kernel Organization. (2025). The Linux kernel documentation. https://www.kernel.org/doc/html/latest/