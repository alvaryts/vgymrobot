"""
VGymRobot - Booking Requests State
Gestiona solicitudes manuales persistentes para reservar clases.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Optional

from src.booking import next_target_occurrence
from src.config import AppConfig, BookingTarget, get_local_now
from src.logger import setup_logger

logger = setup_logger()


@dataclass
class BookingRequest:
    """Solicitud persistente de reserva."""

    id: str
    club: str
    day: str
    time: str
    class_name: str
    target_date: str
    created_at: str
    watch_until: str
    status: str = "pending"
    attempts: int = 0
    last_checked_at: Optional[str] = None
    last_result: Optional[str] = None
    booked_at: Optional[str] = None

    def to_target(self) -> BookingTarget:
        """Convierte la solicitud en un target ejecutable."""
        return BookingTarget(
            day=self.day,
            time=self.time,
            class_name=self.class_name,
            enabled=True,
            target_date=self.target_date,
        )


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def requests_path(path: Optional[str] = None) -> str:
    """Devuelve la ruta al archivo de solicitudes."""
    if path:
        return path
    return os.path.join(_project_root(), "state", "requests.json")


def load_requests(path: Optional[str] = None) -> list[BookingRequest]:
    """Carga todas las solicitudes persistidas."""
    file_path = requests_path(path)
    if not os.path.exists(file_path):
        return []

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return [BookingRequest(**item) for item in data.get("requests", [])]


def save_requests(requests: list[BookingRequest], path: Optional[str] = None) -> None:
    """Guarda las solicitudes persistidas."""
    file_path = requests_path(path)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    payload = {"requests": [asdict(request) for request in requests]}
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _slugify(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return clean or "request"


def _parse_watch_until(value: str, config: AppConfig) -> datetime:
    """
    Parsea watch_until aceptando ISO o YYYY-MM-DD HH:MM.
    """
    for parser in (datetime.fromisoformat,):
        try:
            parsed = parser(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=get_local_now(config).tzinfo)
            return parsed
        except ValueError:
            continue

    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M")
        return parsed.replace(tzinfo=get_local_now(config).tzinfo)
    except ValueError as exc:
        raise ValueError(
            "watch_until debe ser ISO o YYYY-MM-DD HH:MM"
        ) from exc


def build_request(
    config: AppConfig,
    day: str,
    time: str,
    class_name: str,
    club: Optional[str] = None,
    watch_until: Optional[str] = None,
    stop_minutes_before_class: int = 5,
) -> BookingRequest:
    """Construye una nueva solicitud a partir de parámetros simples."""
    target = BookingTarget(day=day, time=time, class_name=class_name, enabled=True)
    occurrence = next_target_occurrence(target, config)

    if watch_until:
        watch_until_dt = _parse_watch_until(watch_until, config)
    else:
        watch_until_dt = occurrence - timedelta(minutes=stop_minutes_before_class)

    created_at = get_local_now(config)
    request_id = (
        f"{occurrence.strftime('%Y%m%d')}-"
        f"{normalize_day(day)}-{time.replace(':', '')}-"
        f"{_slugify(class_name)}"
    )

    return BookingRequest(
        id=request_id,
        club=club or config.club,
        day=day,
        time=time,
        class_name=class_name,
        target_date=occurrence.date().isoformat(),
        created_at=created_at.isoformat(),
        watch_until=watch_until_dt.isoformat(),
    )


def normalize_day(value: str) -> str:
    """Normaliza el día para usarlo en ids."""
    return (
        value.lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )


def upsert_request(
    requests: list[BookingRequest], new_request: BookingRequest
) -> tuple[list[BookingRequest], BookingRequest, bool]:
    """
    Inserta la solicitud o reactiva una previa con el mismo id.

    Returns:
        (lista_actualizada, solicitud_existente_o_nueva, created)
    """
    for request in requests:
        if request.id != new_request.id:
            continue

        if request.status == "pending":
            return requests, request, False

        request.club = new_request.club
        request.day = new_request.day
        request.time = new_request.time
        request.class_name = new_request.class_name
        request.target_date = new_request.target_date
        request.created_at = new_request.created_at
        request.watch_until = new_request.watch_until
        request.status = "pending"
        request.attempts = 0
        request.last_checked_at = None
        request.last_result = None
        request.booked_at = None
        return requests, request, False

    requests.append(new_request)
    return requests, new_request, True


def expire_overdue_requests(
    requests: list[BookingRequest], config: AppConfig
) -> list[BookingRequest]:
    """Marca como expiradas las solicitudes cuyo watch_until ya pasó."""
    now = get_local_now(config)
    for request in requests:
        if request.status != "pending":
            continue
        if datetime.fromisoformat(request.watch_until) <= now:
            request.status = "expired"
            request.last_result = "Ventana de vigilancia expirada"
    return requests


def active_requests(
    requests: list[BookingRequest], config: AppConfig
) -> list[BookingRequest]:
    """Devuelve solo las solicitudes pendientes y vigentes."""
    now = get_local_now(config)
    result = []
    for request in requests:
        if request.status != "pending":
            continue
        if datetime.fromisoformat(request.watch_until) <= now:
            continue
        result.append(request)
    return result


def get_request_by_id(
    requests: list[BookingRequest], request_id: str
) -> BookingRequest | None:
    """Devuelve una solicitud por id si existe."""
    for request in requests:
        if request.id == request_id:
            return request
    return None
