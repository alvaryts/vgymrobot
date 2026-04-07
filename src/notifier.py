"""
VGymRobot - Notification Module
Envía notificaciones cuando se consigue una reserva.
MVP: Solo logging. Futuro: ntfy.sh push notifications.
"""

import os
from typing import Optional

from src.logger import setup_logger

logger = setup_logger()


async def notify_success(class_name: str, time: str, day: str) -> None:
    """
    Notifica una reserva exitosa.

    En el MVP solo logea. En futuras versiones enviará push via ntfy.sh.

    Args:
        class_name: Nombre de la clase reservada
        time: Hora de la clase
        day: Día de la clase
    """
    message = f"🎉 ¡RESERVA CONFIRMADA! {class_name} - {day} a las {time}"
    logger.info(message)

    # Futuro: push notification via ntfy.sh
    ntfy_topic = os.getenv("NTFY_TOPIC")
    if ntfy_topic:
        await _send_ntfy_push(ntfy_topic, message)


async def notify_failure(reason: str) -> None:
    """
    Notifica que no se pudo completar la reserva.

    Args:
        reason: Razón del fallo
    """
    message = f"⚠️ Reserva no completada: {reason}"
    logger.warning(message)


async def _send_ntfy_push(topic: str, message: str) -> None:
    """
    Envía push notification via ntfy.sh (gratuito, sin registro).

    Args:
        topic: Tópico ntfy.sh
        message: Mensaje a enviar
    """
    try:
        import urllib.request

        server = os.getenv("NTFY_SERVER", "https://ntfy.sh")
        url = f"{server}/{topic}"

        req = urllib.request.Request(
            url,
            data=message.encode("utf-8"),
            method="POST",
            headers={"Title": "VGymRobot", "Priority": "high", "Tags": "muscle"},
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info(f"📱 Push notification enviada a {topic}")
    except Exception as e:
        logger.warning(f"⚠️ No se pudo enviar push notification: {e}")
