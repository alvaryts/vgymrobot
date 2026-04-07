"""
Script de exploración: login + captura de DOM y screenshots post-login.
Este script NO reserva nada, solo explora la interfaz.
"""

import asyncio
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from playwright.async_api import async_playwright

# Cargar .env
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
        print("🔐 Navegando a login...")
        await page.goto("https://gimnasios.vivagym.es/login", wait_until="networkidle", timeout=30000)
        await page.wait_for_selector("#email", state="visible", timeout=15000)
        
        # Screenshot pre-login
        await page.screenshot(path=f"{SCREENSHOTS_DIR}/01_login_page.png", full_page=True)
        print("📸 Screenshot: 01_login_page.png")

        # Rellenar credenciales
        username = os.getenv("GYM_USERNAME", "")
        password = os.getenv("GYM_PASSWORD", "")
        
        if not username or not password:
            print("❌ GYM_USERNAME o GYM_PASSWORD no definidos en .env")
            return

        await page.locator("#email").fill(username)
        await page.locator("#password").fill(password)
        
        print("🔑 Credenciales introducidas, haciendo login...")
        await page.locator('button[type="submit"]').click()

        # Esperar navegación post-login
        await page.wait_for_timeout(5000)
        await page.wait_for_load_state("networkidle", timeout=15000)

        current_url = page.url
        print(f"📍 URL post-login: {current_url}")

        # Screenshot post-login
        await page.screenshot(path=f"{SCREENSHOTS_DIR}/02_post_login.png", full_page=True)
        print("📸 Screenshot: 02_post_login.png")

        # ===== 2. EXPLORAR NAVEGACIÓN =====
        # Capturar todos los links y botones visibles
        nav_info = await page.evaluate("""() => {
            const links = Array.from(document.querySelectorAll('a, button, [role="button"]'));
            return links
                .filter(el => el.offsetParent !== null) // solo visibles
                .map(el => ({
                    tag: el.tagName,
                    text: el.innerText?.trim().substring(0, 80),
                    href: el.href || el.getAttribute('href') || '',
                    class: el.className?.substring(0, 100),
                    id: el.id,
                }))
                .filter(el => el.text || el.href);
        }""")
        
        print(f"\n📋 NAVEGACIÓN DISPONIBLE ({len(nav_info)} elementos):")
        for item in nav_info:
            print(f"   [{item['tag']}] {item['text'][:50]} → {item['href'][:60]}")

        # ===== 3. BUSCAR SECCIÓN DE RESERVAS =====
        print("\n🔍 Buscando sección de reservas...")
        
        booking_found = False
        for item in nav_info:
            text_lower = (item.get("text", "") or "").lower()
            href_lower = (item.get("href", "") or "").lower()
            
            if any(kw in text_lower or kw in href_lower 
                   for kw in ["reserv", "horario", "clase", "booking", "schedule", "actividad", "timetable"]):
                print(f"   🎯 ¡Encontrado! [{item['tag']}] '{item['text']}' → {item['href']}")
                
                # Navegar a esa sección
                if item['href'] and item['href'].startswith('http'):
                    await page.goto(item['href'], wait_until="networkidle", timeout=15000)
                elif item['href'] and item['href'].startswith('/'):
                    await page.goto(f"https://gimnasios.vivagym.es{item['href']}", wait_until="networkidle", timeout=15000)
                else:
                    # Click en el elemento
                    target = page.locator(f"text='{item['text']}'").first
                    await target.click()
                    await page.wait_for_timeout(3000)
                    await page.wait_for_load_state("networkidle", timeout=15000)
                
                booking_found = True
                break

        if not booking_found:
            # Intentar rutas directa
            test_paths = ["/booking", "/reservas", "/horario", "/schedule", "/classes", "/timetable", "/activities"]
            for path in test_paths:
                url = f"https://gimnasios.vivagym.es{path}"
                print(f"   🔗 Probando ruta directa: {url}")
                resp = await page.goto(url, wait_until="networkidle", timeout=10000)
                await page.wait_for_timeout(2000)
                cur = page.url
                if "/login" not in cur and cur != "https://gimnasios.vivagym.es/":
                    print(f"   ✅ Ruta válida: {cur}")
                    booking_found = True
                    break
                    
        print(f"📍 URL sección reservas: {page.url}")
        await page.screenshot(path=f"{SCREENSHOTS_DIR}/03_booking_section.png", full_page=True)
        print("📸 Screenshot: 03_booking_section.png")

        # ===== 4. CAPTURAR DOM DE RESERVAS =====
        dom_info = await page.evaluate("""() => {
            // Capturar estructura completa relevante del body
            function getStructure(el, depth = 0) {
                if (depth > 6) return null;
                if (!el || !el.tagName) return null;
                
                const result = {
                    tag: el.tagName.toLowerCase(),
                    id: el.id || undefined,
                    class: el.className?.substring?.(0, 150) || undefined,
                    text: el.children?.length === 0 ? el.innerText?.trim()?.substring(0, 100) : undefined,
                    role: el.getAttribute('role') || undefined,
                    type: el.getAttribute('type') || undefined,
                    href: el.getAttribute('href') || undefined,
                };
                
                // Limpiar undefined
                Object.keys(result).forEach(k => result[k] === undefined && delete result[k]);
                
                if (el.children?.length > 0 && depth < 6) {
                    result.children = Array.from(el.children)
                        .slice(0, 20)
                        .map(c => getStructure(c, depth + 1))
                        .filter(Boolean);
                }
                
                return result;
            }
            
            const main = document.querySelector('main, #app, .app, [role="main"]') || document.body;
            return getStructure(main, 0);
        }""")

        # Guardar DOM como JSON
        dom_path = f"{SCREENSHOTS_DIR}/dom_structure.json"
        with open(dom_path, "w", encoding="utf-8") as f:
            json.dump(dom_info, f, indent=2, ensure_ascii=False)
        print(f"📄 DOM guardado: {dom_path}")

        # ===== 5. BUSCAR ELEMENTOS DE CLASES =====
        class_cards = await page.evaluate("""() => {
            // Buscar elementos que parezcan tarjetas/filas de clases
            const selectors = [
                '[class*="class"]', '[class*="session"]', '[class*="event"]',
                '[class*="booking"]', '[class*="activity"]', '[class*="card"]',
                '[class*="schedule"]', '[class*="timetable"]', '[class*="lesson"]',
                '[class*="reserv"]', '[class*="horario"]', 'li', 'tr',
            ];
            
            const results = [];
            for (const sel of selectors) {
                const els = document.querySelectorAll(sel);
                for (const el of els) {
                    const text = el.innerText?.trim();
                    if (text && text.length > 5 && text.length < 500) {
                        results.push({
                            selector: sel,
                            tag: el.tagName,
                            class: el.className?.substring(0, 150),
                            id: el.id,
                            text: text.substring(0, 200),
                            hasButton: el.querySelector('button, a[class*="book"], a[class*="reserv"], [role="button"]') !== null,
                        });
                    }
                }
                if (results.length > 30) break;
            }
            return results;
        }""")

        print(f"\n🎴 ELEMENTOS DE CLASES ENCONTRADOS ({len(class_cards)}):")
        for card in class_cards[:20]:
            btn = "🔘" if card.get('hasButton') else "  "
            print(f"   {btn} [{card['selector']}] {card['tag']}.{card.get('class', '')[:40]} → {card['text'][:80]}")

        # ===== 6. INTERACTUAR CON CLASES SI LAS HAY =====
        if class_cards:
            # Click en la primera clase para ver qué pasa
            first_card_text = class_cards[0].get('text', '')[:30]
            print(f"\n🖱️ Intentando interactuar con primera clase: '{first_card_text}'...")
            
            try:
                first = page.locator(f"text='{first_card_text}'").first
                await first.click()
                await page.wait_for_timeout(3000)
                
                await page.screenshot(path=f"{SCREENSHOTS_DIR}/04_class_detail.png", full_page=True)
                print("📸 Screenshot: 04_class_detail.png")

                # Capturar DOM del detalle/modal
                detail_dom = await page.evaluate("""() => {
                    const modals = document.querySelectorAll('[class*="modal"], [class*="dialog"], [class*="popup"], [class*="overlay"], [role="dialog"]');
                    if (modals.length > 0) {
                        return Array.from(modals).map(m => ({
                            tag: m.tagName,
                            class: m.className?.substring(0, 150),
                            html: m.innerHTML?.substring(0, 2000),
                            visible: m.offsetParent !== null,
                        }));
                    }
                    return "No modal found";
                }""")
                
                detail_path = f"{SCREENSHOTS_DIR}/class_detail_dom.json"
                with open(detail_path, "w", encoding="utf-8") as f:
                    json.dump(detail_dom, f, indent=2, ensure_ascii=False)
                print(f"📄 Detalle DOM guardado: {detail_path}")

            except Exception as e:
                print(f"⚠️ No se pudo interactuar con la clase: {e}")

        # ===== 7. CAPTURA FINAL =====
        await page.screenshot(path=f"{SCREENSHOTS_DIR}/05_final_state.png", full_page=True)
        print("\n📸 Screenshot final: 05_final_state.png")
        print(f"📍 URL final: {page.url}")

        await browser.close()
        print("\n✅ Exploración completada. Revisa la carpeta screenshots/")


if __name__ == "__main__":
    asyncio.run(explore())
