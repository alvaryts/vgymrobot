"""
VGymRobot - Logging Configuration
Configura logging rotativos para trazabilidad completa.
"""

import logging
import os
import sys
from datetime import datetime


def setup_logger(name: str = "vgymrobot", log_dir: str = "logs") -> logging.Logger:
    """
    Configura y devuelve un logger con salida a consola y archivo.

    Args:
        name: Nombre del logger
        log_dir: Directorio donde guardar los logs

    Returns:
        Logger configurado
    """
    logger = logging.getLogger(name)

    # Evitar duplicar handlers si ya está configurado
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Formato detallado
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Handler de consola (INFO+)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Handler de archivo (DEBUG+)
    # Determinar la raíz del proyecto
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_path = os.path.join(project_root, log_dir)
    os.makedirs(log_path, exist_ok=True)

    log_file = os.path.join(
        log_path, f"vgymrobot_{datetime.now().strftime('%Y%m%d')}.log"
    )
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
