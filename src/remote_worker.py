"""
VGymRobot - Remote Worker
Worker largo para GitHub Actions: obtiene una solicitud externa del backend,
usa las credenciales del usuario y reintenta hasta reservar o expirar.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright

from src.auth import login
from src.booking import find_and_book_class, navigate_to_booking, take_debug_screenshot
from src.config import BookingTarget, get_local_now, load_config, with_runtime_credentials
from src.logger import setup_logger
from src.worker_api import WorkerAPIError, fetch_remote_request, update_remote_request

logger = setup_logger()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Worker remoto multiusuario")
    parser.add_argument("--request-id", required=True, help="ID de la solicitud remota")
    return parser.parse_args()


async def attempt_remote_booking(request_id: str) -> int:
    config = load_config(require_credentials=False)
    remote_request = fetch_remote_request(request_id)
    attempts = remote_request.attempts

    logger.info("=" * 60)
    logger.info(f"🤖 Remote worker arrancado para {remote_request.id}")
    logger.info(
        f"🎯 {remote_request.class_name} - {remote_request.day} {remote_request.time}"
    )
    logger.info(f"🏁 Vigilar hasta: {remote_request.watch_until}")
    logger.info("=" * 60)

    while True:
        remote_request = fetch_remote_request(request_id)
        if remote_request.status in {"cancelled", "booked", "expired"}:
            logger.info(
                f"⏹️ La solicitud {remote_request.id} ya está en estado "
                f"{remote_request.status}; saliendo"
            )
            return 0

        config = with_runtime_credentials(
            config,
            username=remote_request.member.gym_username,
            password=remote_request.member.gym_password,
            club=remote_request.club,
        )
        target = BookingTarget(
            day=remote_request.day,
            time=remote_request.time,
            class_name=remote_request.class_name,
            enabled=True,
            target_date=remote_request.target_date,
        )
        watch_until = datetime.fromisoformat(remote_request.watch_until)
        now = get_local_now(config)
        if now >= watch_until:
            update_remote_request(
                remote_request.id,
                status="expired",
                attempts=attempts,
                last_checked_at=now.isoformat(),
                last_result="Ventana de vigilancia expirada",
            )
            logger.info("⏹️ La solicitud ha expirado antes del siguiente intento")
            return 0

        attempts += 1
        logger.info(f"🔁 Intento remoto {attempts} para {remote_request.id}")

        try:
            result = await run_single_attempt(config, target)
        except Exception as exc:
            result = {"booked": False, "reason": f"Error inesperado: {exc}"}

        checked_at = get_local_now(config).isoformat()
        logger.info(f"📌 Resultado intento {attempts}: {result['reason']}")

        if result.get("booked"):
            update_remote_request(
                remote_request.id,
                status="booked",
                attempts=attempts,
                last_checked_at=checked_at,
                booked_at=checked_at,
                last_result=result["reason"],
            )
            logger.info("🎉 Reserva remota completada")
            return 0

        update_remote_request(
            remote_request.id,
            status="pending",
            attempts=attempts,
            last_checked_at=checked_at,
            last_result=result["reason"],
        )

        remaining_seconds = int((watch_until - get_local_now(config)).total_seconds())
        if remaining_seconds <= 0:
            update_remote_request(
                remote_request.id,
                status="expired",
                attempts=attempts,
                last_checked_at=checked_at,
                last_result="Ventana de vigilancia expirada",
            )
            logger.info("⏹️ La solicitud ha expirado tras el último intento")
            return 0

        sleep_seconds = min(remote_request.interval_seconds, remaining_seconds)
        logger.info(f"😴 Esperando {sleep_seconds}s para el siguiente intento...")
        await asyncio.sleep(sleep_seconds)


async def run_single_attempt(config, target: BookingTarget) -> dict:
    async with async_playwright() as p:
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
            logged_in = await login(page, config)
            if not logged_in:
                await take_debug_screenshot(page, "remote_login_failed")
                return {"booked": False, "reason": "No se pudo hacer login"}

            booking_ready = await navigate_to_booking(page, config)
            if not booking_ready:
                return {
                    "booked": False,
                    "reason": "No se pudo cargar la sección de reservas",
                }

            return await find_and_book_class(page, target, config)
        finally:
            await browser.close()


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(attempt_remote_booking(args.request_id))
    except WorkerAPIError as exc:
        logger.error(f"❌ Error con backend remoto: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
