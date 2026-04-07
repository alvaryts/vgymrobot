"""
VGymRobot - Process Booking Requests
Procesa solicitudes persistentes activas hasta reservar o expirar.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright

from src.auth import login
from src.booking import find_and_book_class, navigate_to_booking, take_debug_screenshot
from src.config import get_local_now, load_config
from src.logger import setup_logger
from src.notifier import notify_failure, notify_success
from src.request_state import (
    active_requests,
    expire_overdue_requests,
    load_requests,
    save_requests,
)

logger = setup_logger()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Procesar solicitudes activas")
    parser.add_argument(
        "--request-id",
        help="Procesar solo una solicitud concreta",
    )
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    config = load_config()
    requests = load_requests()
    requests = expire_overdue_requests(requests, config)

    pending = active_requests(requests, config)
    if args.request_id:
        pending = [request for request in pending if request.id == args.request_id]

    if not pending:
        logger.info("ℹ️  No hay solicitudes activas para procesar")
        save_requests(requests)
        return 0

    logger.info(f"🧾 Solicitudes activas a procesar: {len(pending)}")

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
                logger.error("❌ No se pudo hacer login")
                await take_debug_screenshot(page, "request_login_failed")
                save_requests(requests)
                return 1

            for request in pending:
                logger.info(f"\n{'─' * 40}")
                logger.info(f"🛰️ Procesando solicitud {request.id}")
                logger.info(
                    f"🎯 {request.class_name} - {request.day.capitalize()} {request.time}"
                )
                logger.info(f"{'─' * 40}")

                config.club = request.club or config.club

                request.attempts += 1
                request.last_checked_at = get_local_now(config).isoformat()

                booking_ready = await navigate_to_booking(page, config)
                if not booking_ready:
                    request.last_result = "No se pudo cargar la sección de reservas"
                    continue

                result = await find_and_book_class(page, request.to_target(), config)
                request.last_result = result.get("reason")

                if result.get("booked"):
                    request.status = "booked"
                    request.booked_at = get_local_now(config).isoformat()
                    await notify_success(request.class_name, request.time, request.day)
                    await take_debug_screenshot(page, f"request_{request.id}_success")
                else:
                    await notify_failure(
                        f"{request.class_name} {request.day} {request.time}: "
                        f"{request.last_result}"
                    )

            requests = expire_overdue_requests(requests, config)

        finally:
            await browser.close()

    save_requests(requests)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
