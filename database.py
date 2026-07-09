import aiosqlite
import random
import time
from config import ADMIN_IDS
from constants import TITLES

DB_NAME = "p2p_bot.db"

async def init_db():
    """Инициализация базы данных и создание таблиц с защитой структуры"""
    async with aiosqlite.connect(DB_NAME) as db:
        # Включаем режим WAL для предотвращения блокировок при конкурентных запросах
        await db.execute("PRAGMA journal_mode=WAL;")
        
        # Таблица пользователей системы
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
        
        # Таблица реквизитов под новые 4 направления (Полное соответствие ТЗ)
        await db.execute('''
        CREATE TABLE IF NOT EXISTS requisites (
            tg_id INTEGER PRIMARY KEY,
            card TEXT DEFAULT '',
            crypto_bot TEXT DEFAULT '',
            bybit TEXT DEFAULT '',
            other_wallets TEXT DEFAULT '',
            fkwallet TEXT DEFAULT ''
        )''')
        
        # Таблица объявлений в торговом стакане
        await db.execute('''
        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER,
            direction TEXT, 
            offer_type TEXT, 
            amount TEXT,
            rate TEXT,
            status TEXT DEFAULT 'active'
        )''')
        
        # Таблица асинхронных сделок
        await db.execute('''
        CREATE TABLE IF NOT EXISTS deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_id INTEGER,
            buyer_id INTEGER,
            seller_id INTEGER,
            status TEXT, 
            use_guarantor INTEGER DEFAULT 1, 
            guarantor_id INTEGER DEFAULT NULL,
            timer_start TEXT
        )''')
        
        await db.commit()
async def has_active_deal(tg_id: int) -> bool:
    """Проверяет наличие активной сделки на любом из асинхронных этапов"""
    async with aiosqlite.connect(DB_NAME) as db:
        query = """
        SELECT COUNT(*) FROM deals 
        WHERE (buyer_id = ? OR seller_id = ?) 
        AND status IN ('waiting_deposit', 'waiting_payment', 'waiting_delivery', 'dispute')
        """
        async with db.execute(query, (tg_id, tg_id)) as cursor:
            res = await cursor.fetchone()
            return res[0] > 0 if res else False

async def check_offer_limit(tg_id: int) -> int:
    """Возвращает точное количество активных объявлений пользователя"""
    async with aiosqlite.connect(DB_NAME) as db:
        query = "SELECT COUNT(*) FROM offers WHERE creator_id = ? AND status = 'active'"
        async with db.execute(query, (tg_id,)) as cursor:
            res = await cursor.fetchone()
            return res[0] if res else 0

async def has_required_requisites(tg_id: int, direction: str, offer_type: str) -> bool:
    """
    Проверяет реквизиты. 
    Важно: Покупатель фиата должен иметь кошелек/адрес для получения крипты.
    Продавец крипты должен иметь Карту для получения фиата.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        query = "SELECT card, crypto_bot, bybit, other_wallets, fkwallet FROM requisites WHERE tg_id = ?"
        async with db.execute(query, (tg_id,)) as cursor:
            res = await cursor.fetchone()
            
    if not res:
        return False
        
    card, c_bot, bybit, other, fk = res
    
    # Определяем роль пользователя: если тип ордера в стакане 'sell' (создатель продает),
    # то тот, кто его НАЖИМАЕТ — покупает крипту (отдает фиат)
    is_selling_crypto = (offer_type == "sell") 

    if is_selling_crypto:
        # Продавцу крипты (получателю фиата) обязательно нужна заполненная Карта
        return bool(card and card.strip())
    else:
        # Покупателю крипты (получателю монет) нужен адрес кошелька под конкретное направление
        if direction == "crypto_bot":
            return bool(c_bot and c_bot.strip())
        elif direction == "bybit":
            return bool(bybit and bybit.strip())
        elif direction == "other_wallets":
            return bool(other and other.strip())
        elif direction == "fkwallet":
            return bool(fk and fk.strip())
            
        return False
        
async def is_user_guarantor(tg_id: int) -> bool:
    """Проверяет права Гаранта с корректной распаковкой кортежа"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_status FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            res = await cursor.fetchone()
        # ИСПРАВЛЕНО: Проверяем первый элемент кортежа res[0]
        if res and res[0] in ["guarantor_member", "guarantor"]:
            return True
        return False


async def get_user_title(deals_count: int, rating: float) -> str:
    """Расчет титула пользователя"""
    for title in TITLES:
        if deals_count >= title["min_deals"] and rating >= title["min_rating"]:
            return title["name"]
    return "Новичок"
