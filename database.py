import aiosqlite
import random
import time
from config import ADMIN_IDS
from constants import STATUS_LIMITS, TITLES

DB_NAME = "p2p_bot.db"

async def init_db():
    """Инициализация базы данных и создание таблиц с защитой структуры"""
    async with aiosqlite.connect(DB_NAME) as db:
        # Включаем режим WAL (Write-Ahead Logging) для предотвращения блокировок файла БД
        await db.execute("PRAGMA journal_mode=WAL;")
        
        # Обновленная таблица пользователей с поддержкой точной математики репутации
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                nickname TEXT UNIQUE,
                is_verified INTEGER DEFAULT 0,
                user_status TEXT DEFAULT 'verified',
                rating REAL DEFAULT 5.0,
                deals_count INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,       
                ban_until INTEGER DEFAULT 0,        
                kyc_file_id TEXT DEFAULT NULL,
                rating_sum INTEGER DEFAULT 5,
                rating_count INTEGER DEFAULT 1
            )''')

        # Таблица сохраненных реквизитов для ЛК
        await db.execute('''
            CREATE TABLE IF NOT EXISTS requisites (
                tg_id INTEGER PRIMARY KEY,
                card TEXT DEFAULT '',
                piastrix TEXT DEFAULT '',
                ton TEXT DEFAULT ''
            )''')

        # Таблица объявлений (Offers) в стакане
        await db.execute('''
            CREATE TABLE IF NOT EXISTS offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER,
                direction TEXT, -- 'gram_card', 'gram_piastrix', 'card_piastrix'
                offer_type TEXT, -- 'buy' или 'sell'
                amount TEXT,
                rate TEXT,
                status TEXT DEFAULT 'active' -- 'active' или 'closed'
            )''')

        # Таблица сделок (Deals) между пользователями
        await db.execute('''
            CREATE TABLE IF NOT EXISTS deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                offer_id INTEGER,
                buyer_id INTEGER,
                seller_id INTEGER,
                status TEXT, -- 'waiting_seller', 'waiting_payment', 'waiting_delivery', 'completed', 'cancelled', 'dispute'
                use_guarantor INTEGER DEFAULT 0,
                guarantor_id INTEGER DEFAULT NULL,
                timer_start TEXT
            )''')
        await db.commit()

async def check_offer_limit(tg_id: int) -> bool:
    """Защита продавцов: Проверяет, может ли пользователь создать новую заявку по своему лимиту"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_status FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            res = await cursor.fetchone()
            user_status = res[0] if res else "verified"
            
        async with db.execute(
            "SELECT COUNT(*) FROM offers WHERE creator_id = ? AND status = 'active'", 
            (tg_id,)
        ) as cursor:
            res = await cursor.fetchone()
            active_offers_count = res[0] if res else 0
            
    max_limit = STATUS_LIMITS.get(user_status, 3)
    return active_offers_count < max_limit

async def has_active_deal(tg_id: int) -> bool:
    """Защита продавцов от флуда сделками: Проверяет, есть ли у покупателя незавершенная сделка в моменте"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            """
            SELECT COUNT(*) FROM deals 
            WHERE (buyer_id = ? OR seller_id = ?) 
            AND status NOT IN ('completed', 'cancelled')
            """, 
            (tg_id, tg_id)
        ) as cursor:
            res = await cursor.fetchone()
            count = res[0] if res else 0
            
    return count > 0

async def has_required_requisites(tg_id: int, direction: str) -> bool:
    """
    Проверяет, заполнены ли у пользователя необходимые реквизиты 
    для работы в выбранном направлении обмена.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT card, piastrix, ton FROM requisites WHERE tg_id = ?", (tg_id,)) as cursor:
            res = await cursor.fetchone()
            
    if not res:
        return False
        
    card, piastrix, ton = res
    
    # В зависимости от направления проверяем нужные поля
    if direction == "gram_card":
        # Нужна и карта, и TON-кошелек
        return bool(card and card.strip()) and bool(ton and ton.strip())
    elif direction == "gram_piastrix":
        # Нужен Piastrix и TON-кошелек
        return bool(piastrix and piastrix.strip()) and bool(ton and ton.strip())
    elif direction == "card_piastrix":
        # Нужна карта и Piastrix
        return bool(card and card.strip()) and bool(piastrix and piastrix.strip())
        
    return False

async def is_user_guarantor(tg_id: int) -> bool:
    """
    Вспомогательная функция безопасности.
    Проверяет, имеет ли право пользователь модерировать сделку 
    в качестве Гаранта (проверяет статус в БД).
    """
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_status FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            res = await cursor.fetchone()
            
    if res and res[0] == "guarantor_member":
        return True
    return False


async def get_user_title(deals_count: int, rating: float) -> str:
    """
    Динамически вычисляет титул пользователя на основе количества 
    успешных сделок и текущего рейтинга.
    """
    for title in TITLES:
        if deals_count >= title["min_deals"] and rating >= title["min_rating"]:
            return title["name"]
    return "🥚 Новичок"
