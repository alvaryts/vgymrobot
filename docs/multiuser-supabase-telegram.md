# MVP Multiusuario: Supabase + Telegram + GitHub Worker

## Arquitectura

1. Telegram recibe comandos del usuario.
2. `telegram-webhook` guarda las credenciales del gimnasio cifradas en Supabase.
3. `telegram-webhook` crea una `booking_request`.
4. `telegram-webhook` dispara `remote-worker.yml` en GitHub Actions.
5. `remote_worker.py` pide al backend la solicitud y las credenciales del usuario.
6. El worker reintenta cada 120s hasta reservar o expirar.
7. `worker-api` actualiza el estado en Supabase y notifica por Telegram cuando reserva o expira.

## Cuentas que necesitas crear

1. Una cuenta/proyecto en Supabase.
2. Un bot de Telegram creado con `@BotFather`.
3. Un token de GitHub con permiso para disparar workflows del repo.

## Token de GitHub recomendado

Usa un `fine-grained personal access token` limitado al repo del worker.

Permisos mínimos recomendados:

- `Actions: Read and write`
- `Contents: Read`
- `Metadata: Read`

## Secretos en Supabase Edge Functions

- `CREDENTIALS_SECRET`
- `TELEGRAM_BOT_TOKEN`
- `GITHUB_WORKFLOW_TOKEN`
- `GITHUB_OWNER`
- `GITHUB_REPO`
- `GITHUB_WORKFLOW_ID`
- `GITHUB_REF`
- `WORKER_SHARED_SECRET`

## Secretos en GitHub Actions

- `WORKER_API_BASE_URL`
  - Ejemplo: `https://<project-ref>.supabase.co/functions/v1`
- `WORKER_SHARED_SECRET`

## Despliegue

1. Ejecuta `supabase/schema.sql` en el SQL editor.
2. Despliega las funciones:
   - `telegram-webhook`
   - `worker-api`
3. Configura el webhook del bot de Telegram apuntando a:
   - `https://<project-ref>.supabase.co/functions/v1/telegram-webhook`
4. Configura en GitHub el workflow `remote-worker.yml`.

## Despliegue con Supabase CLI

```bash
supabase login
supabase link --project-ref <project-ref>
supabase functions deploy telegram-webhook
supabase functions deploy worker-api
```

## Configurar el webhook de Telegram

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=https://<project-ref>.supabase.co/functions/v1/telegram-webhook"
```

## Secretos concretos a crear

### En Supabase Edge Functions

- `CREDENTIALS_SECRET`
  - Cadena larga aleatoria para cifrar usuario y contraseña del gimnasio.
- `TELEGRAM_BOT_TOKEN`
  - Token del bot creado en `@BotFather`.
- `GITHUB_WORKFLOW_TOKEN`
  - Fine-grained PAT con permisos sobre el repo.
- `GITHUB_OWNER`
  - Tu usuario u organización de GitHub.
- `GITHUB_REPO`
  - Nombre del repo, por ejemplo `vgymrobot`.
- `GITHUB_WORKFLOW_ID`
  - Déjalo en `remote-worker.yml` si usas este workflow.
- `GITHUB_REF`
  - Rama a ejecutar, normalmente `main`.
- `WORKER_SHARED_SECRET`
  - Secreto compartido entre GitHub y Supabase.

### En GitHub Actions

- `WORKER_API_BASE_URL`
  - `https://<project-ref>.supabase.co/functions/v1`
- `WORKER_SHARED_SECRET`
  - El mismo valor que en Supabase.

## Comandos del bot

- `/start`
- `/credenciales correo contraseña`
- `/reservar miercoles 17:00 V-Power`
- `/estado`
- `/cancelar <request_id>`

## Limitaciones del MVP

- La ventana de vigilancia se fija en 2 horas desde la creación.
- La experiencia de onboarding de cuenta todavía puede evolucionar hacia una interfaz más guiada.
- La ergonomía del flujo remoto seguirá mejorando según crezcan los casos de uso.
