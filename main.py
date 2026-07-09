import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext

# Импортируем конфигурацию, базу и константы
from config import BOT_TOKEN
from database import init_db, has_active_deal
from constants import DEAL_STATUS_NAMES

# Импортируем роутеры из корневой папки
import cabinet
import offers
import verification

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

# --- ХЭНДЛЕР СТАРТА С КОНТРОЛЕМ АКТИВНЫХ СДЕЛОК ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    """Точка старта бота с перехватом и принудительным возвратом в интерфейс активной сделки"""
    await state.clear()
    tg_id = message.from_user.id
    
    import aiosqlite
    from database import DB_NAME
    
    # Проверяем, есть ли у пользователя незавершенная сделка на любом асинхронном этапе
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
            
    # Если найдена активная сделка — жестко блокируем меню и перерисовываем интерфейс шага
    if active_deal:
        deal_id, status, buyer_id, seller_id, guarantor_id = active_deal
        
        # Вызываем централизованный рендеринг кнопок из actions.py
        from actions import send_deal_interface_to_user
        await send_deal_interface_to_user(bot, tg_id, deal_id, status, buyer_id, seller_id, guarantor_id, message)
        return

    # Если активных сделок нет — открываем стандартное Главное Меню P2P
    import cabinet
    await message.answer(
        "👋 **Добро пожаловать на P2P Торговую Платформу!**\n\n"
        "Здесь вы можете безопасно обменивать активы напрямую с другими пользователями.\n"
        "🛡 Все операции проходят **строго через асинхронного Гаранта** системы для исключения мошенничества и блокировок по 115-ФЗ.\n\n"
        "Используйте интерактивное меню ниже для работы:",
        reply_markup=cabinet.get_main_keyboard(),
        parse_mode="Markdown"
    )

# --- ИНИЦИАЛИЗАЦИЯ И ЗАПУСК ВСЕЙ СИСТЕМЫ ---
async def main():
    # 1. Создаем таблицы в БД и включаем режим высокой производительности WAL
    await init_db()
    
    # 2. Подключаем все разработанные роутеры компонентов платформы
    dp.include_router(cabinet.router)
    dp.include_router(offers.router)
    dp.include_router(core.router)
    dp.include_router(actions.router)
    dp.include_router(guarantor.router)
    dp.include_router(admin.router)
    dp.include_router(verification.router)
    dp.include_router(rating.router)
    
    # 3. Запускаем асинхронный фоновый таймаут-воркер контроля сделок
    asyncio.create_task(auto_cancel_expired_deals(bot))
    
    print("[СИСТЕМА]: P2P Бот успешно запущен в асинхронном режиме безопасности.")
    
    # 4. Включаем Long Polling (пропускаем входящие сообщения, пока бот был выключен)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("[СИСТЕМА]: Бот принудительно остановлен.")

