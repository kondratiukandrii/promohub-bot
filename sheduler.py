"""
scheduler.py — Автооновлення товарів в БД з парсерів
Запускається як окрема задача всередині бота (asyncio.create_task)
або як окремий процес.

Логіка:
- Кожні N годин запускає парсери
- Формує/оновлює паки в БД
- Сповіщає адміна про результат
"""

import asyncio
import aiosqlite
import logging
import os
import time
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH  = os.getenv("DB_PATH", "db.sqlite3")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Як часто оновлювати (в годинах)
UPDATE_INTERVAL_HOURS = float(os.getenv("PARSER_INTERVAL_HOURS", "6"))

# Мінімальна кількість товарів щоб оновлення мало сенс
MIN_DEALS = 1

# ============================================================
# СИНХРОНІЗАЦІЯ ПАКУ В БД
# ============================================================
async def upsert_pack(
    pack_id: str,
    name: str,
    price: float,
    delivery_type: str,  # "link" | "code" | "pdf"
    content: str,        # URL або промокод
    note: str = ""
):
    """
    Створює або оновлює пак в БД.
    Якщо пак з таким pack_id вже є — оновлює дані.
    Якщо немає — створює новий.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Перевіряємо чи є активні pending_payments — не чіпаємо такі паки
        async with db.execute(
            "SELECT COUNT(*) FROM pending_payments WHERE pack=? AND status='pending'",
            (pack_id,)
        ) as cur:
            active = (await cur.fetchone())[0]

        if active:
            logger.warning(f"Пропускаємо оновлення паку {pack_id} — є активні платежі")
            return False

        # Upsert паку
        await db.execute("""
            INSERT INTO packs(pack_id, name, price, delivery_type)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(pack_id) DO UPDATE SET
                name=excluded.name,
                price=excluded.price,
                delivery_type=excluded.delivery_type
        """, (pack_id, name, max(price, 0.01), delivery_type))

        # Оновлюємо контент (видаляємо старий, вставляємо новий)
        await db.execute("DELETE FROM pack_codes WHERE pack_id=?", (pack_id,))
        if content:
            await db.execute(
                "INSERT INTO pack_codes(pack_id, code) VALUES (?,?)",
                (pack_id, content)
            )

        await db.commit()

    logger.info(f"Пак оновлено: {pack_id} | {name} | {price} | {delivery_type}")
    return True

async def remove_outdated_auto_packs(current_ids: list[str]):
    """
    Видаляє авто-паки яких більше немає в парсері
    (щоб не накопичувались старі акції).
    Не чіпає паки без префіксу 'auto_'.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT pack_id FROM packs WHERE pack_id LIKE 'auto_%'"
        ) as cur:
            existing = [r[0] for r in await cur.fetchall()]

        to_remove = [pid for pid in existing if pid not in current_ids]
        for pid in to_remove:
            # Не видаляємо якщо є активні платежі
            async with db.execute(
                "SELECT COUNT(*) FROM pending_payments WHERE pack=? AND status='pending'", (pid,)
            ) as cur:
                if (await cur.fetchone())[0]:
                    continue
            await db.execute("DELETE FROM packs WHERE pack_id=?", (pid,))
            await db.execute("DELETE FROM pack_codes WHERE pack_id=?", (pid,))
            logger.info(f"Видалено застарілий авто-пак: {pid}")

        await db.commit()

# ============================================================
# ОБРОБКА РЕЗУЛЬТАТІВ ПАРСЕРІВ
# ============================================================
async def sync_ali_deals(deals: list[dict]) -> int:
    """Синхронізує AliExpress акції в БД. Повертає кількість оновлених."""
    count = 0
    for i, deal in enumerate(deals[:10]):  # максимум 10 акцій AliExpress
        pack_id = f"auto_ali_{i+1}"
        title   = deal.get("title", "AliExpress Deal")
        price   = deal.get("price", 1.0)
        url     = deal.get("url", "")
        discount = deal.get("discount", "")

        if not url:
            continue

        # Ціна в боті = невелика комісія поверх ціни або фіксована
        # Логіка: якщо ціна товару < $5 — беремо $1 за "пак з посиланням"
        # Якщо $5-50 — беремо $2
        # Більше $50 — $3
        bot_price = 1.0 if price < 5 else (2.0 if price < 50 else 3.0)

        name = f"🛒 {title}"
        if discount:
            name += f" ({discount} знижка)"
        note = deal.get("note", "")

        ok = await upsert_pack(
            pack_id=pack_id,
            name=name,
            price=bot_price,
            delivery_type="link",
            content=url,
            note=note
        )
        if ok:
            count += 1

    return count

async def sync_vpn_deals(deals: list[dict]) -> int:
    """Синхронізує VPN акції в БД. Повертає кількість оновлених."""
    count = 0
    nord_count = surf_count = 0

    for deal in deals:
        source = deal.get("source", "")
        url    = deal.get("url", "")
        code   = deal.get("code", "")  # промокод якщо є (з Admitad)

        if not url and not code:
            continue

        # Генеруємо унікальний pack_id
        if "nord" in source:
            nord_count += 1
            pack_id = f"auto_nord_{nord_count}"
        elif "surf" in source:
            surf_count += 1
            pack_id = f"auto_surf_{surf_count}"
        elif "admitad" in source:
            pack_id = f"auto_admitad_{count+1}"
        else:
            continue

        title    = deal.get("title", "VPN Deal")
        discount = deal.get("discount", "")
        note     = deal.get("note", "")

        name = title
        if discount and discount not in title:
            name += f" — {discount}"

        # Якщо є промокод — тип "code", якщо тільки посилання — тип "link"
        if code:
            delivery_type = "code"
            content = f"Промокод: {code}\nПосилання: {url}"
        else:
            delivery_type = "link"
            content = url

        # Ціна в боті за "доступ до акції" — символічна
        bot_price = 1.0

        ok = await upsert_pack(
            pack_id=pack_id,
            name=name,
            price=bot_price,
            delivery_type=delivery_type,
            content=content,
            note=note
        )
        if ok:
            count += 1

    return count

# ============================================================
# ГОЛОВНИЙ ЦИКЛ ОНОВЛЕННЯ
# ============================================================
async def run_parsers_once(bot=None) -> dict:
    """
    Запускає всі парсери один раз і синхронізує БД.
    Повертає звіт: {"ali": N, "vpn": N, "errors": [...]}
    """
    from parser_ali import get_ali_deals
    from parser_vpn import get_vpn_deals

    report = {"ali": 0, "vpn": 0, "errors": [], "ts": datetime.now().strftime("%d.%m.%Y %H:%M")}

    # --- AliExpress ---
    try:
        logger.info("Запуск парсера AliExpress...")
        ali_deals = await get_ali_deals(limit=8)
        if ali_deals:
            report["ali"] = await sync_ali_deals(ali_deals)
            logger.info(f"AliExpress: синхронізовано {report['ali']} паків")
        else:
            report["errors"].append("AliExpress: не знайдено акцій")
    except Exception as e:
        err = f"AliExpress парсер помилка: {e}"
        logger.error(err)
        report["errors"].append(err)

    # --- VPN ---
    try:
        logger.info("Запуск парсера VPN...")
        vpn_deals = await get_vpn_deals()
        if vpn_deals:
            report["vpn"] = await sync_vpn_deals(vpn_deals)
            logger.info(f"VPN: синхронізовано {report['vpn']} паків")
        else:
            report["errors"].append("VPN: не знайдено акцій")
    except Exception as e:
        err = f"VPN парсер помилка: {e}"
        logger.error(err)
        report["errors"].append(err)

    # --- Очищення застарілих авто-паків ---
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT pack_id FROM packs WHERE pack_id LIKE 'auto_%'") as cur:
                current_auto = [r[0] for r in await cur.fetchall()]
        await remove_outdated_auto_packs(current_auto)
    except Exception as e:
        logger.error(f"Очищення авто-паків: {e}")

    # --- Сповіщення адміна ---
    if bot and ADMIN_ID:
        total = report["ali"] + report["vpn"]
        errors_text = "\n".join(f"⚠️ {e}" for e in report["errors"]) if report["errors"] else "немає"
        try:
            await bot.send_message(
                ADMIN_ID,
                f"🔄 *Автооновлення товарів*\n\n"
                f"🛒 AliExpress: {report['ali']} паків\n"
                f"🔒 VPN: {report['vpn']} паків\n"
                f"📅 {report['ts']}\n\n"
                f"Помилки: {errors_text}",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    return report

async def scheduler_worker(bot=None):
    """
    Фоновий воркер — запускає парсери кожні N годин.
    Підключається до бота через asyncio.create_task в main().
    """
    interval = UPDATE_INTERVAL_HOURS * 3600
    logger.info(f"Scheduler запущено (інтервал: {UPDATE_INTERVAL_HOURS} год)")

    # Перший запуск одразу при старті бота (через 30 сек щоб БД встигла ініціалізуватись)
    await asyncio.sleep(30)
    await run_parsers_once(bot=bot)

    while True:
        await asyncio.sleep(interval)
        await run_parsers_once(bot=bot)
