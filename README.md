# 🤖 VGymRobot

Bot automatizado para reservar clases dirigidas en **Vivagym** de forma persistente y desatendida.

## 🎯 ¿Qué hace?

- Permite lanzar una **solicitud manual** con día, hora y clase desde GitHub Actions
- Un worker periódico sigue comprobando huecos hasta reservar o expirar la solicitud
- Inicia sesión en tu cuenta de Vivagym
- Usa `preferences.yaml` solo para configuración base del gimnasio, no para las solicitudes manuales
- Intenta reservar con **reintentos automáticos** y backoff exponencial
- También sirve para **cazar desapuntamientos** dentro de la ventana previa a la clase
- Puede guardar **screenshots y logs** locales para debugging
- (Futuro) Envía notificación push cuando consigue la reserva

## 📁 Estructura

```
vgymrobot/
├── .env.example                 # Plantilla de credenciales
├── .gitignore                   # Seguridad: ignora .env
├── preferences.yaml             # ⚙️ Configuración base del gimnasio
├── requirements.txt             # Dependencias Python
├── README.md
│
├── src/
│   ├── main.py                  # 🚀 Modo legacy / pruebas locales
│   ├── config.py                # Carga preferencias + credenciales
│   ├── auth.py                  # Login en Vivagym
│   ├── booking.py               # Motor de búsqueda y reserva
│   ├── request_create.py        # Crea solicitudes manuales
│   ├── process_requests.py      # Procesa solicitudes activas
│   ├── request_state.py         # Persistencia de solicitudes
│   ├── retry.py                 # Reintentos con backoff
│   ├── notifier.py              # Notificaciones (futuro)
│   └── logger.py                # Logging a consola + archivo
│
├── .github/workflows/
│   ├── request.yml              # 📝 Crear solicitud manual
│   └── book.yml                 # ⏰ Procesar solicitudes activas
│
├── state/                       # Estado persistente de solicitudes
├── logs/                        # Logs de ejecución
└── screenshots/                 # Capturas de debugging
```

## 🚀 Configuración Rápida

### 1. Fork/Clone del repo

```bash
git clone https://github.com/TU_USUARIO/vgymrobot.git
cd vgymrobot
```

### 2. Configurar credenciales en GitHub

Ve a **Settings → Secrets and variables → Actions** y añade:

| Secret | Valor |
|--------|-------|
| `GYM_USERNAME` | Tu email de Vivagym |
| `GYM_PASSWORD` | Tu contraseña de Vivagym |

### 3. Configurar el gimnasio base

`preferences.yaml` ya no define las solicitudes manuales. Ahora solo guarda
la configuración base, por ejemplo el club por defecto y la ventana de vigilancia.

### 4. Crear una solicitud de reserva

En GitHub:
- Ve a **Actions**
- Abre **VGymRobot - Solicitar Reserva**
- Rellena `day`, `time` y `class_name`
- Pulsa **Run workflow**

La solicitud se guarda en `state/requests.json` y el worker periódico la seguirá
procesando hasta reservar o hasta que expire su `watch_until`.

### 5. Ajustar horarios del worker

Edita `.github/workflows/book.yml` si quieres cambiar la frecuencia con la que se
revisan las solicitudes activas.

> ⚠️ GitHub Actions usa **UTC**. España (CEST) es UTC+2.

### 6. Activar workflow

- Ve a la pestaña **Actions** de tu repo
- Haz click en el workflow **VGymRobot - Solicitar Reserva**
- Click en **Run workflow** para crear una solicitud manual

## 🔧 Desarrollo Local

```bash
# Crear entorno virtual
python -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
playwright install chromium

# Crear .env con tus credenciales
cp .env.example .env
# Editar .env con tus datos reales

# Ejecutar
python src/main.py
```

## 💰 Costes

El coste depende sobre todo de dos factores:
- si el repositorio es público o privado
- cada cuánto revisa el worker de `book.yml`

Si usas un repo público con runners estándar de GitHub, normalmente este modelo
sale gratis. Si es privado, conviene ajustar la frecuencia del cron porque el
worker periódico consume minutos incluso cuando no consigue reserva.

## ⚠️ Notas Importantes

- **Selectores**: Los selectores del DOM pueden cambiar si Vivagym actualiza su web. En ese caso habrá que actualizar `auth.py` y `booking.py`.
- **Uso responsable**: Este bot es para uso personal. No abuses de la frecuencia de ejecución.
- **Estado**: Las solicitudes activas se guardan en `state/requests.json`.
