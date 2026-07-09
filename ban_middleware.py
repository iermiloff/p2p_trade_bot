import aiosqlite
import time
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from database import DB_NAME

# Локальный ин-мемори кэш для защиты от быстрого клик-флуда (анти-DOS)
# Ключ: user_id, Значение: timestamp последнего клика
THROTTLING_CACHE = {}
# Минимальная задержка между кликами по кнопкам/отправкой сообщений в секундах
RATE_LIMIT = 0.5

class PlatformSecurityMiddleware(BaseMiddleware):
    """
    Единый защитный комплекс платформы:
    1. Защита от одновременных запросов (Throttling / Rate-Limit)
    2. Проверка глобальных блокировок (Вечный / Временный бан)
    """
    async def __call__(self, handler, event, data: dict):
        user_id = event.from_user.id
        current_time = time.time()
        current_time_int = int(current_time)

        # --- 1. МОДУЛЬ ЗАЗАЩИТЫ ОТ ФЛУДА (THROTTLING) ---
        if user_id in THROTTLING_CACHE:
            last_request_time = THROTTLING_CACHE[user_id]
            if current_time - last_request_time < RATE_LIMIT:
                # Если пользователь спамит кликами, гасим запрос всплывающим алертом
                if isinstance(event, CallbackQuery):
                    await event.answer("⚠️ Пожалуйста, не нажимайте кнопки так быстро!", show_alert=False)
                return  # Обрываем выполнение, запрос не дойдет до СУБД и хэндлеров

        # Обновляем таймштамп последней активности пользователя
        THROTTLING_CACHE[user_id] = current_time

        # Очищаем старый кэш раз в 500 запросов, чтобы не забивать память сервера
        if len(THROTTLING_CACHE) > 500:
            # Удаляем записи старше 2 секунд
            expired_keys = [k for k, v in THROTTLING_CACHE.items() if current_time - v > 2.0]
            for k in expired_keys:
                THROTTLING_CACHE.pop(k, None)

        # --- 2. МОДУЛЬ ПРОВЕРКИ БАНОВ В БД ---
        try:
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute(
                    "SELECT is_banned, ban_until FROM users WHERE tg_id = ?", 
                    (user_id,)
                ) as cursor:
                    res = await cursor.fetchone()
                    
            if res:
                is_banned, ban_until = res

                # А. Вечный бан
                if is_banned == 1:
                    if isinstance(event, Message):
                        await event.answer("❌ **Доступ заблокирован.** Ваш аккаунт навсегда забанен администрацией.")
                    elif isinstance(event, CallbackQuery):
                        await event.answer("❌ Доступ ограничен. Вы забанены навсегда.", show_alert=True)
                    return

                # Б. Временный бан
                if ban_until > current_time_int:
                    remaining_min = int((ban_until - current_time_int) / 60)
                    if remaining_min <= 0:
                        remaining_min = 1
                    ban_text = f"⏳ **Доступ ограничен.** Разблокировка через: {remaining_min} мин."

                    if isinstance(event, Message):
                        await event.answer(ban_text)
                    elif isinstance(event, CallbackQuery):
                        await event.answer(ban_text, show_alert=True)
                    return
                    
        except Exception as e:
            print(f"[КРИТИЧЕСКАЯ ОШИБКА МИДЛВАРЯ БЕЗОПАСНОСТИ]: {e}")

        # Все проверки пройдены успешно, передаем управление дальше по цепочке фреймворка
        return await handler(event, data)

