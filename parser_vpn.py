"""
parser_vpn.py — Парсер актуальних VPN акцій
Джерела:
- NordVPN публічна сторінка акцій (nordvpn.com/pricing)
- Surfshark публічна сторінка (surfshark.com/vpn/pricing)
- Admitad API якщо є ключ (офіційні промокоди)
"""

import aiohttp
import logging
import os
import re
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

ADMITAD_TOKEN = os.getenv("ADMITAD_TOKEN", "")  # з кабінету Admitad → API

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# Твої партнерські посилання (вставляєш після реєстрації в партнерці)
NORDVPN_AFFILIATE_URL  = os.getenv("NORDVPN_AFFILIATE_URL", "https://nordvpn.com")
SURFSHARK_AFFILIATE_URL = os.getenv("SURFSHARK_AFFILIATE_URL", "https://surfshark.com")

# ============================================================
# NORDVPN
# ============================================================
async def fetch_nordvpn_deals() -> list[dict]:
    """
    Парсить публічну сторінку цін NordVPN і формує список актуальних акцій.
    """
    url = "https://nordvpn.com/pricing/"
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                html = await r.text()
    except Exception as e:
        logger.error(f"NordVPN парсинг — помилка завантаження: {e}")
        return _nordvpn_fallback()

    try:
        soup = BeautifulSoup(html, "html.parser")

        deals = []

        # Шукаємо блоки тарифів
        plan_blocks = soup.select(
            "[class*='plan'], [class*='pricing'], [class*='subscription'], [class*='offer']"
        )

        for block in plan_blocks[:6]:
            # Назва плану
            name_el = block.select_one(
                "[class*='name'], [class*='title'], [class*='plan-name'], h2, h3, h4"
            )
            # Ціна зі знижкою
            price_el = block.select_one(
                "[class*='sale-price'], [class*='current'], [class*='discounted'], [class*='price']"
            )
            # Відсоток знижки
            discount_el = block.select_one(
                "[class*='discount'], [class*='save'], [class*='off']"
            )

            name     = name_el.get_text(strip=True) if name_el else ""
            price    = price_el.get_text(strip=True) if price_el else ""
            discount = discount_el.get_text(strip=True) if discount_el else ""

            if name and price:
                deals.append({
                    "title":    f"🔒 NordVPN — {name}",
                    "price":    _extract_price(price),
                    "discount": discount,
                    "url":      NORDVPN_AFFILIATE_URL,
                    "source":   "nordvpn",
                    "note":     f"Знижка: {discount}" if discount else "",
                })

        if deals:
            logger.info(f"NordVPN: знайдено {len(deals)} планів")
            return deals

    except Exception as e:
        logger.error(f"NordVPN парсинг — помилка обробки: {e}")

    return _nordvpn_fallback()

def _nordvpn_fallback() -> list[dict]:
    """
    Хардкод актуальних NordVPN планів як fallback.
    Оновлюй вручну раз на місяць якщо сайт змінить структуру.
    Актуальні ціни: nordvpn.com/pricing
    """
    return [
        {
            "title":    "🔒 NordVPN — 2 роки + 3 міс БЕЗКОШТОВНО",
            "price":    3.09,
            "discount": "до 72%",
            "url":      NORDVPN_AFFILIATE_URL,
            "source":   "nordvpn_fallback",
            "note":     "Найвигідніший план. Ціна $3.09/міс",
        },
        {
            "title":    "🔒 NordVPN — 1 рік",
            "price":    4.99,
            "discount": "до 59%",
            "url":      NORDVPN_AFFILIATE_URL,
            "source":   "nordvpn_fallback",
            "note":     "Ціна $4.99/міс",
        },
        {
            "title":    "🔒 NordVPN — 1 місяць",
            "price":    12.99,
            "discount": "",
            "url":      NORDVPN_AFFILIATE_URL,
            "source":   "nordvpn_fallback",
            "note":     "Без зобов'язань",
        },
    ]

# ============================================================
# SURFSHARK
# ============================================================
async def fetch_surfshark_deals() -> list[dict]:
    """
    Парсить сторінку цін Surfshark.
    """
    url = "https://surfshark.com/vpn/pricing"
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                html = await r.text()
    except Exception as e:
        logger.error(f"Surfshark парсинг — помилка: {e}")
        return _surfshark_fallback()

    try:
        soup = BeautifulSoup(html, "html.parser")
        deals = []

        plan_blocks = soup.select(
            "[class*='plan'], [class*='pricing-card'], [class*='subscription']"
        )[:4]

        for block in plan_blocks:
            name_el     = block.select_one("[class*='name'], [class*='title'], h2, h3, h4")
            price_el    = block.select_one("[class*='price'], [class*='amount']")
            discount_el = block.select_one("[class*='discount'], [class*='save'], [class*='off']")

            name     = name_el.get_text(strip=True) if name_el else ""
            price    = price_el.get_text(strip=True) if price_el else ""
            discount = discount_el.get_text(strip=True) if discount_el else ""

            if name and price:
                deals.append({
                    "title":    f"🦈 Surfshark — {name}",
                    "price":    _extract_price(price),
                    "discount": discount,
                    "url":      SURFSHARK_AFFILIATE_URL,
                    "source":   "surfshark",
                    "note":     f"Знижка: {discount}" if discount else "",
                })

        if deals:
            logger.info(f"Surfshark: знайдено {len(deals)} планів")
            return deals

    except Exception as e:
        logger.error(f"Surfshark парсинг — помилка обробки: {e}")

    return _surfshark_fallback()

def _surfshark_fallback() -> list[dict]:
    return [
        {
            "title":    "🦈 Surfshark — 2 роки",
            "price":    2.19,
            "discount": "до 82%",
            "url":      SURFSHARK_AFFILIATE_URL,
            "source":   "surfshark_fallback",
            "note":     "Ціна $2.19/міс + 3 міс безкоштовно",
        },
        {
            "title":    "🦈 Surfshark — 1 рік",
            "price":    3.99,
            "discount": "до 67%",
            "url":      SURFSHARK_AFFILIATE_URL,
            "source":   "surfshark_fallback",
            "note":     "Ціна $3.99/міс",
        },
    ]

# ============================================================
# ADMITAD API (якщо є токен)
# ============================================================
async def fetch_admitad_coupons(limit: int = 10) -> list[dict]:
    """
    Отримує актуальні купони/промокоди через Admitad API.
    Токен отримується в кабінеті Admitad → API → Client credentials.
    """
    if not ADMITAD_TOKEN:
        return []

    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://api.admitad.com/coupons/",
                headers={
                    "Authorization": f"Bearer {ADMITAD_TOKEN}",
                    "Content-Type": "application/json",
                },
                params={
                    "limit": limit,
                    "order_by": "-date_start",
                    "category": "software",  # VPN потрапляє в software
                },
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                data = await r.json()

        results = data.get("results", [])
        deals = []
        for item in results:
            deals.append({
                "title":    item.get("name", "Промокод")[:60],
                "price":    0.0,
                "discount": item.get("discount", ""),
                "url":      item.get("goto_link", ""),
                "source":   "admitad",
                "note":     item.get("description", "")[:100],
                "code":     item.get("coupon", ""),
            })

        logger.info(f"Admitad API: отримано {len(deals)} купонів")
        return deals

    except Exception as e:
        logger.error(f"Admitad API помилка: {e}")
        return []

# ============================================================
# ХЕЛПЕРИ
# ============================================================
def _extract_price(text: str) -> float:
    """Витягує число з рядка типу '$3.09/mo' або '€4,99'"""
    try:
        cleaned = re.sub(r"[^\d.,]", "", text.split("/")[0])
        cleaned = cleaned.replace(",", ".")
        return float(cleaned)
    except Exception:
        return 0.0

# ============================================================
# ГОЛОВНА ФУНКЦІЯ
# ============================================================
async def get_vpn_deals() -> list[dict]:
    """
    Збирає VPN акції з усіх джерел.
    """
    nord      = await fetch_nordvpn_deals()
    surf      = await fetch_surfshark_deals()
    admitad   = await fetch_admitad_coupons()

    all_deals = nord + surf + admitad
    logger.info(f"VPN deals всього: {len(all_deals)}")
    return all_deals
