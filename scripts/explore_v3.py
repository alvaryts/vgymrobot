"""
Script de exploración v3: explora un día con clases y captura las tarjetas de actividades.
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

        # ===== 1. LOGIN =====
        print("🔐 Login...")
        await page.goto("https://gimnasios.vivagym.es/login", wait_until="networkidle", timeout=30000)
        await page.wait_for_selector("#email", state="visible", timeout=15000)

        username = os.getenv("GYM_USERNAME", "")
        password = os.getenv("GYM_PASSWORD", "")
        await page.locator("#email").fill(username)
        await page.locator("#password").fill(password)
        await page.locator('button[type="submit"]').click()
        await page.wait_for_selector("text=Bienvenido", timeout=15000)
        print("✅ Login OK")

        # ===== 2. NAVEGAR A RESERVAS =====
        print("\n📋 Navegando a reservas...")
        await page.locator("text=Nueva reserva").first.click()
        
        # Esperar a que la SPA cargue
        try:
            await page.wait_for_selector("text=Cargando", state="hidden", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)
        print(f"📍 URL: {page.url}")

        # ===== 3. CLICK EN DÍA CON CLASES (mañana miércoles) =====
        print("\n📅 Seleccionando miércoles (mañana, debería tener clases)...")
        
        # Los días se muestran como divs con texto
        day_buttons = page.locator("div.px-1.select-none")
        day_count = await day_buttons.count()
        print(f"   Encontrados {day_count} botones de día")
        
        # Buscar y hacer click en un día futuro
        for i in range(day_count):
            btn = day_buttons.nth(i)
            text = await btn.text_content() or ""
            print(f"   Día {i}: '{text.strip()}'")
            
            if "miércoles" in text.lower() or "miercoles" in text.lower():
                print(f"   ✅ Seleccionando: {text.strip()}")
                await btn.click()
                await page.wait_for_timeout(3000)
                break
            elif "lunes" in text.lower():
                print(f"   ✅ Seleccionando lunes: {text.strip()}")
                await btn.click()
                await page.wait_for_timeout(3000)
                break
        
        # Esperar carga
        try:
            await page.wait_for_selector("text=Cargando", state="hidden", timeout=10000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)

        await page.screenshot(path=f"{SCREENSHOTS_DIR}/v3_01_day_selected.png", full_page=True)
        print("📸 Screenshot: v3_01_day_selected.png")

        # ===== 4. CAPTURAR CONTENIDO PRINCIPAL =====
        main_text = await page.evaluate("""() => {
            const main = document.querySelector('main, #main-content') || document.body;
            return main.innerText?.substring(0, 5000);
        }""")
        
        print(f"\n📝 TEXTO VISIBLE:")
        print(main_text[:3000])

        # ===== 5. CAPTURAR TARJETAS DE CLASES =====
        class_info = await page.evaluate("""() => {
            const main = document.querySelector('main, #main-content') || document.body;
            
            // Buscar todos los elementos con data-cy
            const dataCy = main.querySelectorAll('[data-cy]');
            const dataCyInfo = Array.from(dataCy).map(el => ({
                dataCy: el.getAttribute('data-cy'),
                tag: el.tagName,
                class: el.className?.substring(0, 200),
                text: el.innerText?.trim()?.substring(0, 200),
            }));

            // HTML completo del main
            const html = main.innerHTML?.substring(0, 15000);

            // Buscar todas las divs que podrían ser tarjetas
            const allDivs = main.querySelectorAll('div[class]');
            const cards = Array.from(allDivs)
                .filter(d => {
                    const text = d.innerText?.trim() || '';
                    // Una tarjeta de clase típicamente tiene hora y nombre
                    return text.length > 10 && text.length < 500 && 
                           (text.match(/\\d{1,2}:\\d{2}/) || text.match(/\\d{1,2}h/));
                })
                .slice(0, 20)
                .map(d => ({
                    tag: d.tagName,
                    class: d.className?.substring(0, 200),
                    text: d.innerText?.trim()?.substring(0, 300),
                    hasBookButton: d.querySelector('button') !== null,
                    buttonText: d.querySelector('button')?.innerText?.trim(),
                    dataCy: d.getAttribute('data-cy'),
                    children: d.children.length,
                }));

            return { dataCy: dataCyInfo, cards, html };
        }""")

        print(f"\n🏷️ ELEMENTOS CON data-cy ({len(class_info.get('dataCy', []))}):")
        for el in class_info.get('dataCy', []):
            print(f"   data-cy='{el['dataCy']}' [{el['tag']}] {el['text'][:80]}")

        print(f"\n🎴 TARJETAS DE CLASES ({len(class_info.get('cards', []))}):")
        for card in class_info.get('cards', []):
            btn_text = f" [BTN: {card.get('buttonText', '')}]" if card.get('hasBookButton') else ""
            print(f"   .{card.get('class', '')[:60]} → {card['text'][:100]}{btn_text}")

        # Guardar HTML completo
        html_path = f"{SCREENSHOTS_DIR}/v3_booking_html.txt"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(class_info.get("html", ""))
        print(f"\n📄 HTML guardado: {html_path}")

        # ===== 6. SI HAY CLASES, EXPLORAR UNA TARJETA =====
        cards = class_info.get('cards', [])
        if cards:
            print(f"\n🖱️ Explorando primera tarjeta de clase...")
            first_card = cards[0]
            # Intentar click en la tarjeta
            card_text = first_card['text'][:50].split('\n')[0]
            try:
                target = page.locator(f"text='{card_text}'").first
                await target.click()
                await page.wait_for_timeout(3000)
                
                await page.screenshot(path=f"{SCREENSHOTS_DIR}/v3_02_class_clicked.png", full_page=True)
                print("📸 Screenshot: v3_02_class_clicked.png")

                # Capturar modal/detalle
                modal_info = await page.evaluate("""() => {
                    const modals = document.querySelectorAll(
                        '[class*="modal"], [class*="dialog"], [role="dialog"], ' +
                        '[class*="popup"], [class*="overlay"][style*="display"]'
                    );
                    if (modals.length === 0) {
                        // Quizá no hay modal, el botón está directamente en la tarjeta
                        return "No modal - button might be inline";
                    }
                    return Array.from(modals).map(m => ({
                        class: m.className?.substring(0, 200),
                        visible: m.offsetParent !== null || m.style.display !== 'none',
                        html: m.innerHTML?.substring(0, 3000),
                        buttons: Array.from(m.querySelectorAll('button')).map(b => b.innerText?.trim()),
                    }));
                }""")
                                
                modal_path = f"{SCREENSHOTS_DIR}/v3_modal_info.json"
                with open(modal_path, "w", encoding="utf-8") as f:
                    json.dump(modal_info, f, indent=2, ensure_ascii=False)
                print(f"📄 Modal info guardada: {modal_path}")

            except Exception as e:
                print(f"⚠️ Error explorando tarjeta: {e}")
        else:
            print("\n⚠️ No se encontraron tarjetas de clases con hora")
            
            # Intentar navegar a la flecha derecha para ver más días
            forward = page.locator("text=>").first
            if await forward.count() > 0:
                print("   ➡️ Intentando siguiente semana...")
                await forward.click()
                await page.wait_for_timeout(3000)

                await page.screenshot(path=f"{SCREENSHOTS_DIR}/v3_02_next_week.png", full_page=True)
                print("📸 Screenshot: v3_02_next_week.png")

        # ===== FINAL =====
        await page.screenshot(path=f"{SCREENSHOTS_DIR}/v3_03_final.png", full_page=True)
        print(f"\n📸 Screenshot final. URL: {page.url}")
        
        await browser.close()
        print("✅ Exploración v3 completada")


if __name__ == "__main__":
    asyncio.run(explore())
