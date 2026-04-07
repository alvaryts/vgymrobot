"""
VGymRobot - Create Booking Request
Crea una solicitud manual persistente para que el worker la procese.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config
from src.logger import setup_logger
from src.request_state import build_request, load_requests, save_requests, upsert_request

logger = setup_logger()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crear solicitud de reserva")
    parser.add_argument("--day", required=True, help="Día: lunes..domingo")
    parser.add_argument("--time", required=True, help="Hora de la clase, ej. 19:00")
    parser.add_argument("--class-name", required=True, help="Nombre de la clase")
    parser.add_argument("--club", help="Club a usar; por defecto el configurado")
    parser.add_argument(
        "--watch-until",
        help="Límite de vigilancia (ISO o YYYY-MM-DD HH:MM)",
    )
    return parser.parse_args()


def write_output(name: str, value: str) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return

    with open(output_path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def main() -> int:
    args = parse_args()
    config = load_config(require_credentials=False)
    requests = load_requests()

    request = build_request(
        config=config,
        day=args.day,
        time=args.time,
        class_name=args.class_name,
        club=args.club,
        watch_until=args.watch_until,
    )

    requests, saved_request, created = upsert_request(requests, request)
    save_requests(requests)

    logger.info(
        f"{'✅' if created else 'ℹ️'} Solicitud "
        f"{'creada' if created else 'ya existente'}: {saved_request.id}"
    )
    logger.info(
        f"   🎯 {saved_request.class_name} - {saved_request.day} {saved_request.time}"
    )
    logger.info(f"   🏁 Vigilar hasta: {saved_request.watch_until}")

    write_output("request_id", saved_request.id)
    write_output("created", str(created).lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
