import aiosqlite
import time
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from database import DB_NAME

class BanCheckMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user:
            user_id = user.id
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
                            await event.answer("❌ **Доступ заблокирован.** Ваш аккаунт навсегда забанен.")
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
                # Если падает база данных, мы пишем ошибку в консоль сервера, но НЕ тушим бота
                print(f"[КРИТИЧЕСКАЯ ОШИБКА MIDDLEWARE]: {e}")

        return await handler(event, data)

