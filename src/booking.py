"""
VGymRobot - Booking Engine
Motor principal de reserva usando Playwright.
Navega por la web de Vivagym para encontrar y reservar clases.

Selectores obtenidos por exploración directa de la SPA de Vivagym.
Usa atributos data-cy que son estables (usados para testing por Vivagym).
"""

import os
import re
from datetime import datetime, timedelta, time as dt_time

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from src.config import AppConfig, BookingTarget, get_local_now
from src.logger import setup_logger

logger = setup_logger()

# ============================================
# Selectores data-cy de Vivagym
# ============================================
SEL = {
    # Filtros
    "filters": '[data-cy="booking-filters"]',
    "filter_centers": '[data-cy="booking-filter-centers"]',
    "filter_activities": '[data-cy="booking-filter-activities"]',
    "filter_clear": '[data-cy="booking-filter-clear"]',

    # Swiper de días
    "swiper": '[data-cy="booking-swiper"]',
    "swiper_prev": '[data-cy="booking-swiper-prev"]',
    "swiper_next": '[data-cy="booking-swiper-next"]',
    "swiper_day": '[data-cy="booking-swiper-date-{date}"]',  # YYYY-MM-DD
    "swiper_selected": '[data-cy="booking-swiper-selected"]',

    # Entradas de clases (cada una es un participation-entry-0-{id})
    "class_entries": '[data-cy^="participation-entry"]',
    "start_time": '[data-cy="start-time"]',
    "duration_time": '[data-cy="duration-time"]',
    "booking_name": '[data-cy="booking-name"]',
    "booking_state": '[data-cy="booking-state"]',
    "center_name": '[data-cy="center-name"]',
    "expand_button": '[data-cy="expand-button"]',
    "entry_chevron": '[data-cy="entry-chevron"]',
    "expanded_description": '[data-cy="expanded-description"]',
    "book_button": '[data-cy="book-button"]',

    # Loading indicator
    "loading": "text=Cargando",
    "no_activities": "text=No hay actividades para el filtro seleccionado",
}

# Textos de estado
STATE_FULL = "clase llena"
STATE_AVAILABLE = "disponibles"


def parse_target_time(value: str) -> dt_time | None:
    """Parsea una hora tipo 7:00 o 19:30."""
    normalized = normalize_time_label(value)
    match = re.match(r"^(\d{1,2}):(\d{2})$", normalized)
    if not match:
        return None

    hour, minute = match.groups()
    return dt_time(hour=int(hour), minute=int(minute))


def next_target_occurrence(target: BookingTarget, config: AppConfig) -> datetime:
    """
    Devuelve la próxima ocurrencia real del target.

    Si la clase es hoy pero su hora ya ha pasado, salta a la semana siguiente.
    """
    now = get_local_now(config)
    days_ahead = (target.day_number - now.weekday()) % 7
    occurrence = now + timedelta(days=days_ahead)

    class_time = parse_target_time(target.time)
    if class_time is not None:
        occurrence = occurrence.replace(
            hour=class_time.hour,
            minute=class_time.minute,
            second=0,
            microsecond=0,
        )

    if occurrence < now:
        occurrence += timedelta(days=7)

    return occurrence


def resolve_target_date(target: BookingTarget, config: AppConfig) -> datetime:
    """
    Resuelve la fecha concreta que corresponde al próximo target vigilable.
    """
    if target.target_date:
        parsed_date = datetime.fromisoformat(target.target_date)
        class_time = parse_target_time(target.time)
        if class_time is None:
            return parsed_date

        return parsed_date.replace(
            hour=class_time.hour,
            minute=class_time.minute,
            second=0,
            microsecond=0,
            tzinfo=get_local_now(config).tzinfo,
        )

    return next_target_occurrence(target, config)


def normalize_time_label(value: str) -> str:
    """Normaliza horas como 07:00 y 7:00 al mismo formato."""
    match = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", value or "")
    if not match:
        return (value or "").strip()
    hour, minute = match.groups()
    return f"{int(hour)}:{minute}"


def availability_count(state_text: str) -> int | None:
    """
    Devuelve el número de plazas disponibles si el estado lo indica.

    Returns:
        0 si la clase está llena, un entero positivo si hay plazas o None si el
        texto no sigue el patrón esperado.
    """
    normalized = " ".join((state_text or "").lower().split())

    if STATE_FULL in normalized:
        return 0

    match = re.search(r"(\d+)\s+disponible", normalized)
    if match:
        return int(match.group(1))

    return None


def get_target_for_today(config: AppConfig) -> list[BookingTarget]:
    """
    Filtra los targets activos cuya próxima ocurrencia cae dentro de la
    ventana de vigilancia.

    Ejemplo: con `days_in_advance: 1`, una clase del miércoles a las 20:00
    empieza a vigilarse el martes a las 20:00. Así el bot sirve tanto para
    aperturas justas como para cazar cancelaciones hasta la hora de la clase.
    """
    now = get_local_now(config)
    window = timedelta(days=config.booking.days_in_advance)
    matching_targets = []

    for target in config.targets:
        if not target.enabled:
            continue

        occurrence = next_target_occurrence(target, config)
        time_until_class = occurrence - now

        if timedelta(0) <= time_until_class <= window:
            matching_targets.append(target)

    if matching_targets:
        logger.info(
            "📅 Targets dentro de la ventana de vigilancia: "
            f"{len(matching_targets)}"
        )
        for target in matching_targets:
            occurrence = next_target_occurrence(target, config)
            hours_until = (occurrence - now).total_seconds() / 3600
            logger.info(
                f"   ⏰ {target.class_name} - "
                f"{occurrence.strftime('%A %d/%m %H:%M')} "
                f"(en {hours_until:.1f}h)"
            )
    else:
        logger.info(
            "📅 No hay clases objetivo dentro de la ventana actual "
            f"de {config.booking.days_in_advance} día(s)"
        )

    return matching_targets


async def navigate_to_booking(page: Page, config: AppConfig) -> bool:
    """
    Navega a la sección de reservas desde el dashboard.
    Usa el botón 'Nueva reserva' o navega directamente a /booking.
    """
    logger.info("📋 Navegando a la sección de reservas...")

    try:
        current_url = page.url

        # Si ya estamos en /booking, solo recargar
        if "/booking" in current_url:
            logger.debug("   Ya estamos en /booking, recargando...")
            await page.reload(wait_until="domcontentloaded", timeout=15000)
        else:
            # Intentar click en 'Nueva reserva' desde el dashboard
            nueva_reserva = page.locator("text=Nueva reserva").first
            if await nueva_reserva.count() > 0:
                await nueva_reserva.click()
            else:
                # Intentar link 'Reservas' en la navegación
                reservas_link = page.locator('a[href="/booking"]').first
                if await reservas_link.count() > 0:
                    await reservas_link.click()
                else:
                    await page.goto(
                        f"{config.gym.base_url}/booking",
                        wait_until="domcontentloaded",
                        timeout=15000,
                    )

        # Esperar a que desaparezca el spinner "Cargando..."
        try:
            await page.wait_for_selector(
                SEL["loading"], state="hidden", timeout=20000
            )
        except PlaywrightTimeout:
            logger.warning("⚠️ Timeout esperando desaparición del spinner")

        await page.wait_for_timeout(2000)

        # Verificar que estamos en /booking
        if "/booking" in page.url:
            if config.club:
                selected_club = (
                    await page.locator(SEL["filter_centers"]).inner_text()
                ).strip()
                if config.club.lower() not in selected_club.lower():
                    logger.warning(
                        "⚠️ El club seleccionado en la web no coincide con "
                        f"preferences.yaml: '{selected_club}'"
                    )
            logger.info(f"   ✅ Sección de reservas cargada: {page.url}")
            return True

        logger.error(f"❌ No estamos en /booking, URL actual: {page.url}")
        return False

    except Exception as e:
        logger.error(f"❌ Error navegando a reservas: {e}")
        return False


async def select_day(page: Page, target_date: datetime) -> bool:
    """
    Selecciona un día específico en el swiper de fechas.

    Args:
        page: Página de Playwright
        target_date: Fecha a seleccionar (datetime)

    Returns:
        True si se seleccionó el día correctamente
    """
    date_str = target_date.strftime("%Y-%m-%d")
    day_selector = SEL["swiper_day"].format(date=date_str)

    logger.info(f"📅 Seleccionando día: {date_str}")

    try:
        day_element = page.locator(day_selector)

        if await day_element.count() == 0:
            logger.error(f"❌ Día {date_str} no encontrado en el swiper")
            return False

        # Scroll into view y click
        await day_element.scroll_into_view_if_needed()
        await day_element.click()

        # Esperar recarga de clases
        await page.wait_for_timeout(2000)
        try:
            await page.wait_for_selector(
                SEL["loading"], state="hidden", timeout=15000
            )
        except PlaywrightTimeout:
            pass

        await page.wait_for_timeout(1000)

        logger.info(f"   ✅ Día {date_str} seleccionado")
        return True

    except Exception as e:
        logger.error(f"❌ Error seleccionando día {date_str}: {e}")
        return False


async def find_and_book_class(
    page: Page, target: BookingTarget, config: AppConfig
) -> dict:
    """
    Busca una clase específica en la página de reservas e intenta reservarla.

    Flujo:
    1. Seleccionar el día correcto en el swiper
    2. Buscar las entradas de clases (participation-entry)
    3. Encontrar la que coincida en nombre y hora
    4. Verificar disponibilidad
    5. Click en la entrada para expandirla
    6. Buscar y click en botón de reserva

    Returns:
        dict con booked: bool y reason: str
    """
    logger.info(
        f"🔍 Buscando clase: {target.class_name} a las {target.time} ({target.day})"
    )

    try:
        # 1. Seleccionar el día
        target_date = resolve_target_date(target, config)
        day_selected = await select_day(page, target_date)

        if not day_selected:
            return {
                "booked": False,
                "reason": (
                    "No se pudo seleccionar el día "
                    f"{target_date.strftime('%Y-%m-%d')} en el swiper"
                ),
            }

        # 2. Comprobar si hay actividades
        no_activities = page.locator(SEL["no_activities"])
        if await no_activities.count() > 0 and await no_activities.is_visible():
            return {
                "booked": False,
                "reason": "No hay actividades para el filtro seleccionado",
            }

        # 3. Obtener todas las entradas de clases
        entries = page.locator(SEL["class_entries"])
        entry_count = await entries.count()
        logger.info(f"   📋 {entry_count} clases encontradas")

        if entry_count == 0:
            return {
                "booked": False,
                "reason": "No se encontraron clases en la página",
            }

        # 4. Buscar la clase que coincida
        target_time = normalize_time_label(target.time)
        last_match_reason = ""

        for i in range(entry_count):
            entry = entries.nth(i)

            # Obtener nombre y hora de la clase
            name_el = entry.locator(SEL["booking_name"])
            time_el = entry.locator(SEL["start_time"])
            state_el = entry.locator(SEL["booking_state"])

            if await name_el.count() == 0 or await time_el.count() == 0:
                continue

            class_name = (await name_el.text_content() or "").strip()
            class_time = (await time_el.text_content() or "").strip()
            class_state = (await state_el.text_content() or "").strip().lower()
            seats = availability_count(class_state)

            # Comprobar coincidencia (case-insensitive, parcial)
            name_match = target.class_name.lower() in class_name.lower()
            time_match = target_time == normalize_time_label(class_time)

            if not (name_match and time_match):
                continue

            logger.info(
                f"   ✅ Clase encontrada: {class_name} a las {class_time} → {class_state}"
            )

            # 5. Verificar disponibilidad
            if seats == 0:
                last_match_reason = (
                    f"Clase '{class_name}' a las {class_time} → CLASE LLENA"
                )
                continue

            if seats is None:
                logger.warning(
                    f"   ⚠️ Estado inesperado: '{class_state}'"
                )

            # 6. Expandir la entrada (click en el chevron/expand)
            expand = entry.locator(SEL["expand_button"]).first
            if await entry.locator(SEL["expanded_description"]).count() == 0:
                if await expand.count() > 0:
                    await expand.click()
                    await page.wait_for_timeout(1500)
                    logger.info("   📂 Entrada expandida")
                else:
                    await entry.click()
                    await page.wait_for_timeout(1500)

            # Capturar screenshot post-expand
            await take_debug_screenshot(page, "post_expand")

            # 7. Buscar botón de reserva
            book_button = entry.locator(SEL["book_button"]).first
            if await book_button.count() == 0:
                book_button = entry.locator("button").filter(
                    has_text=re.compile(
                        r"reserva|reservar|book|inscribir|apuntar|confirmar|unirse",
                        re.IGNORECASE,
                    )
                ).first

            page_level_fallback = page.locator("button").filter(
                has_text=re.compile(
                    r"reserva|reservar|book|inscribir|apuntar|confirmar|unirse",
                    re.IGNORECASE,
                )
            )

            if await book_button.count() > 0:
                logger.info("   🎯 ¡Botón de reserva encontrado! Haciendo click...")
                await book_button.click()
            elif await page_level_fallback.count() > 0:
                logger.warning(
                    "   ⚠️ No apareció un botón scoped en la entrada; "
                    "usando fallback global"
                )
                await page_level_fallback.first.click()
            else:
                book_link = entry.locator("a").filter(
                    has_text=re.compile(
                        r"reservar|book|inscribir|apuntar|confirmar",
                        re.IGNORECASE,
                    )
                )
                if await book_link.count() > 0:
                    await book_link.first.click()
                else:
                    await take_debug_screenshot(page, "no_book_button")
                    return {
                        "booked": False,
                        "reason": "Clase disponible pero no se encontró botón de reserva",
                    }

            # 8. Esperar resultado
            await page.wait_for_timeout(3000)
            await take_debug_screenshot(page, "post_book_click")

            # Verificar si hay modal de confirmación
            confirm_button = page.locator("button").filter(
                has_text=re.compile(
                    r"confirmar|confirm|aceptar|sí|si|ok|yes",
                    re.IGNORECASE,
                )
            )

            if await confirm_button.count() > 0:
                logger.info("   ✅ Modal de confirmación detectado, confirmando...")
                await confirm_button.first.click()
                await page.wait_for_timeout(3000)

            # 9. Verificar resultado
            await take_debug_screenshot(page, "post_confirm")

            # Comprobar estado actualizado
            updated_state = entry.locator(SEL["booking_state"]).filter(
                has_text=re.compile(
                    r"reservado|inscrito|confirmad|booked",
                    re.IGNORECASE,
                )
            )
            if await updated_state.count() > 0:
                return {
                    "booked": True,
                    "reason": f"✅ ¡Reserva confirmada! {class_name} a las {class_time}",
                }

            # Buscar mensajes de éxito genéricos
            success_msg = page.locator(
                "text=/reserva.*confirmada|reserva.*exitosa|reservado|booked|inscrito|éxito|success/i"
            )
            if await success_msg.count() > 0:
                return {
                    "booked": True,
                    "reason": f"✅ ¡Reserva confirmada! {class_name} a las {class_time}",
                }

            # Si el estado cambió a algo que no sea "disponibles" ni "clase llena"
            # podría ser que la reserva se hizo
            new_state_el = entry.locator(SEL["booking_state"])
            if await new_state_el.count() > 0:
                new_state = (await new_state_el.text_content() or "").strip().lower()
                if new_state != class_state and STATE_FULL not in new_state:
                    return {
                        "booked": True,
                        "reason": f"✅ Estado cambió a: '{new_state}' — probablemente reservado",
                    }

            post_click_buttons = entry.locator("button").filter(
                has_text=re.compile(r"cancelar|anular|borrar", re.IGNORECASE)
            )
            if await post_click_buttons.count() > 0:
                return {
                    "booked": True,
                    "reason": (
                        f"✅ Detectado botón de cancelación para {class_name} "
                        f"a las {class_time}"
                    ),
                }

            return {
                "booked": False,
                "reason": "Se hizo click en reservar pero no se pudo confirmar el resultado",
            }

        # Si llegamos aquí, no encontramos la clase
        if last_match_reason:
            return {
                "booked": False,
                "reason": last_match_reason,
            }

        return {
            "booked": False,
            "reason": f"Clase '{target.class_name}' a las {target.time} no encontrada en las {entry_count} entradas",
        }

    except PlaywrightTimeout as e:
        return {"booked": False, "reason": f"Timeout buscando/reservando clase: {e}"}
    except Exception as e:
        return {"booked": False, "reason": f"Error: {e}"}


async def take_debug_screenshot(page: Page, name: str) -> None:
    """Captura screenshot para debugging."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    screenshots_dir = os.path.join(project_root, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(screenshots_dir, f"{name}_{timestamp}.png")
    try:
        await page.screenshot(path=path, full_page=True)
        logger.debug(f"📸 Screenshot guardado: {path}")
    except Exception as e:
        logger.warning(f"⚠️ No se pudo guardar screenshot: {e}")
