"""
parser_ali.py — Парсер акцій AliExpress
Джерела:
1. AliExpress Portals API (офіційно, потрібен APP_KEY)
2. Публічна сторінка акцій як fallback (без ключа)
"""

import aiohttp
import logging
import os
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Отримати безкоштовно на: https://portals.aliexpress.com
ALI_APP_KEY    = os.getenv("ALI_APP_KEY", "")
ALI_APP_SECRET = os.getenv("ALI_APP_SECRET", "")
ALI_TRACKING   = os.getenv("ALI_TRACKING_ID", "")  # твій tracking ID з Portals

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
}

# ============================================================
# ВАРІАНТ 1: Офіційний AliExpress Portals API
# Потрібна реєстрація на portals.aliexpress.com (безкоштовно)
# Дає реальні партнерські посилання з твоїм tracking ID
# ============================================================
async def fetch_ali_api(category: str = "accessories", limit: int = 5) -> list[dict]:
    """
    Отримує топ товари зі знижками через офіційний API.
    Повертає список: [{"title": ..., "price": ..., "original_price": ..., "url": ..., "discount": ...}]
    """
    if not ALI_APP_KEY:
        logger.info("ALI_APP_KEY не задано — пропускаємо API, переходимо до fallback")
        return []

    import hmac
    import hashlib
    import time
    import json

    timestamp = str(int(time.time() * 1000))
    params = {
        "app_key": ALI_APP_KEY,
        "timestamp": timestamp,
        "sign_method": "hmac",
        "method": "aliexpress.affiliate.hotproduct.query",
        "category_ids": "200000783",  # Electronics & Accessories
        "fields": "app_sale_price,original_price,product_title,product_detail_url,discount",
        "page_size": str(limit),
        "page_no": "1",
        "tracking_id": ALI_TRACKING,
    }

    # Підпис запиту
    sorted_params = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    sign = hmac.new(
        ALI_APP_SECRET.encode(),
        sorted_params.encode(),
        hashlib.md5
    ).hexdigest().upper()
    params["sign"] = sign

    try:
        async with aiohttp.ClientSession(headers=HEADERS) as s:
            async with s.get(
                "https://api-sg.aliexpress.com/sync",
                params=params,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                data = await r.json()

        products = (
            data
            .get("aliexpress_affiliate_hotproduct_query_response", {})
            .get("resp_result", {})
            .get("result", {})
            .get("products", {})
            .get("product", [])
        )

        result = []
        for p in products:
            result.append({
                "title":          p.get("product_title", "")[:60],
                "price":          float(p.get("app_sale_price", 0)),
                "original_price": float(p.get("original_price", 0)),
                "discount":       p.get("discount", ""),
                "url":            p.get("product_detail_url", ""),
                "source":         "aliexpress_api",
            })
        logger.info(f"AliExpress API: отримано {len(result)} товарів")
        return result

    except Exception as e:
        logger.error(f"AliExpress API помилка: {e}")
        return []

# ============================================================
# ВАРІАНТ 2: Fallback — парсинг публічної сторінки акцій
# Працює без API ключа, але менш стабільний
# Парсимо hotdeals.aliexpress.com — публічна сторінка акцій
# ============================================================
async def fetch_ali_fallback(limit: int = 5) -> list[dict]:
    """
    Парсить публічну сторінку акцій AliExpress.
    Не потребує API ключа, але може зламатись якщо AliExpress змінить верстку.
    """
    url = "https://www.aliexpress.com/deals.html"
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                html = await r.text()
    except Exception as e:
        logger.error(f"AliExpress fallback — не вдалось завантажити: {e}")
        return []

    try:
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select(".product-card, [class*='deal-item'], [class*='product-item']")[:limit]

        result = []
        for item in items:
            title_el = item.select_one("[class*='title'], h3, h4")
            price_el  = item.select_one("[class*='price-sale'], [class*='current-price']")
            link_el   = item.select_one("a[href]")

            title = title_el.get_text(strip=True)[:60] if title_el else "AliExpress Deal"
            price_text = price_el.get_text(strip=True) if price_el else "0"
            link  = link_el["href"] if link_el else url

            # Додаємо tracking якщо є
            if ALI_TRACKING and "aff_fcid" not in link:
                link = f"{link}{'&' if '?' in link else '?'}aff_fcid={ALI_TRACKING}"

            try:
                price = float(price_text.replace("$", "").replace(",", ".").strip().split()[0])
            except Exception:
                price = 0.0

            if title:
                result.append({
                    "title":          title,
                    "price":          price,
                    "original_price": 0.0,
                    "discount":       "",
                    "url":            link if link.startswith("http") else f"https://aliexpress.com{link}",
                    "source":         "aliexpress_fallback",
                })

        logger.info(f"AliExpress fallback: знайдено {len(result)} товарів")
        return result

    except Exception as e:
        logger.error(f"AliExpress fallback — помилка парсингу: {e}")
        return []

# ============================================================
# ГОЛОВНА ФУНКЦІЯ
# ============================================================
async def get_ali_deals(limit: int = 5) -> list[dict]:
    """
    Спочатку пробує офіційний API, якщо немає ключа — fallback на парсинг.
    """
    deals = await fetch_ali_api(limit=limit)
    if not deals:
        deals = await fetch_ali_fallback(limit=limit)
    return deals
