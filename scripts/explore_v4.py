"""
Script de exploración v4: selecciona un día en viewport y captura las clases.
"""

import asyncio
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


async def explore():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="es-ES",
            timezone_id="Europe/Madrid",
        )
        page = await context.new_page()

        # ===== LOGIN =====
        print("🔐 Login...")
        await page.goto("https://gimnasios.vivagym.es/login", wait_until="networkidle", timeout=30000)
        await page.wait_for_selector("#email", state="visible", timeout=15000)
        await page.locator("#email").fill(os.getenv("GYM_USERNAME", ""))
        await page.locator("#password").fill(os.getenv("GYM_PASSWORD", ""))
        await page.locator('button[type="submit"]').click()
        await page.wait_for_selector("text=Bienvenido", timeout=15000)
        print("✅ Login OK")

        # ===== NAVEGAR A RESERVAS =====
        await page.locator("text=Nueva reserva").first.click()
        try:
            await page.wait_for_selector("text=Cargando", state="hidden", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)

        # ===== EXPLORAR DÍAS DEL SWIPER =====
        print("\n📅 Explorando días del swiper...")
        
        # Usar el patrón data-cy descubierto
        all_days = await page.evaluate("""() => {
            const days = document.querySelectorAll('[data-cy^="booking-swiper-date"]');
            return Array.from(days).map(d => ({
                dataCy: d.getAttribute('data-cy'),
                text: d.innerText?.trim(),
                isVisible: d.offsetParent !== null,
                rect: d.getBoundingClientRect(),
                classes: d.className,
            }));
        }""")
        
        print(f"   Total días: {len(all_days)}")
        for d in all_days:
            viewport = d['rect']['x'] >= 0 and d['rect']['x'] < 1280
            print(f"   {'👁️' if viewport else '  '} {d['dataCy']} → '{d['text']}' x={d['rect']['x']:.0f}")

        # ===== CLICK EN MIÉRCOLES 8 ABR (en viewport) =====
        target_day = page.locator('[data-cy="booking-swiper-date-2026-04-08"]')
        if await target_day.count() > 0:
            print("\n✅ Seleccionando miércoles 8 abr...")
            await target_day.scroll_into_view_if_needed()
            await target_day.click()
        else:
            # Click en cualquier día visible futuro
            print("\n⚠️ miércoles 8 abr no encontrado, buscando día visible...")
            tomorrow_sel = page.locator('[data-cy="booking-swiper-date-2026-04-09"]')
            if await tomorrow_sel.count() > 0:
                await tomorrow_sel.scroll_into_view_if_needed()
                await tomorrow_sel.click()
            else:
                # Cualquier día visible
                visible_days = [d for d in all_days if d['rect']['x'] >= 0 and d['rect']['x'] < 1200 and '2026-04-0' in d['dataCy']]
                if visible_days:
                    day_sel = visible_days[-1]  # último día visible
                    print(f"   Seleccionando: {day_sel['dataCy']}")
                    await page.locator(f'[data-cy="{day_sel["dataCy"]}"]').click()
        
        # Esperar carga
        await page.wait_for_timeout(5000)
        try:
            await page.wait_for_selector("text=Cargando", state="hidden", timeout=10000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)

        await page.screenshot(path=f"{SCREENSHOTS_DIR}/v4_01_day_with_classes.png", full_page=True)
        print("📸 Screenshot: v4_01_day_with_classes.png")

        # ===== CAPTURAR TEXTO COMPLETO =====
        main_text = await page.evaluate("""() => {
            const main = document.querySelector('main, #main-content') || document.body;
            return main.innerText;
        }""")
        
        print(f"\n📝 TEXTO VISIBLE EN LA PÁGINA:")
        print(main_text[:4000])

        # ===== CAPTURAR TODOS data-cy =====
        all_data_cy = await page.evaluate("""() => {
            const elements = document.querySelectorAll('[data-cy]');
            return Array.from(elements).map(el => ({
                dataCy: el.getAttribute('data-cy'),
                tag: el.tagName,
                text: el.innerText?.trim()?.substring(0, 200),
                class: el.className?.substring(0, 150),
                children: el.children.length,
                hasButton: el.querySelector('button') !== null,
                buttonText: el.querySelector('button')?.innerText?.trim(),
            }));
        }""")

        print(f"\n🏷️ TODOS LOS data-cy ({len(all_data_cy)}):")
        for el in all_data_cy:
            btn = f" [BTN: {el.get('buttonText', '')}]" if el.get('hasButton') else ""
            print(f"   data-cy='{el['dataCy']}' [{el['tag']}] {el['text'][:100]}{btn}")

        # ===== CAPTURAR TARJETAS DE CLASES =====
        cards = await page.evaluate("""() => {
            const main = document.querySelector('main, #main-content') || document.body;
            
            // Buscar por data-cy que contenga booking o event
            const bookingItems = main.querySelectorAll(
                '[data-cy*="booking"], [data-cy*="event"], [data-cy*="class"], [data-cy*="activity"], [data-cy*="session"]'
            );
            
            const result = Array.from(bookingItems).map(el => ({
                dataCy: el.getAttribute('data-cy'),
                tag: el.tagName,
                class: el.className?.substring(0, 200),
                text: el.innerText?.trim()?.substring(0, 300),
                html: el.outerHTML?.substring(0, 1000),
                buttons: Array.from(el.querySelectorAll('button')).map(b => ({
                    text: b.innerText?.trim(),
                    class: b.className?.substring(0, 100),
                    disabled: b.disabled,
                    dataCy: b.getAttribute('data-cy'),
                })),
            }));
            
            return result;
        }""")

        print(f"\n🎴 BOOKING/EVENT ITEMS ({len(cards)}):")
        for card in cards[:15]:
            print(f"   data-cy='{card['dataCy']}'")
            print(f"   text: {card['text'][:150]}")
            for btn in card.get('buttons', []):
                print(f"     🔘 Button: '{btn['text']}' disabled={btn.get('disabled')} data-cy={btn.get('dataCy')}")
            print()

        # Guardar info completa
        with open(f"{SCREENSHOTS_DIR}/v4_full_data.json", "w", encoding="utf-8") as f:
            json.dump({"days": all_days, "dataCy": all_data_cy, "cards": cards}, f, indent=2, ensure_ascii=False)
        print(f"📄 Datos guardados: v4_full_data.json")

        # ===== SI HAY TARJETA CON BOTÓN, CLICK =====
        cards_with_buttons = [c for c in cards if c.get('buttons')]
        if cards_with_buttons:
            first = cards_with_buttons[0]
            btn = first['buttons'][0]
            print(f"\n🖱️ Click en botón: '{btn['text']}' (data-cy={btn.get('dataCy')})")
            
            if btn.get('dataCy'):
                await page.locator(f'[data-cy="{btn["dataCy"]}"]').first.click()
            else:
                # Click por texto
                btn_locator = page.locator(f'button:has-text("{btn["text"]}")').first
                await btn_locator.click()
            
            await page.wait_for_timeout(3000)
            await page.screenshot(path=f"{SCREENSHOTS_DIR}/v4_02_after_click.png", full_page=True)
            print("📸 Screenshot: v4_02_after_click.png")
            
            # Capturar resultado
            result_text = await page.evaluate("""() => {
                const main = document.querySelector('main, #main-content') || document.body;
                return main.innerText?.substring(0, 3000);
            }""")
            print(f"\n📝 Resultado post-click:")
            print(result_text[:2000])

        await page.screenshot(path=f"{SCREENSHOTS_DIR}/v4_03_final.png", full_page=True)
        await browser.close()
        print("\n✅ Exploración v4 completada")


if __name__ == "__main__":
    asyncio.run(explore())
