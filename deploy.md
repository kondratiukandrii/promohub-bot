# 🚀 Інструкція з розгортання PromoHub Bot на VPS

## 1. Підключення до серверу

```bash
ssh root@твій_ip_адрес
```

## 2. Встановлення Python та залежностей системи

```bash
apt update && apt upgrade -y
apt install python3 python3-pip python3-venv git -y
```

## 3. Завантаження файлів бота

Створи папку і завантаж туди файли (через `scp` з твого комп'ютера, або `git`, якщо проєкт в репозиторії):

```bash
mkdir -p /root/promohub
cd /root/promohub
```

**Варіант А — через scp (з твого комп'ютера, не з серверу):**
```bash
scp bot.py requirements.txt .env root@твій_ip:/root/promohub/
```

**Варіант Б — через git:**
```bash
git clone https://github.com/твій-юзернейм/promohub-bot.git /root/promohub
cd /root/promohub
```

## 4. Віртуальне середовище та залежності

```bash
cd /root/promohub
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 5. Налаштування .env

Якщо ще не завантажив `.env` — створи його на сервері:

```bash
nano .env
```

Встав і заповни всі поля (BOT_TOKEN, ADMIN_ID, адреси), збережи `Ctrl+O`, вийди `Ctrl+X`.

## 6. Тестовий запуск (перед автозапуском)

```bash
source venv/bin/activate
python bot.py
```

Перевір у Telegram що бот відповідає на `/start`. Якщо все ОК — зупини через `Ctrl+C`.

## 7. Постійна робота через systemd (бот працює навіть після перезавантаження серверу)

Створи службу:

```bash
nano /etc/systemd/system/promohub.service
```

Встав:

```ini
[Unit]
Description=PromoHub Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/promohub
ExecStart=/root/promohub/venv/bin/python /root/promohub/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Запусти і додай в автозапуск:

```bash
systemctl daemon-reload
systemctl enable promohub
systemctl start promohub
```

## 8. Перевірка статусу і логів

```bash
# Статус (працює/не працює)
systemctl status promohub

# Логи в реальному часі
journalctl -u promohub -f

# Останні 100 рядків логів
journalctl -u promohub -n 100
```

## 9. Команди для керування

```bash
systemctl restart promohub   # перезапустити (напр. після зміни коду)
systemctl stop promohub      # зупинити
systemctl start promohub     # запустити
```

## 10. Оновлення бота (коли вносиш зміни в код)

```bash
cd /root/promohub
# заміни bot.py новою версією (scp або git pull)
systemctl restart promohub
```

## ⚠️ Перед запуском в продакшн

- Зроби тестову оплату на малу суму і переконайся що PDF приходить автоматично
- Перевір `journalctl -u promohub -f` під час тесту — там видно всі помилки API (TronGrid, TonCenter тощо)
- Переконайся що `.env` має правильні права доступу: `chmod 600 .env`
- Регулярно перевіряй вільне місце на диску для backup-файлів БД: `df -h`

## Типові проблеми

| Проблема | Рішення |
|---|---|
| `ModuleNotFoundError` | Забув активувати venv в ExecStart — перевір шлях `venv/bin/python` |
| Бот не відповідає | `journalctl -u promohub -f` — подивись помилку |
| `BOT_TOKEN не знайдено` | `.env` не в тій же папці що `bot.py`, або неправильний шлях у WorkingDirectory |
| Оплата не підтверджується | Перевір TRONGRID_API_KEY, чи правильна адреса в .env |
