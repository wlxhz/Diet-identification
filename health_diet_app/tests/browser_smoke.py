"""End-to-end smoke test for the integrated recognition entry.

Run through scripts/with_server.py with HEALTH_DB_PATH pointing to a disposable
database. The test uses the locally installed Microsoft Edge executable.
"""

from __future__ import annotations

import os
import sqlite3
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright
from werkzeug.security import generate_password_hash


APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ["HEALTH_DB_PATH"])
SCREENSHOT_PATH = APP_ROOT.parent / ".browser-smoke.png"
IMAGE_PATH = APP_ROOT.parent / ".browser-food.jpg"


def seed_test_user() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO users
                (phone, password_hash, role, nickname, supervisor_code, supervisee_code)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "13800000000",
                generate_password_hash("CodexTest1"),
                "supervisee",
                "浏览器测试",
                "TESTSUP1",
                "TESTSUB1",
            ),
        )


def create_food_image() -> None:
    image = Image.new("RGB", (640, 480), "#e8dfd0")
    draw = ImageDraw.Draw(image)
    draw.ellipse((130, 55, 510, 435), fill="#f4f1e8", outline="#888", width=7)
    draw.ellipse((215, 145, 425, 355), fill="#d7a04b")
    draw.line((235, 185, 400, 315), fill="#7e421d", width=14)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    IMAGE_PATH.write_bytes(buffer.getvalue())


seed_test_user()
create_food_image()

console_errors: list[str] = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    )
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error" and "Failed to load resource" not in message.text
        else None,
    )
    page.goto("http://127.0.0.1:5000/login")
    page.wait_for_load_state("networkidle")
    page.locator("#tab-password input[name=phone]").fill("13800000000")
    page.locator("#tab-password input[name=password]").fill("CodexTest1")
    page.locator("#tab-password button[type=submit]").click()
    page.wait_for_url("**/goal")
    page.goto("http://127.0.0.1:5000/diet")
    page.wait_for_load_state("networkidle")
    page.locator("#scanFile").set_input_files(str(IMAGE_PATH))
    page.locator("#scanStatus").wait_for(state="visible")
    page.wait_for_function(
        "() => ['识别完成', '未识别到明确的食物主体'].includes("
        "document.getElementById('scanStatus').textContent)"
    )
    assert page.locator("#scanButton").is_enabled()
    assert "功能开发中" not in page.content()
    assert not console_errors, console_errors
    page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
    print("browser smoke: PASS")
    browser.close()
