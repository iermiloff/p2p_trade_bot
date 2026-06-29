import aiosqlite
import time
from aiogram import BaseMiddleware
from aiogram.types import Update
from database import DB_NAME

class BanCheckMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Update, data: dict):
        """
        Глобальный Middleware уровня Update. 
        Проверяет блокировку пользователя до того, как событие попадет в любой роутер.
        """
        user = None
        
        # Aiogram 3 передает сюда объект Update, достаем из него автора события
        if event.message:
            user = event.message.from_user
        elif event.callback_query:
            user = event.callback_query.from_user

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
                    
                    # 1. Проверка вечного бана
                    if is_banned == 1:
                        if event.message:
                            await event.message.answer("❌ **Доступ заблокирован.** Ваш аккаунт навсегда забанен администрацией.")
                        elif event.callback_query:
                            await event.callback_query.answer("❌ Вы забанены навсегда.", show_alert=True)
                        return # Полностью прекращаем обработку события
                    
                    # 2. Проверка временного бана
                    if ban_until > current_time:
                        remaining_min = int((ban_until - current_time) / 60)
                        ban_text = f"⏳ **Доступ ограничен.** Разблокировка через: {remaining_min} мин."
                        
                        if event.message:
                            await event.message.answer(ban_text)
                        elif event.callback_query:
                            await event.callback_query.answer(ban_text, show_alert=True)
                        return # Прекращаем обработку
                        
            except Exception as e:
                print(f"[ERROR IN BAN MIDDLEWARE]: {e}")

        # Если пользователь чист — передаем управление дальше в роутеры
        return await handler(event, data)
