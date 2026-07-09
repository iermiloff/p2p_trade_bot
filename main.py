import asyncio
import logging
import sys
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
    """Точка старта бота с перехватом и жестким разделением ролей Админ/Юзер"""
    await state.clear()
    tg_id = message.from_user.id
    
    import aiosqlite
    from database import DB_NAME
    
    # 1. Проверяем активные сделки
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

    # 2. ИСПРАВЛЕНО: Если это Администратор — принудительно перенаправляем в админку!
    if tg_id in ADMIN_IDS:
        import admin
        await message.answer(
            "🛠 **Панель управления Администратора P2P**\n\nВыберите необходимый раздел для модерации платформы:",
            reply_markup=admin.get_admin_keyboard()
        )
        return

    # 3. Если обычный пользователь — отдаем стандартный P2P-интерфейс
    import cabinet
    await message.answer(
        "👋 **Добро пожаловать на P2P Торговую Платформу!**\n\n"
        "🛡 Все операции проходят строго через асинхронного Гаранта системы.\n\n"
        "Используйте интерактивное меню ниже для работы:",
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

