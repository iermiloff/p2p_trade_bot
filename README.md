# 🔄 Open-Source P2P Exchange Telegram Bot (TON / GRAM)

Полностью асинхронный Telegram-бот для безопасного P2P-обмена криптовалюты **GRAM (TON)** и фиатных средств между пользователями. Проект спроектирован с упором на максимальную анонимность участников и защиту от популярных уязвимостей (Race Conditions, Order Booking Attacks, спам заявками).

## 🚀 Направления обмена
Бот разделен на три изолированные секции:
* 💎 **GRAM (TON) ⇄ 💳 Банковские Карты**
* 💎 **GRAM (TON) ⇄ 📱 Piastrix**
* 💳 **Банковские Карты ⇄ 📱 Piastrix**

---

## 🛡️ Архитектура безопасности и фичи
* **Атомарная регистрация:** Защита от состояния гонки (Race Condition). База данных SQLite переведена в асинхронный режим `WAL`, а генерация никнеймов защищена на уровне транзакций.
* **Анонимизация участников:** Все пользователи получают постоянные случайные псевдонимы (например, *Epic Whale*, *Brave Punk*). Реальные Telegram ID и юзернеймы скрыты.
* **Защита от спама продавцов:** Введены жесткие лимиты на количество активных объявлений в стакане на основе ролей, выдаваемых администратором:
  * `Verified` (Верифицированный) — макс. 1 заявка.
  * `Trader` (Трейдер) — макс. 5 заявок.
  * `Super Trader` (Супер-трейдер) — макс. 10 заявок.
* **Защита от флуда сделками (Order Booking Attack):** Покупатель физически не может войти более чем в 1 сделку одновременно, что исключает блокировку ликвидности честных продавцов.
* **Тройная система таймаутов (10 минут):** Фоновая задача `asyncio` каждые 60 секунд проверяет зависшие сделки. Если участник ушел в офлайн на этапе подтверждения, оплаты или выдачи — сделка аннулируется автоматически, а лот возвращается в стакан.
* **Эскалация (Гарант):** Любой участник может в 1 клик вызвать Администратора в анонимный чат для разрешения диспута по чекам. Сообщения админа защищены системным префиксом на уровне бэкенда.
* **Модерация:** Встроенные команды временного (`/tempban`) и перманентного (`/permban`) бана пользователей с отсечением запросов через Middleware.

---

## 🛠️ Технологический стек
* **Language:** Python 3.11+
* **Framework:** Aiogram 3.x (Asynchronous Telegram Bots API)
* **Database:** SQLite3 + aiosqlite (Async driver with WAL mode)
* **State Machine:** Aiogram FSM Context (управление шагами сделок и ввода реквизитов)

---

## ⚙️ Установка и локальный запуск

1. Клонируйте репозиторий:
```bash
git clone https://github.com/iermiloff/p2p_trade_bot/
cd p2p_trade_bot
```

2. Создайте виртуальное окружение и установите зависимости:
```bash
python3 -m venv venv
source venv/bin/activate  # Для Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. Задайте обязательные переменные окружения в .env файле:
```bash
touch .env
chmod 777 .env
nano .env
```
* `BOT_TOKEN` — токен вашего бота от [@BotFather].
* `ADMIN_IDS` — ID администраторов через запятую (например, `12345678,98765432`), которые будут иметь доступ к верификации, спорам и банам.

4. Запустите бота:
```bash
export $(xargs < .env) && python3 main.py
```

---

## 🎛️ Команды Администратора (Вводятся в чате с ботом)
* `/setstatus [tg_id] [verified/trader/super_trader]` — Изменение лимитов объявлений пользователя.
* `/tempban [tg_id] [минуты]` — Временная блокировка на время разбирательств в споре.
* `/permban [tg_id]` — Перманентный бан за мошенничество.
* `/unban [tg_id]` — Полная разблокировка пользователя.

---

## 📦 Деплой на Linux-сервер (через systemd)
Для обеспечения работы бота 24/7 создайте файл службы `/etc/systemd/system/p2pbot.service`:
```ini
[Unit]
Description=Telegram P2P Exchange Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/p2p_trade_bot
EnvironmentFile=/root/p2p_trade_bot/.env
ExecStart=/root/p2p_trade_bot/venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```
5. Активируйте и запустите службу:
```bash
systemctl daemon-reload
systemctl enable p2pbot
systemctl start p2pbot
```
