"""
VGymRobot - Configuration Loader
Carga y valida preferences.yaml y credenciales desde .env
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

from src.logger import setup_logger

logger = setup_logger()

# Mapa de días español → número (lunes=0 ... domingo=6)
DAY_MAP = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "miércoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6,
}


@dataclass
class BookingTarget:
    """Representa una clase objetivo a reservar."""

    day: str
    time: str
    class_name: str
    enabled: bool = True
    target_date: Optional[str] = None

    @property
    def day_number(self) -> int:
        """Devuelve el número del día (lunes=0)."""
        return DAY_MAP.get(self.day.lower(), -1)


@dataclass
class RetryConfig:
    """Configuración de reintentos."""

    max_attempts: int = 20
    initial_delay_seconds: int = 15
    backoff_multiplier: float = 1.3
    max_delay_seconds: int = 120
    max_runtime_minutes: int = 8


@dataclass
class BookingConfig:
    """Configuración de reservas."""

    days_in_advance: int = 2
    booking_opens_at: str = "00:00"
    respect_opening_time: bool = True


@dataclass
class GymConfig:
    """Configuración del gimnasio."""

    name: str = "Vivagym"
    base_url: str = "https://gimnasios.vivagym.es"
    login_path: str = "/login"
    timezone: str = "Europe/Madrid"

    @property
    def login_url(self) -> str:
        return f"{self.base_url}{self.login_path}"


@dataclass
class Credentials:
    """Credenciales de acceso."""

    username: str = ""
    password: str = ""


@dataclass
class AppConfig:
    """Configuración completa de la aplicación."""

    gym: GymConfig = field(default_factory=GymConfig)
    credentials: Credentials = field(default_factory=Credentials)
    club: str = ""
    targets: list[BookingTarget] = field(default_factory=list)
    booking: BookingConfig = field(default_factory=BookingConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)


def with_runtime_credentials(
    config: AppConfig,
    username: str,
    password: str,
    club: Optional[str] = None,
) -> AppConfig:
    """Inyecta credenciales y club en una configuración ya cargada."""
    config.credentials = Credentials(username=username, password=password)
    if club:
        config.club = club
    return config


def get_local_now(config: AppConfig) -> datetime:
    """Devuelve la fecha/hora actual en la zona horaria configurada."""
    return datetime.now(ZoneInfo(config.gym.timezone))


def load_config(
    preferences_path: Optional[str] = None,
    env_path: Optional[str] = None,
    require_credentials: bool = True,
) -> AppConfig:
    """
    Carga la configuración completa desde preferences.yaml y .env

    Args:
        preferences_path: Ruta al archivo de preferencias YAML
        env_path: Ruta al archivo .env
        require_credentials: Si False, permite cargar config sin credenciales

    Returns:
        AppConfig con toda la configuración cargada y validada
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Cargar .env
    if env_path is None:
        env_path = os.path.join(project_root, ".env")
    load_dotenv(env_path)

    # Cargar preferences.yaml
    if preferences_path is None:
        preferences_path = os.path.join(project_root, "preferences.yaml")

    if not os.path.exists(preferences_path):
        raise FileNotFoundError(
            f"No se encontró el archivo de preferencias: {preferences_path}"
        )

    with open(preferences_path, "r", encoding="utf-8") as f:
        prefs = yaml.safe_load(f)

    # Construir configuración
    config = AppConfig()

    # Gym
    gym_data = prefs.get("gym", {})
    config.gym = GymConfig(
        name=gym_data.get("name", "Vivagym"),
        base_url=gym_data.get("base_url", "https://gimnasios.vivagym.es"),
        login_path=gym_data.get("login_path", "/login"),
        timezone=gym_data.get("timezone", "Europe/Madrid"),
    )

    # Credenciales desde env
    username = os.getenv("GYM_USERNAME", "")
    password = os.getenv("GYM_PASSWORD", "")
    if require_credentials and (not username or not password):
        raise ValueError(
            "Las credenciales GYM_USERNAME y GYM_PASSWORD deben estar definidas en .env"
        )
    config.credentials = Credentials(username=username, password=password)
    config.club = prefs.get("club", "")

    # Targets
    targets_data = prefs.get("targets", [])
    config.targets = [
        BookingTarget(
            day=t["day"],
            time=t["time"],
            class_name=t["class_name"],
            enabled=t.get("enabled", True),
            target_date=t.get("target_date"),
        )
        for t in targets_data
    ]

    # Booking config
    booking_data = prefs.get("booking", {})
    config.booking = BookingConfig(
        days_in_advance=booking_data.get("days_in_advance", 2),
        booking_opens_at=booking_data.get("booking_opens_at", "00:00"),
        respect_opening_time=booking_data.get("respect_opening_time", True),
    )

    # Retry config
    retry_data = prefs.get("retry", {})
    config.retry = RetryConfig(
        max_attempts=retry_data.get("max_attempts", 20),
        initial_delay_seconds=retry_data.get("initial_delay_seconds", 15),
        backoff_multiplier=retry_data.get("backoff_multiplier", 1.3),
        max_delay_seconds=retry_data.get("max_delay_seconds", 120),
        max_runtime_minutes=retry_data.get("max_runtime_minutes", 8),
    )

    # Validación
    active_targets = [t for t in config.targets if t.enabled]
    if not active_targets:
        logger.warning("⚠️  No hay targets activos en preferences.yaml")

    for t in active_targets:
        if t.day_number == -1:
            raise ValueError(f"Día no válido: '{t.day}'. Usa: {list(DAY_MAP.keys())}")

    logger.info(f"✅ Configuración cargada: {len(active_targets)} target(s) activo(s)")
    for t in active_targets:
        logger.info(f"   📌 {t.day.capitalize()} {t.time} - {t.class_name}")

    return config
