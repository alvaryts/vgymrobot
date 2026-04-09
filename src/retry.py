"""
VGymRobot - Retry Manager
Lógica de reintentos con backoff exponencial y control de tiempo total.
"""

import asyncio
import time
from typing import Callable, Any, Optional

from src.config import RetryConfig
from src.logger import setup_logger

logger = setup_logger()


class RetryManager:
    """
    Gestor de reintentos con backoff exponencial.

    Controla:
    - Número máximo de intentos
    - Delay creciente entre intentos
    - Tiempo máximo total de ejecución
    """

    def __init__(self, config: RetryConfig):
        self.config = config
        self.attempt = 0
        self.start_time: Optional[float] = None

    @property
    def current_delay(self) -> float:
        """Calcula el delay actual con backoff exponencial."""
        retry_index = max(self.attempt - 1, 0)
        delay = self.config.initial_delay_seconds * (
            self.config.backoff_multiplier ** retry_index
        )
        return min(delay, self.config.max_delay_seconds)

    @property
    def elapsed_minutes(self) -> float:
        """Minutos transcurridos desde el inicio."""
        if self.start_time is None:
            return 0
        return (time.time() - self.start_time) / 60

    @property
    def time_remaining(self) -> bool:
        """Comprueba si queda tiempo dentro del límite."""
        return self.elapsed_minutes < self.config.max_runtime_minutes

    @property
    def remaining_seconds(self) -> float:
        """Segundos restantes antes de agotar el tiempo máximo."""
        return max(0.0, self.config.max_runtime_minutes * 60 - (self.elapsed_minutes * 60))

    @property
    def attempts_remaining(self) -> bool:
        """Comprueba si quedan intentos."""
        return self.attempt < self.config.max_attempts

    def can_retry(self) -> bool:
        """Comprueba si se puede hacer otro intento."""
        return self.attempts_remaining and self.time_remaining

    async def execute_with_retry(
        self, operation: Callable, *args: Any, **kwargs: Any
    ) -> dict:
        """
        Ejecuta una operación con reintentos automáticos.

        Args:
            operation: Función async a ejecutar
            *args: Argumentos para la operación
            **kwargs: Argumentos con nombre para la operación

        Returns:
            dict con:
                - success: bool
                - result: valor devuelto por la operación (si éxito)
                - attempts: número de intentos realizados
                - elapsed_minutes: tiempo total transcurrido
        """
        self.start_time = time.time()
        self.attempt = 0
        last_result = None

        while self.can_retry():
            self.attempt += 1
            logger.info(
                f"🔄 Intento {self.attempt}/{self.config.max_attempts} "
                f"(⏱️ {self.elapsed_minutes:.1f}min / {self.config.max_runtime_minutes}min)"
            )

            try:
                result = await operation(*args, **kwargs)
                last_result = result

                if result.get("booked", False):
                    logger.info(
                        f"🎉 ¡ÉXITO en el intento {self.attempt}! "
                        f"Tiempo total: {self.elapsed_minutes:.1f}min"
                    )
                    return {
                        "success": True,
                        "result": result,
                        "attempts": self.attempt,
                        "elapsed_minutes": self.elapsed_minutes,
                    }

                reason = result.get("reason", "Sin plazas disponibles")
                logger.info(f"   ℹ️  {reason}")

            except Exception as e:
                logger.error(f"   ❌ Error en intento {self.attempt}: {e}")
                last_result = {"booked": False, "reason": str(e)}

            # ¿Queda margen para otro intento?
            if not self.can_retry():
                break

            # Esperar con backoff
            delay = self.current_delay
            if delay >= self.remaining_seconds:
                logger.info(
                    "   ⏱️ No queda margen suficiente para esperar otro ciclo completo"
                )
                break
            logger.info(f"   ⏳ Esperando {delay:.0f}s antes del siguiente intento...")
            await asyncio.sleep(delay)

        logger.warning(
            f"⚠️  Reintentos agotados después de {self.attempt} intentos "
            f"({self.elapsed_minutes:.1f}min)"
        )
        return {
            "success": False,
            "result": last_result,
            "attempts": self.attempt,
            "elapsed_minutes": self.elapsed_minutes,
        }
