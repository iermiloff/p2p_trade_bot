STATUS_LIMITS = {
    "verified": 1,
    "trader": 5,
    "super_trader": 10
}

STATUS_NAMES = {
    "verified": "🟢 Верифицированный",
    "trader": "🔥 Трейдер",
    "super_trader": "⚡  Супер-трейдер",
    "guarantor_member": "🔷 Гарант" 
}

# Четкие читаемые направления для пользователей и Гарантов
DIRECTION_TITLES = {
    "crypto_bot": "Крипта (Bot) ⇄ Карты",
    "bybit": "Крипта (Bybit) ⇄ Карты",
    "other_wallets": "Крипта (Другие кошельки) ⇄ Карты",
    "fkwallet": "FkWallet ⇄ Карты"
}

DEAL_STATUS_NAMES = {
    "waiting_deposit": "⏳ Ожидание крипто-депозита от Продавца",
    "waiting_payment": "💸 Ожидание прямого перевода рублей на Карту",
    "waiting_delivery": "📦 Проверка банком / Ожидание выпуска монет",
    "completed": "✅ Успешно завершена",
    "cancelled": "❌ Отменена",
    "dispute": "⚠️ Открыт официальный Спор (Арбитраж)"
}

TITLES = [
    {"name": "👑 Небожитель P2P", "min_deals": 1000, "min_rating": 4.9},
    {"name": "🔱 Легенда Платформы", "min_deals": 500, "min_rating": 4.8},
    {"name": "⚡ Акула Трейдинга", "min_deals": 250, "min_rating": 4.7},
    {"name": "⚜ Эксперт Торговли", "min_deals": 100, "min_rating": 4.5},
    {"name": "🔥 Про-Трейдер", "min_deals": 50, "min_rating": 4.0},
    {"name": "🔷 Проверенный", "min_deals": 25, "min_rating": 4.2},
    {"name": "⚔ Старший Трейдер", "min_deals": 15, "min_rating": 4.3},
    {"name": "🪵 Бывалый", "min_deals": 7, "min_rating": 4.4},
    {"name": "🍇 Местный", "min_deals": 3, "min_rating": 4.5},
    {"name": "🥚 Новичок", "min_deals": 0, "min_rating": 0.0}
]
