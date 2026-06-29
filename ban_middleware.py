import aiosqlite
import time
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from database import DB_NAME

class BanCheckMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        # Middleware может перехватывать и обычные сообщения, и нажатия кнопок (CallbackQuery)
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user:
            user_id = user.id
            current_time = int(time.time())

            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute(
                    "SELECT is_banned, ban_until FROM users WHERE tg_id = ?", 
                    (user_id,)
                ) as cursor:
                    res = await cursor.fetchone()

            if res:
                is_banned, ban_until = res
                
                # 1. Проверяем вечный бан
                if is_banned == 1:
                    if isinstance(event, Message):
                        await event.answer("❌ **Доступ заблокирован.** Ваш аккаунт навсегда забанен администрацией за нарушение правил платформы.")
                    elif isinstance(event, CallbackQuery):
                        await event.answer("❌ Вы забанены навсегда.", show_alert=True)
                    return # Прерываем выполнение, дальше код бота не пойдет
                
                # 2. Проверяем временный бан
                if ban_until > current_time:
                    remaining_min = int((ban_until - current_time) / 60)
                    ban_text = f"⏳ **Доступ временно ограничен.** Вы заблокированы на время разбирательства. До разблокировки осталось: {remaining_min} мин."
                    
                    if isinstance(event, Message):
                        await event.answer(ban_text)
                    elif isinstance(event, CallbackQuery):
                        await event.answer(ban_text, show_alert=True)
                    return # Прерываем выполнение

        # Если пользователь не забанен, передаем управление дальше по цепочке
        return await handler(event, data)
