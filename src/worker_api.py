"""
VGymRobot - Worker API Client
Cliente HTTP mínimo para que el worker de GitHub lea y actualice solicitudes
multiusuario almacenadas en el backend.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class RemoteMember:
    gym_username: str
    gym_password: str
    telegram_chat_id: str


@dataclass
class RemoteBookingRequest:
    id: str
    club: str
    day: str
    time: str
    class_name: str
    watch_until: str
    target_date: Optional[str]
    interval_seconds: int
    attempts: int
    status: str
    member: RemoteMember


class WorkerAPIError(RuntimeError):
    """Error genérico al hablar con el backend del worker."""


def _base_url() -> str:
    value = os.getenv("WORKER_API_BASE_URL", "").strip().rstrip("/")
    if not value:
        raise WorkerAPIError("WORKER_API_BASE_URL no está configurado")
    return value


def _worker_secret() -> str:
    value = os.getenv("WORKER_SHARED_SECRET", "").strip()
    if not value:
        raise WorkerAPIError("WORKER_SHARED_SECRET no está configurado")
    return value


def _request(payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_base_url()}/worker-api"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-worker-secret": _worker_secret(),
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise WorkerAPIError(
            f"Backend devolvió HTTP {exc.code}: {details or exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise WorkerAPIError(f"No se pudo conectar con el backend: {exc}") from exc


def fetch_remote_request(request_id: str) -> RemoteBookingRequest:
    payload = _request({"action": "fetch", "request_id": request_id})
    request = payload.get("request")
    if not request:
        raise WorkerAPIError("Respuesta inválida del backend: falta 'request'")

    member = request.get("member") or {}
    return RemoteBookingRequest(
        id=request["id"],
        club=request["club"],
        day=request["day"],
        time=request["time"],
        class_name=request["class_name"],
        watch_until=request["watch_until"],
        target_date=request.get("target_date"),
        interval_seconds=int(request.get("interval_seconds", 120)),
        attempts=int(request.get("attempts", 0)),
        status=request.get("status", "pending"),
        member=RemoteMember(
            gym_username=member["gym_username"],
            gym_password=member["gym_password"],
            telegram_chat_id=str(member.get("telegram_chat_id", "")),
        ),
    )


def update_remote_request(
    request_id: str,
    *,
    status: Optional[str] = None,
    attempts: Optional[int] = None,
    last_result: Optional[str] = None,
    last_checked_at: Optional[str] = None,
    booked_at: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": "update",
        "request_id": request_id,
    }

    if status is not None:
        payload["status"] = status
    if attempts is not None:
        payload["attempts"] = attempts
    if last_result is not None:
        payload["last_result"] = last_result
    if last_checked_at is not None:
        payload["last_checked_at"] = last_checked_at
    if booked_at is not None:
        payload["booked_at"] = booked_at

    return _request(payload)
