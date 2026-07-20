"""
PromoHub Bot v3
+ Мультимовність (uk/ru/en)
+ Реферальна система з виплатами (безпечний варіант: баланс + ручне підтвердження адміном)
+ Docker-ready (всі шляхи та налаштування через env)
"""

import asyncio
import aiosqlite
import aiohttp
import time
import qrcode
import os
import shutil
import logging
import hmac
import hashlib
import json
import re
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from strings import t  # мультимовні рядки
from scheduler import scheduler_worker  # автооновлення товарів

# ============================================================
# ЛОГУВАННЯ
# ============================================================
class RedactingFilter(logging.Filter):
    ADDR_PATTERN = re.compile(r"\b(T[a-zA-Z0-9]{25,40}|0x[a-fA-F0-9]{40})\b")
    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = self.ADDR_PATTERN.sub(lambda m: m.group(0)[:6] + "…" + m.group(0)[-4:], record.msg)
        return True

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logger.addFilter(RedactingFilter())

# ============================================================
# ENV
# ============================================================
load_dotenv()
BOT_TOKEN        = os.getenv("BOT_TOKEN")
ADMIN_ID         = int(os.getenv("ADMIN_ID"))
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY", "")
BINANCE_API_KEY  = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET   = os.getenv("BINANCE_SECRET", "")
BSCSCAN_API_KEY  = os.getenv("BSCSCAN_API_KEY", "")
ADDR_TRC20       = os.getenv("CRYPTO_ADDRESS_TRC20", "")
ADDR_TON         = os.getenv("CRYPTO_ADDRESS_TON", "")
ADDR_BEP20       = os.getenv("CRYPTO_ADDRESS_BEP20", "")

# Реферальні налаштування
REF_PERCENT      = float(os.getenv("REF_PERCENT", "10"))        # % від покупки рефералу
REF_MIN_WITHDRAW = float(os.getenv("REF_MIN_WITHDRAW", "2.0"))  # мінімум для виплати USDT

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не знайдено в .env!")
if not ADDR_TRC20 and not ADDR_TON and not ADDR_BEP20:
    raise ValueError("Має бути задана хоча б одна крипто-адреса в .env!")

bot = Bot(BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

DB_PATH           = os.getenv("DB_PATH", "db.sqlite3")
AMOUNT_TOLERANCE  = 0.99
OVERPAY_ALERT     = 1.05
PENDING_TIMEOUT   = 3600

# ============================================================
# PDF ШРИФТ
# ============================================================
_FONT_NAME = "Helvetica"
for _fp in [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]:
    if os.path.exists(_fp):
        try:
            pdfmetrics.registerFont(TTFont("UnicodeFont", _fp))
            _FONT_NAME = "UnicodeFont"
            break
        except Exception:
            pass
if _FONT_NAME == "Helvetica":
    logger.warning("Unicode-шрифт не знайдено! Кирилиця в PDF може не відображатись. apt install fonts-dejavu")

# ============================================================
# RATE LIMITING
# ============================================================
_rate_state = defaultdict(list)

def is_rate_limited(user_id: int) -> bool:
    now = time.time()
    _rate_state[user_id] = [t_ for t_ in _rate_state[user_id] if now - t_ < 5]
    if len(_rate_state[user_id]) >= 5:
        return True
    _rate_state[user_id].append(now)
    return False

@dp.message.outer_middleware()
async def rl_msg(handler, event, data):
    lang = await get_user_lang(event.from_user.id)
    if is_rate_limited(event.from_user.id):
        await event.answer(t(lang, "rate_limit"))
        return
    return await handler(event, data)

@dp.callback_query.outer_middleware()
async def rl_cb(handler, event, data):
    lang = await get_user_lang(event.from_user.id)
    if is_rate_limited(event.from_user.id):
        await event.answer(t(lang, "rate_limit"), show_alert=True)
        return
    return await handler(event, data)

# ============================================================
# FSM
# ============================================================
class AdminStates(StatesGroup):
    waiting_broadcast_text   = State()
    waiting_new_pack_id      = State()
    waiting_new_pack_name    = State()
    waiting_new_pack_price   = State()
    waiting_new_pack_dtype   = State()   # вибір типу видачі
    waiting_new_pack_codes   = State()
    waiting_add_codes_text   = State()

class UserStates(StatesGroup):
    waiting_ref_address = State()

# ============================================================
# БАЗА ДАНИХ
# ============================================================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("""CREATE TABLE IF NOT EXISTS purchases(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            pack TEXT, amount REAL, method TEXT, created_at INTEGER)""")
        await db.execute("CREATE TABLE IF NOT EXISTS income(amount REAL, method TEXT, created_at INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS tx(hash TEXT UNIQUE, created_at INTEGER)")
        await db.execute("""CREATE TABLE IF NOT EXISTS pending_payments(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            pack TEXT, method TEXT, order_id TEXT, amount REAL,
            created_at INTEGER, status TEXT DEFAULT 'pending')""")
        await db.execute("""CREATE TABLE IF NOT EXISTS packs(
            pack_id TEXT PRIMARY KEY, name TEXT, price REAL,
            delivery_type TEXT DEFAULT 'pdf')""")
        # delivery_type: 'pdf' | 'code' | 'link'
        # pdf  — генерує PDF з кодами (як раніше)
        # code — надсилає текстовий код/посилання прямо в повідомленні (для Admitad/VPN)
        # link — надсилає кнопку з URL (для партнерських посилань)
        await db.execute("PRAGMA table_info(packs)")  # no-op, just ensure WAL is active
        # Міграція: якщо таблиця вже існує без колонки delivery_type — додаємо її
        try:
            await db.execute("ALTER TABLE packs ADD COLUMN delivery_type TEXT DEFAULT 'pdf'")
            await db.commit()
            logger.info("Міграція: додано колонку delivery_type до packs")
        except Exception:
            pass  # колонка вже існує
        await db.execute("""CREATE TABLE IF NOT EXISTS pack_codes(
            id INTEGER PRIMARY KEY AUTOINCREMENT, pack_id TEXT, code TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, first_seen INTEGER, lang TEXT DEFAULT 'uk')""")
        await db.execute("""CREATE TABLE IF NOT EXISTS ref(
            user_id INTEGER PRIMARY KEY, ref_id INTEGER)""")
        # Реферальні баланси та запити виплат
        await db.execute("""CREATE TABLE IF NOT EXISTS ref_balance(
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0.0,
            total_earned REAL DEFAULT 0.0,
            total_paid REAL DEFAULT 0.0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS ref_payouts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, amount REAL, address TEXT,
            status TEXT DEFAULT 'pending',
            created_at INTEGER, processed_at INTEGER)""")
        await db.commit()

        async with db.execute("SELECT COUNT(*) FROM packs") as cur:
            if (await cur.fetchone())[0] == 0:
                # (pack_id, name, price, delivery_type, codes)
                defaults = [
                    ("pack1", "Pack 1 — AliExpress + Rozetka", 1.0, "pdf",
                     ["AliExpress NEWUSER", "Rozetka SALE10"]),
                    ("pack2", "Pack 2 — Glovo + Bolt", 1.0, "pdf",
                     ["Glovo FOOD10", "Bolt RIDE5"]),
                    ("pack3", "Pack 3 — АТБ + WOG", 1.0, "pdf",
                     ["АТБ ATB5", "WOG FUEL7"]),
                    ("pack4", "🚀 Mega Pack — VPN + Netflix + Spotify", 3.0, "pdf",
                     ["VPN VIP", "Netflix VIP", "Spotify FREE30"]),
                    # Приклад VPN через Admitad (тип: code — видає текстовий код)
                    # ("vpn1", "🔒 NordVPN 1 рік зі знижкою 68%", 5.0, "code",
                    #  ["ТВІЙ_ADMITAD_КОД_ТУТ"]),
                    # Приклад через реферальне посилання (тип: link — видає кнопку)
                    # ("vpn2", "🔒 NordVPN — активація через посилання", 4.0, "link",
                    #  ["https://go.nordvpn.net/твоє_посилання"]),
                ]
                for pack_id, name, price, dtype, codes in defaults:
                    await db.execute(
                        "INSERT INTO packs(pack_id, name, price, delivery_type) VALUES (?,?,?,?)",
                        (pack_id, name, price, dtype)
                    )
                    for code in codes:
                        await db.execute("INSERT INTO pack_codes(pack_id,code) VALUES (?,?)", (pack_id, code))
                await db.commit()
    logger.info("БД ініціалізована")

# ============================================================
# МОВА КОРИСТУВАЧА
# ============================================================
_lang_cache = {}

async def get_user_lang(user_id: int) -> str:
    if user_id in _lang_cache:
        return _lang_cache[user_id]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT lang FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
    lang = row[0] if row else "uk"
    _lang_cache[user_id] = lang
    return lang

async def set_user_lang(user_id: int, lang: str):
    _lang_cache[user_id] = lang
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users(user_id, first_seen, lang) VALUES (?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET lang=excluded.lang",
            (user_id, int(time.time()), lang)
        )
        await db.commit()

async def track_user(user_id: int, lang: str = "uk"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(user_id, first_seen, lang) VALUES (?,?,?)",
            (user_id, int(time.time()), lang)
        )
        await db.commit()

# ============================================================
# КЕШ ПАКІВ
# ============================================================
_packs_cache = {"data": None, "ts": 0}
PACKS_CACHE_TTL = 15

async def get_packs(force: bool = False) -> dict:
    now = time.time()
    if not force and _packs_cache["data"] and now - _packs_cache["ts"] < PACKS_CACHE_TTL:
        return _packs_cache["data"]
    result = {}
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT pack_id, name, price, delivery_type FROM packs") as cur:
            rows = await cur.fetchall()
        for pack_id, name, price, delivery_type in rows:
            async with db.execute("SELECT code FROM pack_codes WHERE pack_id=?", (pack_id,)) as cur:
                codes = [r[0] for r in await cur.fetchall()]
            result[pack_id] = {
                "name": name,
                "price": price,
                "codes": codes,
                "delivery_type": delivery_type or "pdf",  # fallback для старих записів
            }
    _packs_cache["data"] = result
    _packs_cache["ts"] = now
    return result

def invalidate_packs_cache():
    _packs_cache["data"] = None

# ============================================================
# BACKUP
# ============================================================
async def backup_worker():
    os.makedirs("backups", exist_ok=True)
    while True:
        await asyncio.sleep(86400)
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = f"backups/db_{ts}.sqlite3"
            async with aiosqlite.connect(DB_PATH) as src:
                async with aiosqlite.connect(dest) as dst:
                    await src.backup(dst)
            backups = sorted(f for f in os.listdir("backups") if f.endswith(".sqlite3"))
            for old in backups[:-7]:
                os.remove(os.path.join("backups", old))
            logger.info(f"Backup: {dest}")
        except Exception as e:
            logger.error(f"Backup помилка: {e}")

# ============================================================
# PDF + QR (в пам'яті)
# ============================================================
def create_qr_bytes(address: str) -> bytes:
    import io
    buf = io.BytesIO()
    qrcode.make(address).save(buf, format="PNG")
    return buf.getvalue()

def create_pdf_bytes(title: str, codes: list) -> bytes:
    import io
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf)
    s = getSampleStyleSheet()
    s["Title"].fontName = _FONT_NAME
    s["Normal"].fontName = _FONT_NAME
    content = [Paragraph(f"PromoHub — {title}", s["Title"]), Spacer(1, 12)]
    for code in codes:
        content.append(Paragraph(f"✅ {code}", s["Normal"]))
        content.append(Spacer(1, 6))
    doc.build(content)
    return buf.getvalue()

# ============================================================
# RETRY
# ============================================================
async def fetch_json(method: str, url: str, retries: int = 3, **kwargs):
    for attempt in range(1, retries + 1):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.request(method, url, timeout=aiohttp.ClientTimeout(total=15), **kwargs) as r:
                    if r.status >= 500:
                        raise aiohttp.ClientError(f"HTTP {r.status}")
                    return await r.json()
        except Exception as e:
            if attempt == retries:
                raise
            await asyncio.sleep(2 * attempt)

# ============================================================
# РЕФЕРАЛЬНА СИСТЕМА
# ============================================================
async def get_ref_balance(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT balance, total_earned, total_paid FROM ref_balance WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    if row:
        return {"balance": row[0], "total_earned": row[1], "total_paid": row[2]}
    return {"balance": 0.0, "total_earned": 0.0, "total_paid": 0.0}

async def accrue_referral(buyer_id: int, purchase_amount: float):
    """Нараховує % рефереру при покупці"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT ref_id FROM ref WHERE user_id=?", (buyer_id,)) as cur:
            row = await cur.fetchone()
    if not row:
        return
    ref_id = row[0]
    reward = round(purchase_amount * REF_PERCENT / 100, 6)
    if reward <= 0:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO ref_balance(user_id, balance, total_earned, total_paid)
            VALUES (?, ?, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                balance = balance + excluded.balance,
                total_earned = total_earned + excluded.total_earned
        """, (ref_id, reward, reward))
        await db.commit()

    lang = await get_user_lang(ref_id)
    try:
        await bot.send_message(ref_id, t(lang, "ref_earned", amount=reward))
    except Exception:
        pass
    logger.info(f"Реф. нарахування: {reward} USDT → user={ref_id} (за покупку user={buyer_id})")

async def get_ref_invited_count(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM ref WHERE ref_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
    return row[0] if row else 0

# ============================================================
# ВИДАЧА ПАКУ (підтримує pdf / code / link)
# ============================================================
async def deliver_pack(user_id: int, pack_id: str, amount: float, method: str, expected: float = None):
    lang = await get_user_lang(user_id)
    packs = await get_packs()
    pack = packs.get(pack_id)
    if not pack:
        await bot.send_message(user_id, t(lang, "deliver_pack_deleted"))
        logger.error(f"КРИТИЧНО: оплата {amount} від {user_id} за відсутній пак {pack_id}")
        try:
            await bot.send_message(ADMIN_ID,
                f"🚨 Оплата за видалений пак!\nuser={user_id}, pack={pack_id}, amount={amount}")
        except Exception:
            pass
        return False

    dtype = pack.get("delivery_type", "pdf")
    codes = pack.get("codes", [])

    try:
        if dtype == "pdf":
            # Генерує PDF з усіма кодами і надсилає файлом
            pdf = create_pdf_bytes(pack["name"], codes)
            await bot.send_document(
                user_id,
                types.BufferedInputFile(pdf, filename=f"{pack_id}.pdf"),
                caption=t(lang, "deliver_ok", name=pack["name"]),
                parse_mode="Markdown"
            )

        elif dtype == "code":
            # Надсилає коди/текст прямо в повідомленні (для Admitad-кодів, VPN-ключів тощо)
            # Якщо кодів кілька — видає всі в одному повідомленні
            codes_text = "\n".join(f"`{c}`" for c in codes) if codes else "_(немає кодів)_"
            await bot.send_message(
                user_id,
                t(lang, "deliver_ok", name=pack["name"]) + f"\n\n{codes_text}",
                parse_mode="Markdown"
            )

        elif dtype == "link":
            # Надсилає кнопку з URL (для партнерських/реферальних посилань)
            # Перший елемент codes[] — це URL
            url = codes[0] if codes else None
            if not url:
                raise ValueError("Відсутнє посилання в pack_codes")
            await bot.send_message(
                user_id,
                t(lang, "deliver_ok", name=pack["name"]),
                reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(
                        text=t(lang, "deliver_link_btn"),
                        url=url
                    )]
                ]),
                parse_mode="Markdown"
            )

        else:
            logger.error(f"Невідомий delivery_type '{dtype}' для паку {pack_id}")
            await bot.send_message(user_id, t(lang, "deliver_error"))
            return False

    except Exception as e:
        logger.error(f"Помилка видачі (dtype={dtype}): {e}")
        await bot.send_message(user_id, t(lang, "deliver_error"))
        # Не повертаємо False — оплату все одно фіксуємо в БД нижче

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO purchases(user_id,pack,amount,method,created_at) VALUES (?,?,?,?,?)",
            (user_id, pack_id, amount, method, int(time.time())))
        await db.execute(
            "INSERT INTO income(amount,method,created_at) VALUES (?,?,?)",
            (amount, method, int(time.time())))
        await db.commit()

    # Нарахування реферального %
    await accrue_referral(user_id, amount)

    note = f"💰 Нова покупка!\nUser: {user_id}\nПак: {pack['name']}\nСума: {amount} ({method})"
    if expected and amount > expected * OVERPAY_ALERT:
        note += f"\n⚠️ Переплата! Очікувалось {expected}"
    try:
        await bot.send_message(ADMIN_ID, note)
    except Exception:
        pass
    return True

# ============================================================
# TRC20 / TON / BEP20 ПЕРЕВІРКА
# ============================================================
USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_BEP20_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"

def amount_ok(received: float, expected: float) -> bool:
    return received >= expected * AMOUNT_TOLERANCE

async def mark_tx_used(tx_hash: str) -> bool:
    if not tx_hash:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO tx(hash, created_at) VALUES (?,?)", (tx_hash, int(time.time())))
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def check_trc20(expected: float):
    if not ADDR_TRC20:
        return False
    headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY} if TRONGRID_API_KEY else {}
    try:
        data = await fetch_json("GET",
            f"https://api.trongrid.io/v1/accounts/{ADDR_TRC20}/transactions/trc20",
            params={"limit": 20, "contract_address": USDT_TRC20_CONTRACT},
            headers=headers)
    except Exception:
        return False
    for tx in data.get("data", []):
        if tx.get("to") != ADDR_TRC20: continue
        if time.time() - tx.get("block_timestamp", 0) / 1000 > PENDING_TIMEOUT: continue
        amount = int(tx.get("value", 0)) / 1_000_000
        if not amount_ok(amount, expected): continue
        if await mark_tx_used(tx.get("transaction_id", "")): return amount
    return False

async def check_ton(expected: float):
    if not ADDR_TON:
        return False
    try:
        data = await fetch_json("GET", "https://toncenter.com/api/v2/getTransactions",
            params={"address": ADDR_TON, "limit": 20})
    except Exception:
        return False
    for tx in data.get("result", []):
        in_msg = tx.get("in_msg", {})
        if not in_msg or in_msg.get("destination") != ADDR_TON: continue
        if time.time() - tx.get("utime", 0) > PENDING_TIMEOUT: continue
        amount = int(in_msg.get("value", 0)) / 1_000_000_000
        if not amount_ok(amount, expected): continue
        if await mark_tx_used(tx.get("transaction_id", {}).get("hash", "")): return amount
    return False

async def check_bep20(expected: float):
    if not ADDR_BEP20 or not BSCSCAN_API_KEY:
        return False
    try:
        data = await fetch_json("GET", "https://api.bscscan.com/api", params={
            "module": "account", "action": "tokentx",
            "contractaddress": USDT_BEP20_CONTRACT,
            "address": ADDR_BEP20, "sort": "desc", "apikey": BSCSCAN_API_KEY
        })
    except Exception:
        return False
    for tx in data.get("result", [])[:20]:
        if tx.get("to", "").lower() != ADDR_BEP20.lower(): continue
        if time.time() - int(tx.get("timeStamp", 0)) > PENDING_TIMEOUT: continue
        amount = int(tx.get("value", 0)) / 10**18
        if not amount_ok(amount, expected): continue
        if await mark_tx_used(tx.get("hash", "")): return amount
    return False

async def check_binance(order_id: str, expected: float):
    if not BINANCE_API_KEY:
        return False
    nonce = os.urandom(16).hex()
    ts = str(int(time.time() * 1000))
    body = json.dumps({"merchantTradeNo": order_id}, separators=(",", ":"))
    sig = hmac.new(BINANCE_SECRET.encode(), f"{ts}\n{nonce}\n{body}\n".encode(), hashlib.sha512).hexdigest().upper()
    headers = {"Content-Type": "application/json", "BinancePay-Timestamp": ts,
               "BinancePay-Nonce": nonce, "BinancePay-Certificate-SN": BINANCE_API_KEY,
               "BinancePay-Signature": sig}
    try:
        res = await fetch_json("POST", "https://bpay.binanceapi.com/binancepay/openapi/v2/order/query",
            headers=headers, data=body, retries=2)
    except Exception:
        return False
    data = res.get("data", {})
    if data.get("status") != "PAID":
        return False
    paid = float(data.get("transactAmount") or data.get("orderAmount") or expected)
    return paid if amount_ok(paid, expected) else False

# ============================================================
# PAYMENT WORKER
# ============================================================
async def claim_pending(pid: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE pending_payments SET status='processing' WHERE id=? AND status='pending'", (pid,))
        await db.commit()
        return cur.rowcount > 0

async def payment_worker():
    logger.info("Payment worker запущено")
    while True:
        await asyncio.sleep(30)
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT id,user_id,pack,method,order_id,amount,created_at FROM pending_payments WHERE status='pending'"
                ) as cur:
                    pending = await cur.fetchall()

            for pid, user_id, pack_id, method, order_id, amount, created_at in pending:
                if time.time() - created_at > PENDING_TIMEOUT:
                    if await claim_pending(pid):
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute("DELETE FROM pending_payments WHERE id=?", (pid,))
                            await db.commit()
                        lang = await get_user_lang(user_id)
                        try:
                            await bot.send_message(user_id, t(lang, "pay_timeout"))
                        except Exception:
                            pass
                    continue

                paid = False
                if method == "trc20":    paid = await check_trc20(amount)
                elif method == "ton":    paid = await check_ton(amount)
                elif method == "bep20":  paid = await check_bep20(amount)
                elif method == "binance": paid = await check_binance(order_id, amount)

                if paid:
                    if not await claim_pending(pid):
                        continue
                    labels = {"trc20": "USDT-TRC20", "ton": "TON", "bep20": "USDT-BEP20", "binance": "BinancePay"}
                    ok = await deliver_pack(user_id, pack_id, paid, labels[method], expected=amount)
                    async with aiosqlite.connect(DB_PATH) as db:
                        if ok:
                            await db.execute("DELETE FROM pending_payments WHERE id=?", (pid,))
                        else:
                            await db.execute(
                                "UPDATE pending_payments SET status=? WHERE id=?",
                                (f"failed_paid_{paid}", pid))
                        await db.commit()
        except Exception as e:
            logger.error(f"Payment worker: {e}")

# ============================================================
# КЛАВІАТУРИ
# ============================================================
async def main_menu_kb(user_id: int) -> types.InlineKeyboardMarkup:
    lang = await get_user_lang(user_id)
    packs = await get_packs()
    rows = [
        [types.InlineKeyboardButton(text=f"🎁 {p['name']} — {p['price']} USDT", callback_data=f"buy_{pid}")]
        for pid, p in packs.items()
    ]
    rows.append([types.InlineKeyboardButton(text="🌍 Мова / Lang", callback_data="choose_lang")])
    if user_id == ADMIN_ID:
        rows.append([types.InlineKeyboardButton(text=t(lang, "admin_panel_btn"), callback_data="admin_panel")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)

def lang_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🇺🇦 Українська", callback_data="lang_uk")],
        [types.InlineKeyboardButton(text="🇷🇺 Русский",    callback_data="lang_ru")],
        [types.InlineKeyboardButton(text="🇬🇧 English",    callback_data="lang_en")],
    ])

def payment_methods_kb(pack_id: str, lang: str) -> types.InlineKeyboardMarkup:
    rows = []
    if ADDR_TRC20:  rows.append([types.InlineKeyboardButton(text=t(lang,"pay_trc20"), callback_data=f"pay_trc20_{pack_id}")])
    if ADDR_TON:    rows.append([types.InlineKeyboardButton(text=t(lang,"pay_ton"),   callback_data=f"pay_ton_{pack_id}")])
    if ADDR_BEP20:  rows.append([types.InlineKeyboardButton(text=t(lang,"pay_bep20"),callback_data=f"pay_bep20_{pack_id}")])
    if BINANCE_API_KEY: rows.append([types.InlineKeyboardButton(text=t(lang,"pay_binance"),callback_data=f"pay_binance_{pack_id}")])
    rows.append([types.InlineKeyboardButton(text=t(lang,"back"), callback_data="back_start")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)

# ============================================================
# КОМАНДИ ЮЗЕРА
# ============================================================
@dp.message(Command("start"))
async def start(msg: types.Message):
    await track_user(msg.from_user.id)
    lang = await get_user_lang(msg.from_user.id)
    args = msg.text.split()
    if len(args) > 1:
        try:
            ref_id = int(args[1])
            if ref_id != msg.from_user.id:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("INSERT OR IGNORE INTO ref VALUES (?,?)", (msg.from_user.id, ref_id))
                    await db.commit()
        except ValueError:
            pass
    await msg.answer(t(lang, "welcome"), reply_markup=await main_menu_kb(msg.from_user.id), parse_mode="Markdown")

@dp.message(Command("myorders"))
async def my_orders(msg: types.Message):
    lang = await get_user_lang(msg.from_user.id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT pack, amount, method, created_at FROM purchases WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
            (msg.from_user.id,)
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        await msg.answer(t(lang, "myorders_empty"))
        return
    packs = await get_packs()
    text = t(lang, "myorders_header")
    for pack_id, amount, method, created_at in rows:
        name = packs.get(pack_id, {}).get("name") or t(lang, "myorders_deleted_pack", pack_id=pack_id)
        date = datetime.fromtimestamp(created_at).strftime("%d.%m.%Y %H:%M")
        text += f"• {name} — {amount} ({method}) — {date}\n"
    await msg.answer(text, parse_mode="Markdown")

@dp.message(Command("myref"))
async def my_ref(msg: types.Message):
    lang = await get_user_lang(msg.from_user.id)
    user_id = msg.from_user.id
    bal = await get_ref_balance(user_id)
    invited = await get_ref_invited_count(user_id)

    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"

    text = t(lang, "ref_link_header") + f"`{ref_link}`\n\n"
    text += t(lang, "ref_stats", invited=invited, balance=round(bal["balance"], 4), paid=round(bal["total_paid"], 4))
    text += t(lang, "ref_min_withdraw", min=REF_MIN_WITHDRAW)

    kb_rows = []
    if bal["balance"] >= REF_MIN_WITHDRAW:
        kb_rows.append([types.InlineKeyboardButton(
            text=t(lang, "ref_request_btn", balance=round(bal["balance"], 4)),
            callback_data="ref_withdraw"
        )])
    await msg.answer(text, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb_rows) if kb_rows else None,
                     parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == "ref_withdraw")
async def ref_withdraw_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    lang = await get_user_lang(call.from_user.id)
    user_id = call.from_user.id

    # Перевіряємо чи немає вже активного запиту
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM ref_payouts WHERE user_id=? AND status='pending'", (user_id,)
        ) as cur:
            if await cur.fetchone():
                await call.message.answer(t(lang, "ref_already_pending"))
                return

    bal = await get_ref_balance(user_id)
    if bal["balance"] < REF_MIN_WITHDRAW:
        await call.message.answer(t(lang, "ref_no_balance", min=REF_MIN_WITHDRAW))
        return

    await state.update_data(withdraw_amount=bal["balance"])
    await state.set_state(UserStates.waiting_ref_address)
    await call.message.answer(t(lang, "ref_need_address"))

TRC20_ADDR_PATTERN = re.compile(r"^T[a-zA-Z0-9]{33}$")

@dp.message(StateFilter(UserStates.waiting_ref_address))
async def ref_withdraw_address(msg: types.Message, state: FSMContext):
    lang = await get_user_lang(msg.from_user.id)
    address = msg.text.strip()

    if not TRC20_ADDR_PATTERN.match(address):
        await msg.answer(t(lang, "ref_invalid_address"))
        return

    data = await state.get_data()
    amount = data["withdraw_amount"]
    user_id = msg.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO ref_payouts(user_id, amount, address, status, created_at) VALUES (?,?,?,?,?)",
            (user_id, amount, address, "pending", int(time.time()))
        )
        # Заморожуємо баланс (обнуляємо) одразу при запиті
        await db.execute(
            "UPDATE ref_balance SET balance=0 WHERE user_id=?", (user_id,)
        )
        await db.commit()

    await state.clear()
    await msg.answer(t(lang, "ref_request_sent", amount=round(amount, 4)))

    try:
        await bot.send_message(
            ADMIN_ID,
            f"💸 Новий запит на реферальну виплату!\n\n"
            f"User: {user_id}\nСума: {round(amount, 4)} USDT\nАдреса: `{address}`\n\n"
            f"/pay_{user_id} — підтвердити виплату",
            parse_mode="Markdown"
        )
    except Exception:
        pass

@dp.message(lambda m: m.text and m.text.startswith("/pay_") and m.from_user.id == ADMIN_ID)
async def admin_confirm_payout(msg: types.Message):
    """Адмін пише /pay_USERID щоб підтвердити виплату після ручної відправки крипти"""
    try:
        target_id = int(msg.text.replace("/pay_", "").strip())
    except ValueError:
        await msg.answer("❌ Невірний формат. Використовуй /pay_USERID")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, amount, address FROM ref_payouts WHERE user_id=? AND status='pending' ORDER BY created_at DESC LIMIT 1",
            (target_id,)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        await msg.answer(f"❌ Активний запит для user {target_id} не знайдено.")
        return

    payout_id, amount, address = row

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE ref_payouts SET status='paid', processed_at=? WHERE id=?",
            (int(time.time()), payout_id)
        )
        await db.execute(
            "UPDATE ref_balance SET total_paid=total_paid+? WHERE user_id=?",
            (amount, target_id)
        )
        await db.commit()

    await msg.answer(f"✅ Виплата {amount} USDT → user {target_id} позначена як виконана.")
    lang = await get_user_lang(target_id)
    try:
        await bot.send_message(
            target_id,
            f"✅ Виплата {round(amount, 4)} USDT на адресу `{address}` підтверджена! Дякуємо! 🎉",
            parse_mode="Markdown"
        )
    except Exception:
        pass

# ============================================================
# ВИБІР МОВИ
# ============================================================
@dp.callback_query(lambda c: c.data == "choose_lang")
async def choose_lang(call: types.CallbackQuery):
    await call.answer()
    lang = await get_user_lang(call.from_user.id)
    await call.message.edit_text(t(lang, "choose_lang"), reply_markup=lang_kb())

@dp.callback_query(lambda c: c.data.startswith("lang_"))
async def set_lang(call: types.CallbackQuery):
    lang = call.data.replace("lang_", "")
    if lang not in ("uk", "ru", "en"):
        await call.answer()
        return
    await set_user_lang(call.from_user.id, lang)
    await call.answer(t(lang, "lang_set"), show_alert=True)
    await call.message.edit_text(t(lang, "welcome"), reply_markup=await main_menu_kb(call.from_user.id), parse_mode="Markdown")

# ============================================================
# ПОКУПКА
# ============================================================
@dp.callback_query(lambda c: c.data == "back_start")
async def back_start(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    lang = await get_user_lang(call.from_user.id)
    await call.message.edit_text(t(lang, "welcome"), reply_markup=await main_menu_kb(call.from_user.id), parse_mode="Markdown")

@dp.callback_query(lambda c: c.data.startswith("buy_"))
async def buy_choose_method(call: types.CallbackQuery):
    await call.answer()
    lang = await get_user_lang(call.from_user.id)
    pack_id = call.data.replace("buy_", "")
    packs = await get_packs()
    pack = packs.get(pack_id)
    if not pack:
        await call.message.answer(t(lang, "no_pack")); return
    if not pack["codes"]:
        await call.message.answer(t(lang, "pack_empty")); return
    await call.message.edit_text(
        t(lang, "choose_payment", name=pack["name"], price=pack["price"]),
        reply_markup=payment_methods_kb(pack_id, lang), parse_mode="Markdown"
    )

async def start_payment(call: types.CallbackQuery, pack_id: str, method: str, address: str, method_label: str):
    lang = await get_user_lang(call.from_user.id)
    packs = await get_packs()
    pack = packs.get(pack_id)
    if not pack:
        await call.message.answer(t(lang, "no_pack")); return
    user_id = call.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO pending_payments(user_id,pack,method,order_id,amount,created_at,status) VALUES (?,?,?,?,?,?,?)",
            (user_id, pack_id, method, f"{method}_{user_id}_{int(time.time())}", pack["price"], int(time.time()), "pending")
        )
        await db.commit()

    qr = create_qr_bytes(address)
    await bot.send_photo(
        user_id, types.BufferedInputFile(qr, filename="pay.png"),
        caption=t(lang, "pay_instructions", method=method_label, price=pack["price"], address=address),
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data.startswith("pay_trc20_"))
async def pay_trc20(call: types.CallbackQuery):
    await call.answer()
    lang = await get_user_lang(call.from_user.id)
    await start_payment(call, call.data.replace("pay_trc20_", ""), "trc20", ADDR_TRC20, t(lang, "pay_trc20"))

@dp.callback_query(lambda c: c.data.startswith("pay_ton_"))
async def pay_ton(call: types.CallbackQuery):
    await call.answer()
    lang = await get_user_lang(call.from_user.id)
    await start_payment(call, call.data.replace("pay_ton_", ""), "ton", ADDR_TON, t(lang, "pay_ton"))

@dp.callback_query(lambda c: c.data.startswith("pay_bep20_"))
async def pay_bep20(call: types.CallbackQuery):
    await call.answer()
    lang = await get_user_lang(call.from_user.id)
    await start_payment(call, call.data.replace("pay_bep20_", ""), "bep20", ADDR_BEP20, t(lang, "pay_bep20"))

@dp.callback_query(lambda c: c.data.startswith("pay_binance_"))
async def pay_binance(call: types.CallbackQuery):
    await call.answer()
    lang = await get_user_lang(call.from_user.id)
    pack_id = call.data.replace("pay_binance_", "")
    packs = await get_packs()
    pack = packs.get(pack_id)
    if not pack:
        await call.message.answer(t(lang, "no_pack")); return
    if not BINANCE_API_KEY:
        await call.message.answer(t(lang, "pay_binance_unavailable")); return

    await call.message.answer(t(lang, "pay_creating"))

    nonce = os.urandom(16).hex()
    ts = str(int(time.time() * 1000))
    order_id = f"PROMO_{call.from_user.id}_{int(time.time())}"
    body = json.dumps({
        "env": {"terminalType": "APP"}, "merchantTradeNo": order_id,
        "orderAmount": str(pack["price"]), "currency": "USDT",
        "description": f"PromoHub {pack_id}",
        "goods": {"goodsType": "02", "goodsCategory": "Z000",
                  "referenceGoodsId": pack_id, "goodsName": pack["name"]}
    }, separators=(",", ":"))
    sig = hmac.new(BINANCE_SECRET.encode(), f"{ts}\n{nonce}\n{body}\n".encode(), hashlib.sha512).hexdigest().upper()
    headers = {"Content-Type": "application/json", "BinancePay-Timestamp": ts,
               "BinancePay-Nonce": nonce, "BinancePay-Certificate-SN": BINANCE_API_KEY,
               "BinancePay-Signature": sig}
    try:
        res = await fetch_json("POST", "https://bpay.binanceapi.com/binancepay/openapi/v2/order",
            headers=headers, data=body, retries=2)
        if res.get("status") != "SUCCESS":
            await call.message.answer(f"❌ {res.get('errorMessage', 'Помилка')}"); return
        checkout_url = res["data"]["checkoutUrl"]
    except Exception as e:
        await call.message.answer(f"❌ {e}"); return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO pending_payments(user_id,pack,method,order_id,amount,created_at,status) VALUES (?,?,?,?,?,?,?)",
            (call.from_user.id, pack_id, "binance", order_id, pack["price"], int(time.time()), "pending")
        )
        await db.commit()

    await call.message.answer(
        t(lang, "pay_binance_msg", price=pack["price"]),
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=t(lang, "pay_binance_btn"), url=checkout_url)]
        ]),
        parse_mode="Markdown"
    )

# ============================================================
# АДМІН-ПАНЕЛЬ (спрощена, але повна)
# ============================================================
def admin_only(func):
    async def wrapper(event, *args, **kwargs):
        if event.from_user.id != ADMIN_ID:
            msg = "❌ Немає доступу"
            if isinstance(event, types.CallbackQuery):
                await event.answer(msg, show_alert=True)
            else:
                await event.answer(msg)
            return
        return await func(event, *args, **kwargs)
    return wrapper

@dp.callback_query(lambda c: c.data == "admin_panel")
@admin_only
async def admin_panel(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text("⚙️ *Адмін-панель*", parse_mode="Markdown",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="📊 Статистика",      callback_data="admin_stats")],
            [types.InlineKeyboardButton(text="📦 Паки",            callback_data="admin_packs")],
            [types.InlineKeyboardButton(text="📢 Розсилка",        callback_data="admin_broadcast")],
            [types.InlineKeyboardButton(text="💸 Запити виплат",   callback_data="admin_payouts")],
            [types.InlineKeyboardButton(text="◀️ Назад",           callback_data="back_start")],
        ])
    )

@dp.callback_query(lambda c: c.data == "admin_stats")
@admin_only
async def admin_stats(call: types.CallbackQuery):
    await call.answer()
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        sales   = (await (await db.execute("SELECT COUNT(*) FROM purchases")).fetchone())[0]
        income  = (await (await db.execute("SELECT SUM(amount) FROM income")).fetchone())[0] or 0.0
        users   = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        pending = (await (await db.execute("SELECT COUNT(*) FROM pending_payments WHERE status='pending'")).fetchone())[0]
        stuck   = (await (await db.execute("SELECT COUNT(*) FROM pending_payments WHERE status LIKE 'failed_%'")).fetchone())[0]
        i24h    = (await (await db.execute("SELECT SUM(amount) FROM income WHERE created_at>?", (now-86400,))).fetchone())[0] or 0.0
        s24h    = (await (await db.execute("SELECT COUNT(*) FROM purchases WHERE created_at>?", (now-86400,))).fetchone())[0]
        i7d     = (await (await db.execute("SELECT SUM(amount) FROM income WHERE created_at>?", (now-86400*7,))).fetchone())[0] or 0.0
        s7d     = (await (await db.execute("SELECT COUNT(*) FROM purchases WHERE created_at>?", (now-86400*7,))).fetchone())[0]
        ref_pending = (await (await db.execute("SELECT COUNT(*) FROM ref_payouts WHERE status='pending'")).fetchone())[0]
        ref_paid    = (await (await db.execute("SELECT SUM(amount) FROM ref_payouts WHERE status='paid'")).fetchone())[0] or 0.0
        async with db.execute("SELECT method, SUM(amount) FROM income GROUP BY method") as cur:
            by_method = await cur.fetchall()

    method_lines = "\n".join(f"   ├ {m}: {a:.2f}" for m, a in by_method) or "   └ —"
    stuck_line = f"\n🚨 Потребують ручної перевірки: {stuck}" if stuck else ""

    await call.message.edit_text(
        f"📊 *Статистика*\n\n"
        f"👥 Користувачів: {users}\n"
        f"🛒 Продажів: {sales}\n"
        f"💰 Дохід: {income:.2f} USDT\n{method_lines}\n\n"
        f"📅 *24 год:* {s24h} прод., {i24h:.2f} дохід\n"
        f"📅 *7 днів:* {s7d} прод., {i7d:.2f} дохід\n\n"
        f"⏳ Очікують оплати: {pending}{stuck_line}\n\n"
        f"💸 Реф. виплат очікує: {ref_pending}\n"
        f"💸 Реф. виплачено всього: {ref_paid:.2f} USDT",
        parse_mode="Markdown",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
        ])
    )

@dp.callback_query(lambda c: c.data == "admin_payouts")
@admin_only
async def admin_payouts(call: types.CallbackQuery):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, amount, address, created_at FROM ref_payouts WHERE status='pending' ORDER BY created_at"
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await call.message.edit_text(
            "💸 Немає активних запитів на виплату.",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
            ])
        )
        return

    text = "💸 *Запити на виплату:*\n\n"
    for user_id, amount, address, created_at in rows:
        date = datetime.fromtimestamp(created_at).strftime("%d.%m %H:%M")
        text += f"• User {user_id} — {round(amount,4)} USDT\n  `{address}`\n  {date}\n  → /pay_{user_id}\n\n"

    await call.message.edit_text(
        text, parse_mode="Markdown",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
        ])
    )

@dp.callback_query(lambda c: c.data == "admin_packs")
@admin_only
async def admin_packs(call: types.CallbackQuery):
    await call.answer()
    packs = await get_packs()
    rows = [
        [types.InlineKeyboardButton(text=f"{p['name']} ({len(p['codes'])} кодів)", callback_data=f"admin_pack_{pid}")]
        for pid, p in packs.items()
    ]
    rows += [
        [types.InlineKeyboardButton(text="➕ Новий пак", callback_data="admin_new_pack")],
        [types.InlineKeyboardButton(text="◀️ Назад",     callback_data="admin_panel")],
    ]
    await call.message.edit_text("📦 *Паки:*", parse_mode="Markdown",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=rows))

DTYPE_LABELS = {"pdf": "📄 PDF файл", "code": "🔑 Текстовий код", "link": "🔗 Посилання (кнопка)"}

@dp.callback_query(lambda c: c.data.startswith("admin_pack_") and not c.data.startswith("admin_pack_codes_"))
@admin_only
async def admin_pack_detail(call: types.CallbackQuery):
    await call.answer()
    pack_id = call.data.replace("admin_pack_", "")
    packs = await get_packs()
    pack = packs.get(pack_id)
    if not pack:
        await call.message.answer("❌ Не знайдено"); return

    dtype = pack.get("delivery_type", "pdf")
    dtype_label = DTYPE_LABELS.get(dtype, dtype)

    # Показуємо вміст залежно від типу
    if dtype == "link":
        content_label = "Посилання"
        content = pack["codes"][0] if pack["codes"] else "—"
        content_text = f"🔗 {content}"
    else:
        content_label = "Коди"
        content_text = "\n".join(f"• {c}" for c in pack["codes"]) or "—"

    await call.message.edit_text(
        f"📦 *{pack['name']}*\n"
        f"Ціна: {pack['price']} USDT\n"
        f"Тип видачі: {dtype_label}\n\n"
        f"{content_label}:\n{content_text}",
        parse_mode="Markdown",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(
                text="➕ Додати коди/посилання",
                callback_data=f"admin_addcodes_{pack_id}"
            )],
            [types.InlineKeyboardButton(
                text=f"🔄 Змінити тип ({dtype_label})",
                callback_data=f"admin_changedtype_{pack_id}"
            )],
            [types.InlineKeyboardButton(text="🗑 Видалити пак", callback_data=f"admin_delpack_{pack_id}")],
            [types.InlineKeyboardButton(text="◀️ Назад",        callback_data="admin_packs")],
        ])
    )

@dp.callback_query(lambda c: c.data.startswith("admin_addcodes_"))
@admin_only
async def admin_addcodes_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(pack_id=call.data.replace("admin_addcodes_", ""))
    await state.set_state(AdminStates.waiting_add_codes_text)
    await call.message.edit_text("✏️ Надішліть коди, кожен з нового рядка:")

@dp.message(StateFilter(AdminStates.waiting_add_codes_text))
@admin_only
async def admin_addcodes_finish(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    codes = [l.strip() for l in msg.text.split("\n") if l.strip()]
    if not codes:
        await msg.answer("❌ Не знайдено жодного коду."); return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM packs WHERE pack_id=?", (data["pack_id"],)) as cur:
            if not await cur.fetchone():
                await state.clear()
                await msg.answer("❌ Пак вже видалено."); return
        for code in codes:
            await db.execute("INSERT INTO pack_codes(pack_id,code) VALUES (?,?)", (data["pack_id"], code))
        await db.commit()
    invalidate_packs_cache()
    await state.clear()
    await msg.answer(f"✅ Додано {len(codes)} код(ів).")

@dp.callback_query(lambda c: c.data.startswith("admin_delpack_"))
@admin_only
async def admin_delpack(call: types.CallbackQuery):
    await call.answer()
    pack_id = call.data.replace("admin_delpack_", "")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM pending_payments WHERE pack=? AND status='pending'", (pack_id,)
        ) as cur:
            active = (await cur.fetchone())[0]
        if active:
            await call.message.edit_text(
                f"⚠️ {active} активних оплат за цей пак. Зачекайте і спробуйте знову.",
                reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_pack_{pack_id}")]
                ])
            ); return
        await db.execute("DELETE FROM packs WHERE pack_id=?", (pack_id,))
        await db.execute("DELETE FROM pack_codes WHERE pack_id=?", (pack_id,))
        await db.commit()
    invalidate_packs_cache()
    await call.message.edit_text(f"🗑 Пак `{pack_id}` видалено.", parse_mode="Markdown")

PACK_ID_RE = re.compile(r"^[a-zA-Z0-9_]{2,32}$")

@dp.callback_query(lambda c: c.data.startswith("admin_changedtype_"))
@admin_only
async def admin_change_dtype(call: types.CallbackQuery):
    await call.answer()
    pack_id = call.data.replace("admin_changedtype_", "")
    await call.message.edit_text(
        f"🔄 Оберіть новий тип видачі для паку `{pack_id}`:",
        parse_mode="Markdown",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="📄 PDF файл",          callback_data=f"admin_setdtype_{pack_id}_pdf")],
            [types.InlineKeyboardButton(text="🔑 Текстовий код",      callback_data=f"admin_setdtype_{pack_id}_code")],
            [types.InlineKeyboardButton(text="🔗 Посилання (кнопка)", callback_data=f"admin_setdtype_{pack_id}_link")],
            [types.InlineKeyboardButton(text="◀️ Назад",              callback_data=f"admin_pack_{pack_id}")],
        ])
    )

@dp.callback_query(lambda c: c.data.startswith("admin_setdtype_"))
@admin_only
async def admin_set_dtype(call: types.CallbackQuery):
    await call.answer()
    # формат: admin_setdtype_{pack_id}_{dtype}
    parts = call.data.replace("admin_setdtype_", "").rsplit("_", 1)
    if len(parts) != 2:
        await call.message.answer("❌ Помилка формату"); return
    pack_id, dtype = parts
    if dtype not in ("pdf", "code", "link"):
        await call.message.answer("❌ Невідомий тип"); return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE packs SET delivery_type=? WHERE pack_id=?", (dtype, pack_id))
        await db.commit()
    invalidate_packs_cache()
    label = DTYPE_LABELS.get(dtype, dtype)
    await call.message.edit_text(
        f"✅ Тип видачі для `{pack_id}` змінено на *{label}*",
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data == "admin_new_pack")
@admin_only
async def admin_new_pack_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_new_pack_id)
    await call.message.edit_text("✏️ Введіть ID нового паку (латиниця/цифри/_, 2-32 символи):")

@dp.message(StateFilter(AdminStates.waiting_new_pack_id))
@admin_only
async def admin_new_pack_id(msg: types.Message, state: FSMContext):
    pid = msg.text.strip()
    if not PACK_ID_RE.match(pid):
        await msg.answer("❌ Невірний формат. Спробуйте ще:"); return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM packs WHERE pack_id=?", (pid,)) as cur:
            if await cur.fetchone():
                await msg.answer("❌ Такий ID вже існує. Введіть інший:"); return
    await state.update_data(pack_id=pid)
    await state.set_state(AdminStates.waiting_new_pack_name)
    await msg.answer("✏️ Назва паку:")

@dp.message(StateFilter(AdminStates.waiting_new_pack_name))
@admin_only
async def admin_new_pack_name(msg: types.Message, state: FSMContext):
    name = msg.text.strip()
    if not name or len(name) > 100:
        await msg.answer("❌ Назва 1-100 символів:"); return
    await state.update_data(name=name)
    await state.set_state(AdminStates.waiting_new_pack_price)
    await msg.answer("✏️ Ціна в USDT (напр. 1.5):")

@dp.message(StateFilter(AdminStates.waiting_new_pack_price))
@admin_only
async def admin_new_pack_price(msg: types.Message, state: FSMContext):
    try:
        price = float(msg.text.strip().replace(",", "."))
        assert 0 < price <= 100000
    except Exception:
        await msg.answer("❌ Введіть додатне число:"); return
    await state.update_data(price=round(price, 6))
    await state.set_state(AdminStates.waiting_new_pack_dtype)
    await msg.answer(
        "📦 Оберіть тип видачі товару:\n\n"
        "📄 *PDF* — генерує файл з усіма кодами (для наборів промокодів)\n"
        "🔑 *Код* — надсилає текст/код прямо в чат (для VPN-ключів, Admitad-кодів)\n"
        "🔗 *Посилання* — надсилає кнопку з URL (для реферальних/партнерських посилань)",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="📄 PDF файл",          callback_data="dtype_pdf")],
            [types.InlineKeyboardButton(text="🔑 Текстовий код",      callback_data="dtype_code")],
            [types.InlineKeyboardButton(text="🔗 Посилання (кнопка)", callback_data="dtype_link")],
        ]),
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data.startswith("dtype_"), StateFilter(AdminStates.waiting_new_pack_dtype))
@admin_only
async def admin_new_pack_dtype(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    dtype = call.data.replace("dtype_", "")
    if dtype not in ("pdf", "code", "link"):
        return
    await state.update_data(delivery_type=dtype)
    await state.set_state(AdminStates.waiting_new_pack_codes)

    hints = {
        "pdf":  "✏️ Введіть коди (кожен з нового рядка) — всі увійдуть у PDF файл:",
        "code": "✏️ Введіть коди/ключі (кожен з нового рядка) — будуть надіслані текстом покупцю:",
        "link": "✏️ Введіть реферальне/партнерське посилання (одне, повний URL із https://):",
    }
    await call.message.edit_text(hints[dtype])

@dp.message(StateFilter(AdminStates.waiting_new_pack_codes))
@admin_only
async def admin_new_pack_codes(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    dtype = data.get("delivery_type", "pdf")
    codes = [l.strip() for l in msg.text.split("\n") if l.strip()]

    if not codes:
        await msg.answer("❌ Потрібен хоча б один елемент:"); return

    # Для типу link — перевіряємо що це валідний URL
    if dtype == "link":
        url = codes[0]
        if not url.startswith("http://") and not url.startswith("https://"):
            await msg.answer("❌ Посилання має починатись з https:// Спробуйте ще раз:"); return
        codes = [url]  # лише перший рядок для link

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO packs(pack_id, name, price, delivery_type) VALUES (?,?,?,?)",
                (data["pack_id"], data["name"], data["price"], dtype)
            )
        except aiosqlite.IntegrityError:
            await state.clear()
            await msg.answer("❌ ID вже зайнятий."); return
        for code in codes:
            await db.execute("INSERT INTO pack_codes(pack_id,code) VALUES (?,?)", (data["pack_id"], code))
        await db.commit()

    invalidate_packs_cache()
    await state.clear()
    label = DTYPE_LABELS.get(dtype, dtype)
    await msg.answer(
        f"✅ Пак «{data['name']}» створено!\n"
        f"Тип: {label}\n"
        f"Елементів: {len(codes)}"
    )

@dp.callback_query(lambda c: c.data == "admin_broadcast")
@admin_only
async def admin_broadcast_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminStates.waiting_broadcast_text)
    await call.message.edit_text("📢 Надішліть текст розсилки:")

@dp.message(StateFilter(AdminStates.waiting_broadcast_text))
@admin_only
async def admin_broadcast_send(msg: types.Message, state: FSMContext):
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            user_ids = [r[0] for r in await cur.fetchall()]
    status_msg = await msg.answer(f"📤 0/{len(user_ids)}")
    sent = failed = 0
    for i, uid in enumerate(user_ids):
        try:
            await bot.send_message(uid, msg.text)
            sent += 1
        except Exception:
            failed += 1
        if i % 20 == 0 and i:
            await asyncio.sleep(1)
        if i % 10 == 0:
            try:
                await status_msg.edit_text(f"📤 {i+1}/{len(user_ids)}")
            except Exception:
                pass
    await status_msg.edit_text(f"✅ Надіслано: {sent}, помилок: {failed}")

# ============================================================
# STARTUP — відновлення processing після краші
# ============================================================
async def recover_on_startup():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("UPDATE pending_payments SET status='pending' WHERE status='processing'")
        await db.commit()
        if cur.rowcount:
            logger.warning(f"Відновлено {cur.rowcount} платежів після перезапуску")

# ============================================================
# ЗАПУСК
# ============================================================
async def main():
    await init_db()
    await recover_on_startup()
    asyncio.create_task(payment_worker())
    asyncio.create_task(backup_worker())
    asyncio.create_task(scheduler_worker(bot=bot))  # автооновлення товарів
    logger.info("PromoHub Bot v3 запущено!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
