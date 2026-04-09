# VGymRobot

Automatización de reservas de clases en VivaGym con tres carriles de ejecución:

1. `Local legacy`: script Python tradicional con `.env` y `preferences.yaml`.
2. `Local watch`: vigilancia local de una clase concreta cada `N` segundos durante `M` minutos.
3. `Remoto multiusuario`: Telegram + Supabase + GitHub Actions + Playwright.

El proyecto está orientado a cazar plazas liberadas por desapuntamientos y no solo a reservar justo al abrirse la ventana.

## Estado actual

La arquitectura actual convive en dos capas:

- Una capa `single-user` basada en archivos locales y workflows clásicos de GitHub.
- Una capa `multi-user MVP` basada en `Telegram`, `Supabase` y un `remote worker` en GitHub Actions.

La capa multiusuario es hoy el camino más avanzado para uso real desde móvil.

## Qué hace exactamente

- Hace login en la web de VivaGym con Playwright.
- Navega a `/booking` y selecciona el día correcto en el swiper.
- Busca una clase por `día + hora + nombre`.
- Comprueba disponibilidad real en la tarjeta de la clase.
- Expande la entrada de la clase y pulsa el botón real de reserva.
- Reintenta de forma periódica hasta reservar o expirar la ventana de vigilancia.
- Persiste el estado para poder consultar intentos, estado final y motivo.

## Modos de uso

### 1. Modo local legacy

Archivo principal:
- [main.py](/Users/alopez/vgymrobot/vgymrobot/src/main.py)

Características:
- carga `preferences.yaml`
- carga credenciales desde `.env`
- decide qué `targets` están dentro de la ventana de vigilancia
- ejecuta Playwright en local
- usa `RetryManager` para reintentos en una sola ejecución

Cuándo usarlo:
- pruebas rápidas
- depuración local
- reservas con una sola cuenta

### 2. Modo local watch

Archivo principal:
- [local_watch.py](/Users/alopez/vgymrobot/vgymrobot/src/local_watch.py)

Características:
- crea o reactiva una solicitud local
- la guarda en `state/requests.json`
- ejecuta un intento completo
- duerme `interval_seconds`
- repite hasta reservar o hasta `duration_minutes`

Cuándo usarlo:
- quieres probar localmente el patrón “cada 2 minutos durante 2 horas”
- quieres tener control manual total del proceso

### 3. Modo remoto multiusuario

Piezas principales:
- bot de Telegram
- Supabase como backend y persistencia
- GitHub Actions como worker Playwright

Cuándo usarlo:
- un usuario no técnico quiere lanzar reservas desde móvil
- varias personas quieren usar el sistema con sus propias credenciales
- no quieres depender de tu máquina encendida

## Arquitectura actual

```text
Telegram user
  -> telegram-webhook (Supabase Edge Function)
  -> booking_requests + member_accounts (Supabase DB)
  -> remote-worker.yml (GitHub Actions)
  -> remote_worker.py
  -> worker-api (Supabase Edge Function)
  -> booking_requests update
  -> Telegram notification
```

## Flujos completos

### Flujo A. Reserva local legacy

1. `python src/main.py`
2. [config.py](/Users/alopez/vgymrobot/vgymrobot/src/config.py) carga:
   - `preferences.yaml`
   - `.env`
3. [main.py](/Users/alopez/vgymrobot/vgymrobot/src/main.py) filtra `targets`
4. [auth.py](/Users/alopez/vgymrobot/vgymrobot/src/auth.py) hace login
5. [booking.py](/Users/alopez/vgymrobot/vgymrobot/src/booking.py) navega a `/booking`
6. [retry.py](/Users/alopez/vgymrobot/vgymrobot/src/retry.py) coordina reintentos en una sola ejecución
7. [notifier.py](/Users/alopez/vgymrobot/vgymrobot/src/notifier.py) notifica el resultado

### Flujo B. Vigilancia local concreta

1. `python src/local_watch.py --day ... --time ... --class-name ...`
2. [request_state.py](/Users/alopez/vgymrobot/vgymrobot/src/request_state.py) crea o reactiva una `BookingRequest`
3. la solicitud se guarda en [requests.json](/Users/alopez/vgymrobot/vgymrobot/state/requests.json)
4. [local_watch.py](/Users/alopez/vgymrobot/vgymrobot/src/local_watch.py) llama a [process_requests.py](/Users/alopez/vgymrobot/vgymrobot/src/process_requests.py)
5. cada ciclo hace:
   - login
   - navegación
   - intento de reserva
   - actualización de estado
6. al terminar:
   - `booked`
   - `expired`
   - o `cancelled`

### Flujo C. GitHub clásico por solicitudes en archivo

Workflows implicados:
- [request.yml](/Users/alopez/vgymrobot/vgymrobot/.github/workflows/request.yml)
- [book.yml](/Users/alopez/vgymrobot/vgymrobot/.github/workflows/book.yml)

Secuencia:
1. el usuario lanza `VGymRobot - Solicitar Reserva`
2. [request_create.py](/Users/alopez/vgymrobot/vgymrobot/src/request_create.py) inserta o reutiliza la solicitud
3. la solicitud se guarda en [requests.json](/Users/alopez/vgymrobot/vgymrobot/state/requests.json)
4. se hace un primer intento inmediato
5. `VGymRobot - Procesar Solicitudes` sigue revisando pendientes por cron

Este carril sigue existiendo, pero ya no es la opción más cómoda para uso externo.

### Flujo D. Telegram + Supabase + GitHub remote worker

Secuencia exacta de una petición:

1. Un usuario escribe en Telegram:
   - `/credenciales correo contraseña`
   - `/reservar viernes 16:15 V-Metcon`

2. Telegram envía el update al webhook:
   - [telegram-webhook/index.ts](/Users/alopez/vgymrobot/vgymrobot/supabase/functions/telegram-webhook/index.ts)

3. El webhook responde `200 OK` inmediatamente a Telegram y procesa el comando en background con `EdgeRuntime.waitUntil(...)`.

4. Si el comando es `/credenciales`:
   - cifra email y contraseña con `CREDENTIALS_SECRET`
   - hace upsert en la tabla `member_accounts`

5. Si el comando es `/reservar`:
   - busca la cuenta asociada al `telegram_chat_id`
   - crea una fila en `booking_requests`
   - calcula:
     - `target_date`
     - `interval_seconds`
     - `watch_until`
   - responde en Telegram con `Solicitud creada`
   - llama a GitHub Actions mediante API REST

6. GitHub dispara:
   - [remote-worker.yml](/Users/alopez/vgymrobot/vgymrobot/.github/workflows/remote-worker.yml)

7. El workflow ejecuta:
   - [remote_worker.py](/Users/alopez/vgymrobot/vgymrobot/src/remote_worker.py)

8. `remote_worker.py`:
   - pide la solicitud a [worker_api.py](/Users/alopez/vgymrobot/vgymrobot/src/worker_api.py)
   - `worker_api.py` llama a:
     - [worker-api/index.ts](/Users/alopez/vgymrobot/vgymrobot/supabase/functions/worker-api/index.ts)
   - el backend devuelve:
     - metadatos de la solicitud
     - credenciales del usuario descifradas

9. El worker remoto:
   - inyecta credenciales en `AppConfig`
   - ejecuta un intento completo con Playwright
   - actualiza `attempts`, `last_result`, `last_checked_at`
   - duerme `interval_seconds`
   - repite hasta `booked`, `expired` o `cancelled`

10. Cuando el backend recibe un update final:
   - si `status = booked`, envía mensaje de éxito por Telegram
   - si `status = expired`, envía mensaje de expiración por Telegram

## Privacidad y aislamiento entre usuarios

Las respuestas del bot son `point-to-point`, no broadcast.

Cada usuario queda asociado a su `telegram_chat_id`:

- las credenciales se guardan en `member_accounts.telegram_chat_id`
- `/estado` filtra por la cuenta asociada a ese chat
- `/cancelar` solo afecta a solicitudes del mismo chat
- las notificaciones finales se envían al `telegram_chat_id` asociado a la solicitud

Consecuencia:
- si tú reservas desde tu chat, las respuestas te llegan a ti
- si otra persona reserva desde su chat, las respuestas le llegan a esa persona
- no se mezclan salvo que uséis un grupo o la misma cuenta de Telegram

## Artefactos y persistencia

### Archivos locales

- [preferences.yaml](/Users/alopez/vgymrobot/vgymrobot/preferences.yaml)
  - configuración base del gimnasio
  - targets legacy
  - ventana de vigilancia base
  - parámetros de retry legacy

- [.env.example](/Users/alopez/vgymrobot/vgymrobot/.env.example)
  - plantilla de variables de entorno locales

- [requests.json](/Users/alopez/vgymrobot/vgymrobot/state/requests.json)
  - estado de solicitudes del carril local / GitHub clásico

- `screenshots/`
  - capturas de Playwright para debug

- `logs/`
  - logs locales de ejecución

### Base de datos remota

Definida en [schema.sql](/Users/alopez/vgymrobot/vgymrobot/supabase/schema.sql).

Tablas:

- `member_accounts`
  - un usuario por `telegram_chat_id`
  - credenciales cifradas
  - club por defecto

- `booking_requests`
  - solicitud individual de reserva
  - estado operativo del worker
  - timestamps y resultado del último intento

Campos relevantes de `booking_requests`:

- `id`
- `account_id`
- `club`
- `day`
- `time`
- `class_name`
- `target_date`
- `interval_seconds`
- `watch_until`
- `status`
- `attempts`
- `last_result`
- `last_checked_at`
- `booked_at`

## Componentes técnicos

### Núcleo Playwright

- [auth.py](/Users/alopez/vgymrobot/vgymrobot/src/auth.py)
  - selectores del login
  - detección de dashboard
  - detección de errores de login

- [booking.py](/Users/alopez/vgymrobot/vgymrobot/src/booking.py)
  - navegación a `/booking`
  - selección de día en el swiper
  - matching por nombre y hora
  - expansión de la clase
  - click en `book-button`
  - heurísticas de confirmación de reserva

### Configuración

- [config.py](/Users/alopez/vgymrobot/vgymrobot/src/config.py)
  - modelo `AppConfig`
  - carga YAML + `.env`
  - `with_runtime_credentials(...)` para inyectar credenciales remotas

### Persistencia local

- [request_state.py](/Users/alopez/vgymrobot/vgymrobot/src/request_state.py)
  - modelo `BookingRequest`
  - alta/reactivación por `id`
  - expiración de solicitudes vencidas

- [request_create.py](/Users/alopez/vgymrobot/vgymrobot/src/request_create.py)
  - crea solicitudes manuales del carril clásico

- [process_requests.py](/Users/alopez/vgymrobot/vgymrobot/src/process_requests.py)
  - procesa una o varias solicitudes locales persistidas

### Worker remoto

- [remote_worker.py](/Users/alopez/vgymrobot/vgymrobot/src/remote_worker.py)
  - bucle de intento remoto
  - consulta estado remoto antes de cada intento
  - respeta `cancelled`, `booked` y `expired`

- [worker_api.py](/Users/alopez/vgymrobot/vgymrobot/src/worker_api.py)
  - cliente HTTP minimalista hacia `worker-api`

### Backend Supabase

- [telegram-webhook/index.ts](/Users/alopez/vgymrobot/vgymrobot/supabase/functions/telegram-webhook/index.ts)
  - entrada de comandos desde Telegram
  - cifrado de credenciales
  - creación de solicitudes
  - disparo de GitHub

- [worker-api/index.ts](/Users/alopez/vgymrobot/vgymrobot/supabase/functions/worker-api/index.ts)
  - devuelve al worker la solicitud y credenciales descifradas
  - persiste updates del worker
  - envía notificaciones finales por Telegram

- [_shared/crypto.ts](/Users/alopez/vgymrobot/vgymrobot/supabase/functions/_shared/crypto.ts)
  - cifrado AES-GCM de credenciales

- [_shared/github.ts](/Users/alopez/vgymrobot/vgymrobot/supabase/functions/_shared/github.ts)
  - llamada a `workflow_dispatch` en GitHub

- [_shared/telegram.ts](/Users/alopez/vgymrobot/vgymrobot/supabase/functions/_shared/telegram.ts)
  - envío de mensajes con `sendMessage`

### Workflows de GitHub

- [request.yml](/Users/alopez/vgymrobot/vgymrobot/.github/workflows/request.yml)
  - carril clásico manual basado en archivo

- [book.yml](/Users/alopez/vgymrobot/vgymrobot/.github/workflows/book.yml)
  - cron del carril clásico

- [remote-worker.yml](/Users/alopez/vgymrobot/vgymrobot/.github/workflows/remote-worker.yml)
  - worker remoto multiusuario
  - `timeout-minutes: 150`
  - `concurrency` por `request_id`

## Selectores reales de VivaGym

El sistema usa selectores `data-cy` observados directamente en la SPA de VivaGym.

Ejemplos importantes:

- filtro de centros
- carrusel de fechas
- entradas `participation-entry-*`
- `booking-name`
- `start-time`
- `booking-state`
- `expand-button`
- `book-button`

La lógica vive en [booking.py](/Users/alopez/vgymrobot/vgymrobot/src/booking.py).

## Secretos y configuración

### Local / single-user

Archivo `.env`:

- `GYM_USERNAME`
- `GYM_PASSWORD`
- opcional `NTFY_TOPIC`
- opcional `NTFY_SERVER`

### GitHub clásico

Secrets de Actions:

- `GYM_USERNAME`
- `GYM_PASSWORD`
- opcional `NTFY_TOPIC`

### Supabase Edge Functions

Secrets:

- `CREDENTIALS_SECRET`
  - cifra las credenciales de VivaGym por usuario

- `TELEGRAM_BOT_TOKEN`
  - token del bot de Telegram

- `GITHUB_WORKFLOW_TOKEN`
  - fine-grained PAT para disparar workflows

- `GITHUB_OWNER`
- `GITHUB_REPO`
- `GITHUB_WORKFLOW_ID`
- `GITHUB_REF`

- `WORKER_SHARED_SECRET`
  - secreto compartido entre `worker-api` y GitHub worker

### GitHub Actions para el worker remoto

Secrets:

- `WORKER_API_BASE_URL`
  - `https://<project-ref>.supabase.co/functions/v1`

- `WORKER_SHARED_SECRET`
  - debe coincidir exactamente con el de Supabase

## Configuración de Supabase

Archivos:

- [schema.sql](/Users/alopez/vgymrobot/vgymrobot/supabase/schema.sql)
- [config.toml](/Users/alopez/vgymrobot/vgymrobot/supabase/config.toml)

`config.toml` desactiva `verify_jwt` para:

- `telegram-webhook`
- `worker-api`

Esto es necesario porque:
- Telegram no envía JWT de Supabase
- GitHub tampoco va a llamar a `worker-api` con JWT de Supabase

La protección de `worker-api` se hace con `x-worker-secret`.

## Configuración de Telegram

Comandos actuales:

- `/start`
- `/credenciales <correo> <contraseña>`
- `/reservar <dia> <hora> <clase>`
- `/estado`
- `/cancelar <request_id>`

Ejemplos válidos:

```text
/credenciales nombre@email.com clave123
/reservar viernes 16:15 V-Metcon
/reservar sabado 10:30 GAP
/estado
```

Importante:
- Telegram responde por chat privado
- el webhook procesa en background para no bloquear la respuesta de Telegram
- se puede limpiar la cola pendiente con `drop_pending_updates=true` al volver a hacer `setWebhook`

## Observabilidad y monitorización

### GitHub Actions

Para el carril remoto:
- abre `VGymRobot - Remote Worker`
- inspecciona el job `remote-worker`

Ahí verás:
- login
- navegación
- intentos
- espera entre ciclos
- resultado de cada intento

### Supabase

Tablas:
- `booking_requests`
- `member_accounts`

Campos útiles en `booking_requests`:
- `status`
- `attempts`
- `last_result`
- `last_checked_at`
- `booked_at`

Functions:
- `telegram-webhook`
- `worker-api`

### Telegram

El usuario final debería ver:
- confirmación de creación
- confirmación de lanzamiento del worker
- mensaje final de `booked` o `expired`

## Cómo usar el sistema hoy

### Opción A. Local watch

```bash
cd /Users/alopez/vgymrobot/vgymrobot
source venv/bin/activate
python src/local_watch.py --day viernes --time 16:15 --class-name V-Metcon --interval-seconds 120 --duration-minutes 120
```

### Opción B. GitHub clásico

1. Abre `VGymRobot - Solicitar Reserva`
2. Rellena:
   - `day`
   - `time`
   - `class_name`
3. El estado queda en [requests.json](/Users/alopez/vgymrobot/vgymrobot/state/requests.json)

### Opción C. Telegram multiusuario

1. El usuario abre el bot
2. Envía `/credenciales ...`
3. Envía `/reservar ...`
4. El sistema crea la solicitud en Supabase
5. GitHub ejecuta el worker
6. Telegram envía el resultado final

## Coste esperado

### Local

- coste cero salvo tu propia máquina

### GitHub clásico

- si el repo es público y usas runners estándar, normalmente gratis
- si el repo es privado, consume minutos

### Multiusuario remoto

- Supabase:
  - base de datos y Edge Functions dentro del free tier, con los límites del plan
- Telegram Bot API:
  - gratis
- GitHub Actions:
  - depende de si el repo es público o privado

## Limitaciones actuales

- El comando `/credenciales` sigue mandando la contraseña por chat privado de Telegram.
- Para producción real sería mejor una web o Mini App para onboarding de credenciales.
- El worker remoto actual vigila durante `2 horas` desde la creación de la solicitud.
- La confirmación de reserva en VivaGym todavía depende de heurísticas del DOM después del click.
- Los selectores de VivaGym pueden cambiar sin aviso.
- Hay dos carriles de ejecución coexistiendo y ambos siguen en el repo por compatibilidad.

## Riesgos y decisiones de diseño

- `worker-api` expone una función pública sin JWT, pero protegida por `WORKER_SHARED_SECRET`.
- Las credenciales de gimnasio no se guardan en claro en Supabase; se cifran con `CREDENTIALS_SECRET`.
- GitHub no almacena credenciales de gimnasio por usuario; el worker las obtiene del backend en runtime.
- El bot no comparte resultados entre usuarios porque todo se resuelve por `telegram_chat_id`.

## Documentación adicional

- [multiuser-supabase-telegram.md](/Users/alopez/vgymrobot/vgymrobot/docs/multiuser-supabase-telegram.md)

## Siguiente evolución recomendada

Si se quiere endurecer el sistema para producción, los pasos más lógicos son:

1. sustituir `/credenciales` por una web segura o Telegram Mini App
2. añadir comandos administrativos (`/limpiar`, `/quiensoy`, `/misdatos`)
3. mejorar las heurísticas de confirmación post-click en VivaGym
4. añadir pruebas automáticas sobre el flujo remoto
5. separar más claramente el carril legacy del carril multiusuario
