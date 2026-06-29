import aiosqlite
import time
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from database import DB_NAME

class BanCheckMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data: dict):
        # Работаем напрямую с объектом события (Message или CallbackQuery)
        user_id = event.from_user.id
        current_time = int(time.time())

        try:
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute(
                    "SELECT is_banned, ban_until FROM users WHERE tg_id = ?", 
                    (user_id,)
                ) as cursor:
                    res = await cursor.fetchone()

            if res:
                is_banned, ban_until = res
                
                # 1. Вечный бан
                if is_banned == 1:
                    if isinstance(event, Message):
                        await event.answer("❌ **Доступ заблокирован.** Ваш аккаунт навсегда забанен администрацией.")
                    elif isinstance(event, CallbackQuery):
                        await event.answer("❌ Вы забанены навсегда.", show_alert=True)
                    return
                
                # 2. Временный бан
                if ban_until > current_time:
                    remaining_min = int((ban_until - current_time) / 60)
                    ban_text = f"⏳ **Доступ ограничен.** Разблокировка через: {remaining_min} мин."
                    
                    if isinstance(event, Message):
                        await event.answer(ban_text)
                    elif isinstance(event, CallbackQuery):
                        await event.answer(ban_text, show_alert=True)
                    return
        except Exception as e:
            print(f"[ERROR IN BAN MIDDLEWARE]: {e}")

        # Проверка пройдена, передаем управление в хэндлеры
        return await handler(event, data)

