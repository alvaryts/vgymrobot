"""
Script de exploración v2: navega desde el dashboard usando 'Nueva reserva'.
Espera la carga completa de la SPA antes de capturar.
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
        print("🔐 Navegando a login...")
        await page.goto("https://gimnasios.vivagym.es/login", wait_until="networkidle", timeout=30000)
        await page.wait_for_selector("#email", state="visible", timeout=15000)

        username = os.getenv("GYM_USERNAME", "")
        password = os.getenv("GYM_PASSWORD", "")
        await page.locator("#email").fill(username)
        await page.locator("#password").fill(password)
        await page.locator('button[type="submit"]').click()

        # Esperar a que aparezca el dashboard (bienvenido)
        print("⏳ Esperando dashboard...")
        try:
            await page.wait_for_selector("text=Bienvenido", timeout=15000)
            print("✅ Dashboard cargado")
        except Exception:
            await page.wait_for_timeout(5000)
            print(f"⚠️ Dashboard posible: {page.url}")

        await page.screenshot(path=f"{SCREENSHOTS_DIR}/v2_01_dashboard.png", full_page=True)

        # ===== 2. CLICK EN 'Nueva reserva' =====
        print("\n🔗 Buscando botón 'Nueva reserva'...")
        nueva_reserva = page.locator("text=Nueva reserva").first
        if await nueva_reserva.count() > 0:
            print("   ✅ Botón encontrado, haciendo click...")
            await nueva_reserva.click()
        else:
            # Intentar link directo a /booking
            print("   ⚠️ No encontrado, navegando a /booking directo...")
            await page.goto("https://gimnasios.vivagym.es/booking", wait_until="domcontentloaded", timeout=15000)

        # Esperar MUCHO más tiempo para que la SPA cargue el contenido
        print("⏳ Esperando carga de contenido de reservas (hasta 20s)...")
        
        # Esperar a que desaparezca el "Cargando..."
        try:
            await page.wait_for_selector("text=Cargando", state="hidden", timeout=20000)
            print("   ✅ Carga completada (indicador 'Cargando...' desapareció)")
        except Exception:
            print("   ⚠️ Timeout esperando que desaparezca 'Cargando...'")
        
        await page.wait_for_timeout(3000)  # Extra time
        
        current_url = page.url
        print(f"📍 URL: {current_url}")
        await page.screenshot(path=f"{SCREENSHOTS_DIR}/v2_02_booking_loaded.png", full_page=True)
        print("📸 Screenshot: v2_02_booking_loaded.png")

        # ===== 3. CAPTURAR TODA LA INFO DISPONIBLE =====
        page_content = await page.evaluate("""() => {
            const main = document.querySelector('main, #main-content') || document.body;
            return {
                text: main.innerText?.substring(0, 5000),
                html: main.innerHTML?.substring(0, 10000),
            };
        }""")

        print(f"\n📝 TEXTO VISIBLE EN LA PÁGINA:")
        print(page_content.get("text", "")[:3000])

        # Guardar HTML para análisis
        html_path = f"{SCREENSHOTS_DIR}/v2_booking_html.txt"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page_content.get("html", ""))
        print(f"\n📄 HTML guardado: {html_path}")

        # ===== 4. CAPTURAR TODOS LOS ELEMENTOS INTERACTIVOS =====
        interactive = await page.evaluate("""() => {
            const elements = document.querySelectorAll('button, a, input, select, [role="button"], [role="tab"], [role="listbox"], [data-date], [class*="day"], [class*="date"], [class*="calendar"]');
            return Array.from(elements)
                .filter(el => el.offsetParent !== null)
                .map(el => ({
                    tag: el.tagName,
                    text: el.innerText?.trim()?.substring(0, 100),
                    class: el.className?.substring(0, 200),
                    id: el.id,
                    href: el.getAttribute('href'),
                    type: el.type || el.getAttribute('type'),
                    role: el.getAttribute('role'),
                    value: el.value?.substring(0, 50),
                    name: el.name,
                    dataAttrs: Object.keys(el.dataset || {}).map(k => `data-${k}=${el.dataset[k]?.substring(0, 50)}`),
                }))
                .filter(el => el.text || el.href || el.id || el.name);
        }""")

        print(f"\n🔧 ELEMENTOS INTERACTIVOS ({len(interactive)}):")
        for el in interactive:
            attrs = ""
            if el.get('id'): attrs += f" id={el['id']}"
            if el.get('href'): attrs += f" href={el['href'][:60]}"
            if el.get('role'): attrs += f" role={el['role']}"
            if el.get('dataAttrs'): attrs += f" {' '.join(el['dataAttrs'][:3])}"
            print(f"   [{el['tag']}] '{el.get('text', '')[:60]}' class='{el.get('class', '')[:60]}'{attrs}")

        # ===== 5. BUSCAR SELECTORES DE CLASES/ACTIVIDADES =====
        class_items = await page.evaluate("""() => {
            // Buscar algo que parezca una lista de clases
            const allText = document.querySelector('main, #main-content')?.innerText || '';
            
            // Buscar selectores tipo dropdown o filtros
            const selects = document.querySelectorAll('select, [role="listbox"], [class*="select"], [class*="dropdown"], [class*="filter"]');
            const selectInfo = Array.from(selects).map(s => ({
                tag: s.tagName,
                class: s.className?.substring(0, 150),
                id: s.id,
                options: s.tagName === 'SELECT' ? Array.from(s.options).map(o => ({value: o.value, text: o.text})) : [],
                text: s.innerText?.substring(0, 200),
            }));

            // Buscar tabs
            const tabs = document.querySelectorAll('[role="tab"], [class*="tab"]');
            const tabInfo = Array.from(tabs).filter(t => t.offsetParent !== null).map(t => ({
                tag: t.tagName,
                class: t.className?.substring(0, 150),
                text: t.innerText?.trim()?.substring(0, 100),
                selected: t.getAttribute('aria-selected'),
            }));

            // Buscar dates/calendar
            const dates = document.querySelectorAll('[data-date], [class*="calendar"], [class*="datepicker"]');
            const dateInfo = Array.from(dates).map(d => ({
                tag: d.tagName,
                class: d.className?.substring(0, 150),
                text: d.innerText?.trim()?.substring(0, 100),
                dataDate: d.dataset?.date,
            }));

            return { selects: selectInfo, tabs: tabInfo, dates: dateInfo, pageText: allText.substring(0, 2000) };
        }""")

        if class_items.get('selects'):
            print(f"\n📋 SELECTORES/DROPDOWNS ({len(class_items['selects'])}):")
            for s in class_items['selects']:
                print(f"   {s['tag']} #{s.get('id', '')} .{s.get('class', '')[:60]}")
                for opt in s.get('options', [])[:10]:
                    print(f"      - {opt['text']} (value: {opt['value']})")

        if class_items.get('tabs'):
            print(f"\n🔖 TABS ({len(class_items['tabs'])}):")
            for t in class_items['tabs']:
                print(f"   [{t['tag']}] '{t['text']}' selected={t.get('selected')}")

        if class_items.get('dates'):
            print(f"\n📅 ELEMENTOS DE FECHA ({len(class_items['dates'])}):")
            for d in class_items['dates']:
                print(f"   [{d['tag']}] {d['text']} date={d.get('dataDate')}")

        # ===== 6. SCREENSHOT FINAL =====
        await page.screenshot(path=f"{SCREENSHOTS_DIR}/v2_03_final.png", full_page=True)
        print("\n📸 Screenshot final: v2_03_final.png")

        await browser.close()
        print("\n✅ Exploración v2 completada")


if __name__ == "__main__":
    asyncio.run(explore())
