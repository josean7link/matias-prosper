"""Snapshot every static client-portal page and compile a single PDF for
content review. Auth uses the dev magic-link.

Run:
    python /app/scripts/screenshot_client_portal.py
Output:
    /app/exports/prosper_client_portal_<timestamp>.pdf
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright
from PIL import Image

BASE = os.environ.get("PREVIEW_BASE",
                        "https://finance-control-215.preview.emergentagent.com")
EMAIL = os.environ.get("DEV_EMAIL", "matiasplano@gmail.com")

# Each entry: (label, path, optional wait selector)
ROUTES: list[tuple[str, str, str | None]] = [
    ("Dashboard",                "/client",                       None),
    ("Invest · USDC",            "/client/invest",                None),
    ("Invest · ARSa",            "/client/invest?asset=arsa",     None),
    ("Investments (lista)",      "/client/investments",           None),
    ("Cargar dinero (hub)",      "/client/onramp",                None),
    ("Cargar USDC",              "/client/cargar-usdc",           None),
    ("Retirar (hub)",            "/client/offramp",               None),
    ("Mis clientes (N1)",        "/client/mis-clientes",          None),
    ("Transactions",             "/client/transactions",          None),
    ("Profile",                  "/client/profile",               None),
    # Partner-only (los oculta el sidebar si org.type != 'fintech')
    ("Partner · API Keys",       "/client/api-keys",              None),
    ("Partner · Webhooks",       "/client/webhooks",              None),
    ("Partner · Docs/SDK",       "/client/developers",            None),
    ("Partner · Widget",         "/client/widget",                None),
]

OUT_DIR = Path("/app/exports")
OUT_DIR.mkdir(parents=True, exist_ok=True)
PNG_DIR = OUT_DIR / "_pages"
PNG_DIR.mkdir(parents=True, exist_ok=True)


async def main() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_path = OUT_DIR / f"prosper_client_portal_{stamp}.pdf"
    images: list[Path] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path="/pw-browsers/chromium_headless_shell-1208/chrome-linux/headless_shell",
            args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1.5)
        page = await ctx.new_page()

        # Auth: hit the dev-login magic link with a benign next so the
        # response 303s back to /client and sets the session cookie.
        login_url = f"{BASE}/api/v1/auth/dev-login?email={EMAIL}&next=/client"
        print(f"[auth] {login_url}")
        await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        print(f"[auth] landed at: {page.url}")

        for i, (label, path, sel) in enumerate(ROUTES, 1):
            url = f"{BASE}{path}"
            print(f"[{i:02d}/{len(ROUTES)}] {label}  →  {url}")
            try:
                await page.goto(url, wait_until="networkidle", timeout=25000)
            except Exception as e:                                  # noqa: BLE001
                print(f"    ! navigation slow ({e}); falling back to dcl")
                try:
                    await page.goto(url, wait_until="domcontentloaded",
                                     timeout=15000)
                except Exception as e2:                             # noqa: BLE001
                    print(f"    ! second nav failed: {e2}")
            # Settle in any async data + images
            await page.wait_for_timeout(2500)
            if sel:
                try:
                    await page.wait_for_selector(sel, timeout=4000)
                except Exception:                                   # noqa: BLE001
                    pass
            # Full-page screenshot so we see every section
            png_path = PNG_DIR / f"{i:02d}_{label.replace(' ', '_').replace('·','-').replace('/','-')}.png"
            try:
                await page.screenshot(path=str(png_path), full_page=True,
                                         type="png")
                images.append(png_path)
                print(f"    ✓ saved {png_path.name} ({png_path.stat().st_size//1024} KB)")
            except Exception as e:                                  # noqa: BLE001
                print(f"    ! screenshot failed: {e}")

        await browser.close()

    if not images:
        raise SystemExit("No screenshots captured.")

    # Compose PDF — first image sets the base; subsequent become pages.
    pil_imgs = []
    for png in images:
        img = Image.open(png).convert("RGB")
        # Cap height so individual PDF pages aren't absurd; Pillow handles
        # arbitrary sizes but PDF readers cap at ~14400 pts.
        max_h = 12000
        if img.height > max_h:
            ratio = max_h / img.height
            img = img.resize((int(img.width * ratio), max_h),
                                Image.LANCZOS)
        pil_imgs.append(img)
    first, rest = pil_imgs[0], pil_imgs[1:]
    first.save(pdf_path, format="PDF",
                save_all=True, append_images=rest, resolution=120)
    print(f"\nPDF: {pdf_path}  ({pdf_path.stat().st_size//1024} KB)")
    return pdf_path


if __name__ == "__main__":
    asyncio.run(main())
