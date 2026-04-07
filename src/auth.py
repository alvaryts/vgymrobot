"""
VGymRobot - Authentication Module
Maneja el login en la web de Vivagym usando Playwright.

Selectores obtenidos por exploración directa del formulario de login.
"""

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from src.config import AppConfig
from src.logger import setup_logger

logger = setup_logger()

# Selectores del formulario de login de Vivagym
SEL = {
    "email_input": "#email",
    "password_input": "#password",
    "submit_button": 'button[type="submit"]',
    # Post-login: aparece "Bienvenido" en el dashboard
    "welcome_text": "text=Bienvenido",
    # Navegación post-login
    "nav_reservas": 'a[href="/booking"]',
    "nav_principal": "text=Principal",
    "nueva_reserva": "text=Nueva reserva",
}


async def login(page: Page, config: AppConfig) -> bool:
    """
    Realiza el login en la web de Vivagym.

    Flujo:
    1. Navegar a /login
    2. Esperar renderizado de la SPA (Vue.js)
    3. Rellenar email y password
    4. Click en Entrar
    5. Verificar que aparece "Bienvenido"

    Returns:
        True si el login fue exitoso
    """
    login_url = config.gym.login_url
    logger.info(f"🔐 Iniciando login en {login_url}")

    try:
        # Navegar a login
        await page.goto(login_url, wait_until="networkidle", timeout=30000)

        # Esperar a que la SPA renderice el formulario
        await page.wait_for_selector(
            SEL["email_input"], state="visible", timeout=15000
        )

        logger.debug("Formulario de login visible, introduciendo credenciales...")

        # Rellenar email
        await page.locator(SEL["email_input"]).fill(config.credentials.username)

        # Rellenar password
        await page.locator(SEL["password_input"]).fill(config.credentials.password)

        # Click en Entrar
        await page.locator(SEL["submit_button"]).click()

        # Esperar a que aparezca el texto de bienvenida del dashboard
        try:
            await page.wait_for_selector(
                SEL["welcome_text"], timeout=15000
            )
            logger.info("✅ Login exitoso — Dashboard visible")
            return True
        except PlaywrightTimeout:
            pass

        # Alternativa: comprobar que ya no estamos en /login
        current_url = page.url
        if "/login" not in current_url:
            logger.info(f"✅ Login exitoso — Redirigido a: {current_url}")
            return True

        # Comprobar si hay error visible
        error_msg = page.locator(
            ".error-message, .alert-danger, .login-error, "
            "text=/error|incorrecta|inválid/i"
        )
        if await error_msg.count() > 0:
            error_text = await error_msg.first.text_content()
            logger.error(f"❌ Error de login: {error_text}")
            return False

        logger.warning("⚠️ Login incierto — seguimos en la página de login")
        return False

    except PlaywrightTimeout as e:
        logger.error(f"❌ Timeout durante el login: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Error inesperado durante el login: {e}")
        return False
