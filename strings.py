"""
Мультимовні рядки для PromoHub Bot
Підтримувані мови: uk (українська), ru (російська), en (англійська)
"""

STRINGS = {
    "uk": {
        # Старт і меню
        "welcome": "🔥 *PromoHub* — найкращі промокоди!\n\nОберіть пакет:",
        "choose_payment": "💳 *{name}*\nЦіна: *{price} USDT*\n\nОберіть спосіб оплати:",
        "back": "◀️ Назад",
        "admin_panel_btn": "⚙️ Адмін-панель",
        "no_pack": "❌ Пак більше не доступний.",
        "pack_empty": "❌ На жаль, цей пак тимчасово відсутній (немає кодів). Оберіть інший.",

        # Оплата
        "pay_trc20": "🔷 USDT TRC20",
        "pay_ton": "💎 TON",
        "pay_bep20": "🟨 USDT BEP20",
        "pay_binance": "🟡 Binance Pay",
        "pay_instructions": (
            "{method}\n\n"
            "💰 Сума: *{price}*\n\n"
            "📋 Адреса:\n`{address}`\n\n"
            "⏰ Оплатіть протягом *60 хвилин*\n"
            "✅ Бот перевіряє автоматично кожні 30 сек"
        ),
        "pay_creating": "⏳ Створюємо замовлення...",
        "pay_binance_btn": "💳 Оплатити через Binance",
        "pay_binance_msg": "🟡 *Binance Pay*\n\n💰 Сума: *{price} USDT*\n\nНатисніть кнопку для оплати:",
        "pay_binance_unavailable": "❌ Binance Pay недоступний. Скористайтесь TRC20.",
        "pay_timeout": "⏰ Час оплати вийшов. Натисніть /start щоб спробувати знову.",

        # Видача
        "deliver_ok": "✅ *Оплата підтверджена!*\n\n🎁 {name}\n\nДякуємо! 🎉",
        "deliver_error": "❌ Помилка генерації файлу. Напишіть адміну — оплата зафіксована.",
        "deliver_pack_deleted": (
            "⚠️ Оплата отримана, але цей пак вже недоступний. "
            "Зверніться до підтримки — вам повернуть кошти або видадуть альтернативний пак."
        ),

        # Мої замовлення
        "myorders_empty": "У вас ще немає покупок. Натисніть /start щоб обрати пак 🎁",
        "myorders_header": "🧾 *Ваші останні покупки:*\n\n",
        "myorders_deleted_pack": "(видалений пак {pack_id})",

        # Реферальна система
        "ref_link_header": "🔗 *Ваше реферальне посилання:*\n\n",
        "ref_stats": (
            "👥 Запрошено: *{invited}* чол.\n"
            "💰 Нараховано: *{balance} USDT*\n"
            "✅ Виплачено: *{paid} USDT*\n\n"
        ),
        "ref_min_withdraw": "Мінімальна сума для виплати: *{min} USDT*",
        "ref_request_btn": "💸 Запросити виплату ({balance} USDT)",
        "ref_no_balance": "❌ Недостатньо коштів. Мінімум для виплати: {min} USDT",
        "ref_need_address": "✏️ Введіть вашу USDT TRC20 адресу для виплати:",
        "ref_request_sent": "✅ Запит на виплату {amount} USDT відправлено. Очікуйте підтвердження від адміна.",
        "ref_invalid_address": "❌ Невірна адреса. USDT TRC20 адреса починається з 'T' і має 34 символи.",
        "ref_already_pending": "⏳ У вас вже є активний запит на виплату. Зачекайте на його підтвердження.",
        "ref_earned": "🎉 Ваш реферал зробив покупку! Нараховано *{amount} USDT* на ваш баланс.",

        # Вибір мови
        "choose_lang": "🌍 Оберіть мову / Choose language / Выберите язык:",
        "lang_set": "✅ Мову змінено на Українську 🇺🇦",

        # Видача посилання
        "deliver_link_btn": "🔗 Отримати доступ",

        # Rate limit
        "rate_limit": "⏳ Забагато запитів. Зачекайте кілька секунд.",
    },

    "ru": {
        "welcome": "🔥 *PromoHub* — лучшие промокоды!\n\nВыберите пакет:",
        "choose_payment": "💳 *{name}*\nЦена: *{price} USDT*\n\nВыберите способ оплаты:",
        "back": "◀️ Назад",
        "admin_panel_btn": "⚙️ Админ-панель",
        "no_pack": "❌ Пак больше недоступен.",
        "pack_empty": "❌ К сожалению, этот пак временно недоступен (нет кодов). Выберите другой.",

        "pay_trc20": "🔷 USDT TRC20",
        "pay_ton": "💎 TON",
        "pay_bep20": "🟨 USDT BEP20",
        "pay_binance": "🟡 Binance Pay",
        "pay_instructions": (
            "{method}\n\n"
            "💰 Сумма: *{price}*\n\n"
            "📋 Адрес:\n`{address}`\n\n"
            "⏰ Оплатите в течение *60 минут*\n"
            "✅ Бот проверяет автоматически каждые 30 сек"
        ),
        "pay_creating": "⏳ Создаём заказ...",
        "pay_binance_btn": "💳 Оплатить через Binance",
        "pay_binance_msg": "🟡 *Binance Pay*\n\n💰 Сумма: *{price} USDT*\n\nНажмите кнопку для оплаты:",
        "pay_binance_unavailable": "❌ Binance Pay недоступен. Воспользуйтесь TRC20.",
        "pay_timeout": "⏰ Время оплаты истекло. Нажмите /start чтобы попробовать снова.",

        "deliver_ok": "✅ *Оплата подтверждена!*\n\n🎁 {name}\n\nСпасибо! 🎉",
        "deliver_error": "❌ Ошибка генерации файла. Напишите админу — оплата зафиксирована.",
        "deliver_pack_deleted": (
            "⚠️ Оплата получена, но этот пак уже недоступен. "
            "Обратитесь в поддержку — вам вернут средства или выдадут альтернативный пак."
        ),

        "myorders_empty": "У вас ещё нет покупок. Нажмите /start чтобы выбрать пак 🎁",
        "myorders_header": "🧾 *Ваши последние покупки:*\n\n",
        "myorders_deleted_pack": "(удалённый пак {pack_id})",

        "ref_link_header": "🔗 *Ваша реферальная ссылка:*\n\n",
        "ref_stats": (
            "👥 Приглашено: *{invited}* чел.\n"
            "💰 Начислено: *{balance} USDT*\n"
            "✅ Выплачено: *{paid} USDT*\n\n"
        ),
        "ref_min_withdraw": "Минимальная сумма для выплаты: *{min} USDT*",
        "ref_request_btn": "💸 Запросить выплату ({balance} USDT)",
        "ref_no_balance": "❌ Недостаточно средств. Минимум для выплаты: {min} USDT",
        "ref_need_address": "✏️ Введите вашу USDT TRC20 адрес для выплаты:",
        "ref_request_sent": "✅ Запрос на выплату {amount} USDT отправлен. Ожидайте подтверждения от админа.",
        "ref_invalid_address": "❌ Неверный адрес. USDT TRC20 адрес начинается с 'T' и имеет 34 символа.",
        "ref_already_pending": "⏳ У вас уже есть активный запрос на выплату. Подождите подтверждения.",
        "ref_earned": "🎉 Ваш реферал совершил покупку! Начислено *{amount} USDT* на ваш баланс.",

        "deliver_link_btn": "🔗 Получить доступ",
        "choose_lang": "🌍 Оберіть мову / Choose language / Выберите язык:",
        "lang_set": "✅ Язык изменён на Русский 🇷🇺",
        "rate_limit": "⏳ Слишком много запросов. Подождите несколько секунд.",
    },

    "en": {
        "welcome": "🔥 *PromoHub* — best promo codes!\n\nChoose a pack:",
        "choose_payment": "💳 *{name}*\nPrice: *{price} USDT*\n\nChoose payment method:",
        "back": "◀️ Back",
        "admin_panel_btn": "⚙️ Admin Panel",
        "no_pack": "❌ This pack is no longer available.",
        "pack_empty": "❌ This pack is temporarily out of stock (no codes left). Please choose another.",

        "pay_trc20": "🔷 USDT TRC20",
        "pay_ton": "💎 TON",
        "pay_bep20": "🟨 USDT BEP20",
        "pay_binance": "🟡 Binance Pay",
        "pay_instructions": (
            "{method}\n\n"
            "💰 Amount: *{price}*\n\n"
            "📋 Address:\n`{address}`\n\n"
            "⏰ Pay within *60 minutes*\n"
            "✅ Bot checks automatically every 30 sec"
        ),
        "pay_creating": "⏳ Creating order...",
        "pay_binance_btn": "💳 Pay via Binance",
        "pay_binance_msg": "🟡 *Binance Pay*\n\n💰 Amount: *{price} USDT*\n\nPress the button to pay:",
        "pay_binance_unavailable": "❌ Binance Pay is unavailable. Please use TRC20.",
        "pay_timeout": "⏰ Payment time expired. Press /start to try again.",

        "deliver_ok": "✅ *Payment confirmed!*\n\n🎁 {name}\n\nThank you! 🎉",
        "deliver_error": "❌ File generation error. Contact admin — payment is recorded.",
        "deliver_pack_deleted": (
            "⚠️ Payment received, but this pack is no longer available. "
            "Contact support — you'll receive a refund or alternative pack."
        ),

        "myorders_empty": "You have no purchases yet. Press /start to choose a pack 🎁",
        "myorders_header": "🧾 *Your recent purchases:*\n\n",
        "myorders_deleted_pack": "(deleted pack {pack_id})",

        "ref_link_header": "🔗 *Your referral link:*\n\n",
        "ref_stats": (
            "👥 Invited: *{invited}* users\n"
            "💰 Earned: *{balance} USDT*\n"
            "✅ Paid out: *{paid} USDT*\n\n"
        ),
        "ref_min_withdraw": "Minimum withdrawal amount: *{min} USDT*",
        "ref_request_btn": "💸 Request payout ({balance} USDT)",
        "ref_no_balance": "❌ Insufficient balance. Minimum withdrawal: {min} USDT",
        "ref_need_address": "✏️ Enter your USDT TRC20 address for payout:",
        "ref_request_sent": "✅ Payout request for {amount} USDT submitted. Awaiting admin confirmation.",
        "ref_invalid_address": "❌ Invalid address. USDT TRC20 address starts with 'T' and is 34 characters long.",
        "ref_already_pending": "⏳ You already have a pending payout request. Please wait for confirmation.",
        "ref_earned": "🎉 Your referral made a purchase! *{amount} USDT* added to your balance.",

        "deliver_link_btn": "🔗 Get access",
        "choose_lang": "🌍 Оберіть мову / Choose language / Выберите язык:",
        "lang_set": "✅ Language changed to English 🇬🇧",
        "rate_limit": "⏳ Too many requests. Please wait a few seconds.",
    }
}

def t(lang: str, key: str, **kwargs) -> str:
    """Повертає перекладений рядок для заданої мови. Якщо ключ не знайдено — fallback на uk."""
    text = STRINGS.get(lang, STRINGS["uk"]).get(key) or STRINGS["uk"].get(key, f"[{key}]")
    if kwargs:
        try:
            return text.format(**kwargs)
        except KeyError:
            return text
    return text
