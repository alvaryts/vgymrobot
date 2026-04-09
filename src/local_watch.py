"""
VGymRobot - Local Watch Runner
Crea una solicitud y la reintenta localmente cada cierto intervalo.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.booking import next_target_occurrence
from src.config import BookingTarget, get_local_now, load_config
from src.logger import setup_logger
from src.process_requests import process_pending_requests
from src.request_state import (
    build_request,
    get_request_by_id,
    load_requests,
    save_requests,
    upsert_request,
)

logger = setup_logger()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vigilar localmente una clase")
    parser.add_argument("--day", required=True, help="Día: lunes..domingo")
    parser.add_argument("--time", required=True, help="Hora de la clase, ej. 17:00")
    parser.add_argument("--class-name", required=True, help="Nombre de la clase")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=120,
        help="Intervalo entre chequeos locales",
    )
    parser.add_argument(
        "--duration-minutes",
        type=int,
        default=120,
        help="Duración máxima de la vigilancia local",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    config = load_config()
    requests = load_requests()

    now = get_local_now(config)
    target = BookingTarget(
        day=args.day,
        time=args.time,
        class_name=args.class_name,
        enabled=True,
    )
    occurrence = next_target_occurrence(target, config)
    class_cutoff = occurrence - timedelta(minutes=5)
    local_deadline = now + timedelta(minutes=args.duration_minutes)
    watch_until = min(class_cutoff, local_deadline)

    request = build_request(
        config=config,
        day=args.day,
        time=args.time,
        class_name=args.class_name,
        watch_until=watch_until.isoformat(),
    )

    requests, saved_request, created = upsert_request(requests, request)
    if not created:
        saved_request.watch_until = watch_until.isoformat()
        saved_request.status = "pending"
        save_requests(requests)
    save_requests(requests)

    logger.info(
        f"{'✅' if created else 'ℹ️'} Vigilancia local "
        f"{'creada' if created else 'reutilizada'}: {saved_request.id}"
    )
    logger.info(
        f"   ⏱️ Cada {args.interval_seconds}s hasta {watch_until.isoformat()}"
    )

    while True:
        await process_pending_requests(request_id=saved_request.id)

        requests = load_requests()
        current = get_request_by_id(requests, saved_request.id)

        if current is None:
            logger.error("❌ La solicitud ha desaparecido del estado")
            return 1

        if current.status == "booked":
            logger.info(f"🎉 Vigilancia completada: {current.id}")
            return 0

        now = get_local_now(config)
        if now >= watch_until:
            current.status = "cancelled"
            current.last_result = (
                f"Vigilancia local cancelada tras {args.duration_minutes} minutos"
            )
            save_requests(requests)
            logger.warning(f"⏹️ Se cancela la vigilancia local: {current.id}")
            return 1

        logger.info(
            f"😴 Esperando {args.interval_seconds}s antes del siguiente chequeo..."
        )
        await asyncio.sleep(args.interval_seconds)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
