import aiosqlite
import random
import time
from config import ADMIN_IDS
from constants import TITLES

DB_NAME = "p2p_bot.db"

async def init_db():
    """Инициализация базы данных с новыми направлениями обмена"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        
        # Таблица пользователей
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
        
# Таблица реквизитов (Полное соответствие ТЗ)
await db.execute('''
CREATE TABLE IF NOT EXISTS requisites (
    tg_id INTEGER PRIMARY KEY,
    card TEXT DEFAULT '',           -- Куда Продавец получает рубли (нужно для всех 4-х направлений)
    crypto_bot TEXT DEFAULT '',     -- Реквизиты для получения крипты на Crypto Bot
    bybit TEXT DEFAULT '',          -- Реквизиты/Адрес для получения крипты на Bybit
    other_wallets TEXT DEFAULT '',  -- Реквизиты/Адрес для сторонних кошельков
    fkwallet TEXT DEFAULT ''        -- Номер кошелька FkWallet
)''')

        
        # Таблица объявлений в стакане
        # direction может быть: 'crypto_bot', 'bybit', 'other_wallets', 'fkwallet' (все к Картам)
        await db.execute('''
        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER,
            direction TEXT, 
            offer_type TEXT, -- 'buy' (создатель покупает крипту/FK) или 'sell' (создатель продает)
            amount TEXT,
            rate TEXT,
            status TEXT DEFAULT 'active'
        )''')
        
        # Таблица сделок
        await db.execute('''
        CREATE TABLE IF NOT EXISTS deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_id INTEGER,
            buyer_id INTEGER,
            seller_id INTEGER,
            status TEXT, -- 'waiting_deposit', 'waiting_payment', 'waiting_delivery', 'completed', 'cancelled', 'dispute'
            use_guarantor INTEGER DEFAULT 1, -- Всегда 1
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

async def has_required_requisites(tg_id: int, direction: str, offer_type: str) -> bool:
    """
    Проверяет реквизиты. 
    Важно: Покупатель фиата должен иметь кошелек/адрес для получения крипты.
    Продавец крипты должен иметь Карту для получения фиата.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT card, fkwallet, crypto_address FROM requisites WHERE tg_id = ?", (tg_id,)) as cursor:
            res = await cursor.fetchone()
            
    if not res:
        return False
        
    card, fkwallet, crypto_address = res
    
    # Определяем, кем будет пользователь в сделке: Продавцом крипты или Покупателем
    # Если объявление в стакане 'buy' (создатель покупает), то тот кто его НАЖИМАЕТ — продает крипту.
    is_selling_crypto = (offer_type == "sell") 

    if is_selling_crypto:
        # Продавцу крипты (получателю фиата) обязательно нужна заполненная Карта
        return bool(card and card.strip())
    else:
        # Покупателю крипты (получателю монет) нужен адрес кошелька в зависимости от направления
        if direction == "fkwallet":
            return bool(fkwallet and fkwallet.strip())
        else:
            return bool(crypto_address and crypto_address.strip())

async def get_user_title(deals_count: int, rating: float) -> str:
    for title in TITLES:
        if deals_count >= title["min_deals"] and rating >= title["min_rating"]:
            return title["name"]
    return "Новичок"

