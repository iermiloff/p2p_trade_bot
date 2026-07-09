import asyncio
import logging
import sys
import random
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext

# Импортируем конфигурацию, базу и константы
from config import BOT_TOKEN, ADMIN_IDS
from database import init_db, has_active_deal
from constants import DEAL_STATUS_NAMES

import cabinet
import offers
import verification
import admin

# Импортируем один главный роутер из пакета deals
from deals import router as deals_router

# ИСПРАВЛЕНО: Импортируем модули сделок и рейтингов из папки deals
from deals import core
from deals import actions
from deals import guarantor
from deals import rating

# ИСПРАВЛЕНО: Импортируем новый защитный мидлварь взамен старого
from ban_middleware import PlatformSecurityMiddleware
from tasks import auto_cancel_expired_deals

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- РЕГИСТРАЦИЯ МИДЛВАРЕЙ БЕЗОПАСНОСТИ (АНТИ-ФЛУД + БАНЫ) ---
# ИСПРАВЛЕНО: Подключаем единый защитный комплекс на сообщения и клики
dp.message.middleware(PlatformSecurityMiddleware())
dp.callback_query.middleware(PlatformSecurityMiddleware())

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    """Точка старта бота с жестким разделением ролей Админ / Заявка KYC / Верифицированный юзер"""
    await state.clear()
    tg_id = message.from_user.id
    
    import aiosqlite
    from database import DB_NAME
    
    # --- ШАГ 1: ПРОВЕРКА АКТИВНЫХ СДЕЛК ---
    async with aiosqlite.connect(DB_NAME) as db:
        query = """
            SELECT id, status, buyer_id, seller_id, guarantor_id 
            FROM deals 
            WHERE (buyer_id = ? OR seller_id = ? OR guarantor_id = ?) 
            AND status IN ('waiting_deposit', 'waiting_payment', 'waiting_delivery', 'dispute')
            ORDER BY id DESC LIMIT 1
        """
        async with db.execute(query, (tg_id, tg_id, tg_id)) as cursor:
            active_deal = await cursor.fetchone()
            
    if active_deal:
        deal_id, status, buyer_id, seller_id, guarantor_id = active_deal
        from actions import send_deal_interface_to_user
        await send_deal_interface_to_user(bot, tg_id, deal_id, status, buyer_id, seller_id, guarantor_id, message)
        return

    # --- ШАГ 2: ПРОВЕРКА НА РОЛЬ АДМИНИСТРАТОРА ---
    if tg_id in ADMIN_IDS:
        import admin
        await message.answer(
            "🛠 **Панель управления Администратора P2P**\n\nВыберите необходимый раздел для модерации платформы:",
            reply_markup=admin.get_admin_keyboard()
        )
        return

    # --- ШАГ 3: ЖЕСТКАЯ ПРОВЕРКА СТАТУСА ВЕРИФИКАЦИИ (KYC) ---
    async with aiosqlite.connect(DB_NAME) as db:
        # Проверяем, есть ли юзер в базе и какой у него статус верификации
        async with db.execute("SELECT is_verified, nickname FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            user_kyc = await cursor.fetchone()
            
    # Если пользователя еще нет в БД (первый старт)
    if not user_kyc:
        # Генерируем анонимный никнейм из двух массивов слов
        adjectives = ["Epic", "Brave", "Golden", "Rapid", "Shadow", "Silent", "Crypto", "Alpha"]
        nouns = ["Whale", "Punk", "Trader", "Shark", "Wolf", "Bull", "Bear", "Falcon"]
        generated_nick = f"{random.choice(adjectives)} {random.choice(nouns)} #{random.randint(100, 999)}"
        
        async with aiosqlite.connect(DB_NAME) as db:
            # Создаем пользователя со статусом is_verified = 0
            await db.execute(
                "INSERT INTO users (tg_id, nickname, is_verified, user_status) VALUES (?, ?, 0, 'verified')",
                (tg_id, generated_nick)
            )
            # Инициализируем пустую строку реквизитов для защиты от падений ЛК
            await db.execute("INSERT INTO requisites (tg_id) VALUES (?)", (tg_id,))
            await db.commit()
        is_verified = 0
    else:
        is_verified = user_kyc[0]

    # Если пользователь НЕ верифицирован (is_verified == 0), блокируем маркет
    if is_verified == 0:
        kb_kyc = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🚀 Пройти верификацию", callback_data="start_verification")]
        ])
        await message.answer(
            "👋 **Добро пожаловать на P2P Торговую Платформу!**\n\n"
            "⚠️ **Доступ ограничен!**\n"
            "Для защиты системы от спам-ботов, мошенников и мультиаккаунтов, "
            "каждый участник обязан подтвердить свою личность перед началом торговли.\n\n"
            "Нажмите кнопку ниже, чтобы ознакомиться с инструкцией как пройти верификацию и отправить заявку администраторам платформы:",
            reply_markup=kb_kyc,
            parse_mode="Markdown"
        )
        return

    # --- ШАГ 4: ДОСТУП ДЛЯ ПОЛНОСТЬЮ ВЕРИФИЦИРОВАННЫХ ПОЛЬЗОВАТЕЛЕЙ ---
    import cabinet
    await message.answer(
        "👋 **Добро пожаловать на P2P Торговую Платформу!**\n\n"
        "🟢 Ваш профиль успешно верифицирован. Вам открыт полный доступ к торговым стаканам и обменам через Гаранта.\n\n"
        "Используйте меню ниже для настройки реквизитов и управления ордерами:",
        reply_markup=cabinet.get_main_keyboard(),
        parse_mode="Markdown"
    )

# --- ИНИЦИАЛИЗАЦИЯ И ЗАПУСК ВСЕЙ СИСТЕМЫ ---
async def main():
    # 1. Создаем таблицы в БД и включаем режим высокой производительности WAL
    await init_db()
    
    dp.include_router(cabinet.router)
    dp.include_router(offers.router)
    dp.include_router(verification.router)
    dp.include_router(admin.router) # РЕГИСТРИРУЕМ ТУТ
    dp.include_router(deals_router)
    
    asyncio.create_task(auto_cancel_expired_deals(bot))
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
    
    print("[СИСТЕМА]: P2P Бот успешно запущен в асинхронном режиме безопасности.")
    
    # 4. Включаем Long Polling (пропускаем входящие сообщения, пока бот был выключен)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("[СИСТЕМА]: Бот принудительно остановлен.")

