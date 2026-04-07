"""
VGymRobot - Main Entry Point
Orquestador principal del bot de reserva de clases.

Flujo:
1. Carga configuración y credenciales
2. Determina qué clases hay que reservar hoy
3. Inicia Playwright (headless)
4. Login en Vivagym
5. Navega a reservas
6. Intenta reservar con reintentos
7. Notifica resultado
"""

import asyncio
import sys
import os
from datetime import datetime

# Asegurar que el directorio raíz del proyecto esté en el path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright

from src.config import load_config, AppConfig, BookingTarget, get_local_now
from src.auth import login
from src.booking import (
    get_target_for_today,
    navigate_to_booking,
    find_and_book_class,
    take_debug_screenshot,
)
from src.retry import RetryManager
from src.notifier import notify_success, notify_failure
from src.logger import setup_logger

logger = setup_logger()


def is_force_run_enabled() -> bool:
    """Devuelve True si se ha solicitado forzar la ejecución."""
    return os.getenv("FORCE_RUN", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def should_attempt_booking_now(config: AppConfig) -> bool:
    """
    Comprueba si ya ha llegado la hora de apertura configurada.

    Si `FORCE_RUN=true`, siempre permite la ejecución.
    """
    if is_force_run_enabled():
        logger.info("🚀 FORCE_RUN activo: se omite la restricción horaria")
        return True

    if not config.booking.respect_opening_time:
        return True

    now = get_local_now(config)

    try:
        open_time = datetime.strptime(
            config.booking.booking_opens_at, "%H:%M"
        ).time()
    except ValueError:
        logger.warning(
            "⚠️ booking.booking_opens_at tiene un formato inválido "
            f"('{config.booking.booking_opens_at}'); seguimos igualmente"
        )
        return True

    opening_datetime = now.replace(
        hour=open_time.hour,
        minute=open_time.minute,
        second=0,
        microsecond=0,
    )

    if now >= opening_datetime:
        return True

    remaining = opening_datetime - now
    minutes = int(remaining.total_seconds() // 60)
    logger.info(
        "⏳ Aún no se ha abierto la reserva en "
        f"{config.gym.timezone}. Faltan {minutes} min"
    )
    return False


async def attempt_booking(
    page, target: BookingTarget, config: AppConfig
) -> dict:
    """
    Un intento individual de reserva (función que se pasa al RetryManager).

    Args:
        page: Página de Playwright
        target: Clase objetivo
        config: Configuración

    Returns:
        dict con booked: bool y reason: str
    """
    # Recargar la página de reservas para obtener estado actualizado
    booking_ready = await navigate_to_booking(page, config)
    if not booking_ready:
        return {
            "booked": False,
            "reason": "No se pudo cargar la sección de reservas",
        }

    result = await find_and_book_class(page, target, config)
    return result


async def run_bot() -> bool:
    """
    Ejecuta el bot completo.

    Returns:
        True si la ejecución terminó sin errores fatales
    """
    logger.info("=" * 60)
    logger.info("🤖 VGymRobot - Iniciando")
    logger.info("=" * 60)

    # 1. Cargar configuración
    try:
        config = load_config()
    except Exception as e:
        logger.error(f"❌ Error cargando configuración: {e}")
        return False

    if not should_attempt_booking_now(config):
        logger.info("ℹ️  Saliendo sin error para respetar la hora de apertura")
        return True

    # 2. Determinar targets para hoy
    targets = get_target_for_today(config)
    if not targets:
        logger.info("ℹ️  No hay clases para reservar hoy. Saliendo sin error.")
        return True

    # 3. Iniciar Playwright
    any_booked = False
    fatal_error = False

    async with async_playwright() as p:
        # Lanzar browser headless (Chromium para mejor compatibilidad)
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="es-ES",
            timezone_id=config.gym.timezone,
        )

        page = await context.new_page()

        try:
            # 4. Login
            logged_in = await login(page, config)
            if not logged_in:
                logger.error("❌ No se pudo hacer login. Abortando.")
                await take_debug_screenshot(page, "login_failed")
                return False

            await take_debug_screenshot(page, "post_login")

            # 5. Intentar reservar cada target
            for target in targets:
                logger.info(f"\n{'─' * 40}")
                logger.info(
                    f"🎯 Objetivo: {target.class_name} - "
                    f"{target.day.capitalize()} {target.time}"
                )
                logger.info(f"{'─' * 40}")

                retry_manager = RetryManager(config.retry)

                result = await retry_manager.execute_with_retry(
                    attempt_booking, page, target, config
                )

                if result["success"]:
                    any_booked = True
                    await notify_success(
                        target.class_name, target.time, target.day
                    )
                    await take_debug_screenshot(page, "booking_success")
                else:
                    await notify_failure(
                        f"{target.class_name} a las {target.time}: "
                        f"{result['attempts']} intentos en "
                        f"{result['elapsed_minutes']:.1f}min"
                    )
                    await take_debug_screenshot(page, "booking_failed")

        except Exception as e:
            logger.error(f"❌ Error fatal: {e}")
            fatal_error = True
            await take_debug_screenshot(page, "fatal_error")
        finally:
            await browser.close()

    # 6. Resumen final
    logger.info("\n" + "=" * 60)
    if any_booked:
        logger.info("🎉 RESULTADO: Al menos una reserva completada con éxito")
    else:
        logger.info("ℹ️ RESULTADO: Ejecución completada sin reservas confirmadas")
    logger.info("=" * 60)

    return not fatal_error


def main():
    """Entry point para ejecución directa."""
    success = asyncio.run(run_bot())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
