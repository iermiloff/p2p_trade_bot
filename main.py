import asyncio
import random
import time
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from config import BOT_TOKEN, ADMIN_IDS
from database import init_db, DB_NAME
from ban_middleware import BanCheckMiddleware

# Импортируем наши созданные функциональные модули
import tasks
import verification
import cabinet
import offers
import deals

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Списки для генерации анонимных никнеймов контрагентов
ADJECTIVES = ["Epic", "Brave", "Silent", "Golden", "Swift", "Mad", "Crazy", "Happy"]
NOUNS = ["Whale", "Punk", "Trader", "Shark", "Phoenix", "Falcon", "Tiger", "Bear"]

async def register_user_safely(tg_id: int) -> str:
    """
    Атомарная регистрация пользователя с гарантией уникальности никнейма.
    Защищает от уязвимости параллельных запросов (Race Condition).
    """
    async with aiosqlite.connect(DB_NAME) as db:
        # Проверяем, существует ли уже пользователь в системе
        async with db.execute("SELECT nickname FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            user = await cursor.fetchone()
            if user:
                return user[0]  # Возвращаем уже существующий никнейм

        # Если пользователя нет, генерируем уникальный ник в цикле
        while True:
            nickname = f"{random.choice(ADJECTIVES)} {random.choice(NOUNS)}"
            try:
                # Попытка записи. Если никнейм занят, сработает UNIQUE constraint базы данных
                await db.execute("INSERT INTO users (tg_id, nickname) VALUES (?, ?)", (tg_id, nickname))
                await db.execute("INSERT INTO requisites (tg_id) VALUES (?)", (tg_id,))
                await db.commit()
                return nickname
            except aiosqlite.IntegrityError:
                # Никнейм перехватил другой поток/пользователь миллисекундой ранее.
                # Транзакция автоматически откатилась, уходим на новую итерацию генерации.
                continue
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    tg_id = message.from_user.id
    
    # Безопасно регистрируем и получаем постоянный анонимный ник
    nickname = await register_user_safely(tg_id)
    
    # Проверяем текущий статус верификации в базе данных
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT is_verified FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            res = await cursor.fetchone()
            is_verified = res[0] if res else 0

    # ⚡ ДОБАВЛЯЕМ АВТО-ВЕРИФИКАЦИЮ ДЛЯ АДМИНИСТРАТОРОВ:
    if tg_id in ADMIN_IDS:
        if not is_verified:
            # Автоматически проставляем статус верификации в БД, если админ зашел впервые
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("UPDATE users SET is_verified = 1, user_status = 'super_trader' WHERE tg_id = ?", (tg_id,))
                await db.commit()
            is_verified = 1

    if is_verified:
        # Если верифицирован (или это админ) — отправляем красивое Главное Меню
        await message.answer(
            f"Добро пожаловать обратно, **{nickname}**!\n"
            f"Вы верифицированы и можете использовать P2P-обмен. Выберите нужный раздел:",
            reply_markup=cabinet.get_main_keyboard()
        )
    else:
        # Для неверифицированных пользователей доступна только одна кнопка
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🛡 Пройти верификацию", callback_data="start_verification")]
        ])
        await message.answer(
            f"Привет! Твой анонимный никнейм в системе: **{nickname}**.\n\n"
            f"Для безопасности участников, все сделки доступны только после ручной проверки администратором.\n"
            f"Нажмите на кнопку ниже, чтобы отправить заявку на верификацию.",
            reply_markup=kb
        )

# --- ПАНЕЛЬ МОДЕРАЦИИ: АДМИН-КОМАНДЫ БЛОКИРОВКИ ---
@dp.message(lambda msg: msg.from_user.id in ADMIN_IDS)
async def admin_ban_commands(message: types.Message):
    """Обработчик команд блокировки для администраторов"""
    text = message.text.strip()
    
    # 🛑 КОМАНДА 1: Вечный бан. Формат: /permban [tg_id]
    if text.startswith("/permban"):
        args = text.split()
        if len(args) < 2 or not args[1].isdigit():
            await message.answer("⚠ Использование: `/permban [tg_id]`")
            return
        target_id = int(args[1])
        
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET is_banned = 1 WHERE tg_id = ?", (target_id,))
            await db.commit()
        await message.answer(f"⛔ Пользователь `{target_id}` забанен **НАВСЕГДА** за попытку скама.")
        try:
            await bot.send_message(target_id, "❌ Вы были навсегда заблокированы в боте администрацией.")
        except Exception: pass

    # ⏳ КОМАНДА 2: Временный бан. Формат: /tempban [tg_id] [минуты]
    elif text.startswith("/tempban"):
        args = text.split()
        if len(args) < 3 or not args[1].isdigit() or not args[2].isdigit():
            await message.answer("⚠ Использование: `/tempban [tg_id] [минуты]`")
            return
        target_id = int(args[1])
        minutes = int(args[2])
        
        ban_timestamp = int(time.time()) + (minutes * 60)
        
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET ban_until = ? WHERE tg_id = ?", (ban_timestamp, target_id))
            await db.commit()
        await message.answer(f"⏳ Пользователь `{target_id}` временно заблокирован на `{minutes}` минут.")
        try:
            await bot.send_message(target_id, f"⏳ Вы временно заблокированы на {minutes} минут на время разбирательства.")
        except Exception: pass

    # 🔓 КОМАНДА 3: Разбан. Формат: /unban [tg_id]
    elif text.startswith("/unban"):
        args = text.split()
        if len(args) < 2 or not args[1].isdigit():
            await message.answer("⚠ Использование: `/unban [tg_id]`")
            return
        target_id = int(args[1])
        
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET is_banned = 0, ban_until = 0 WHERE tg_id = ?", (target_id,))
            await db.commit()
        await message.answer(f"✅ Пользователь `{target_id}` полностью разблокирован.")
        try:
            await bot.send_message(target_id, "🎉 Ограничения с вашего аккаунта сняты. Вы снова можете использовать бота.")
        except Exception: pass

async def main():
    # Инициализируем структуру таблиц при запуске проекта
    await init_db()
    
    # Подключаем защиту от забаненных пользователей на все типы входящих событий
    dp.message.middleware(BanCheckMiddleware())
    dp.callback_query.middleware(BanCheckMiddleware())
    
    # Подключаем роутеры всех наших модулей к главному диспетчеру
    dp.include_router(verification.router)
    dp.include_router(cabinet.router)
    dp.include_router(offers.router)
    dp.include_router(deals.router)
    
async def main():
    # Инициализируем структуру таблиц при запуске проекта
    await init_db()
    
    # Подключаем защиту от забаненных пользователей
    dp.message.middleware(BanCheckMiddleware())
    dp.callback_query.middleware(BanCheckMiddleware())
    
    # СТРОГИЙ ПОРЯДОК ПОДКЛЮЧЕНИЯ РОУТЕРОВ (От легких к тяжелым)
    dp.include_router(cabinet.router)       # 1. Личный кабинет (Реквизиты FSM)
    dp.include_router(offers.router)        # 2. Торговый стакан заявок
    dp.include_router(verification.router)  # 3. Верификация
    dp.include_router(deals.router)         # 4. Сделки и Анонимный чат (в самом конце!)
    
    # Запускаем автоматический таймер отмены сделок в фоне
    asyncio.create_task(tasks.auto_cancel_expired_deals(bot))
    
    print("Base checked. Background timers active. Starting polling...")
    await dp.start_polling(bot)
    
@dp.message(lambda msg: msg.text == "/debug")
async def cmd_debug_db(message: types.Message):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT * FROM users WHERE tg_id = ?", (user_id,)) as c1:
            u_data = await c1.fetchone()
        async with db.execute("SELECT * FROM requisites WHERE tg_id = ?", (user_id,)) as c2:
            r_data = await c2.fetchone()
            
    text = (
        f"🔍 **Отладочная информация:**\n\n"
        f"Ваш ID: `{user_id}`\n"
        f"Данные Users: `{u_data}`\n"
        f"Данные Requisites: `{r_data}`"
    )
    await message.answer(text, parse_mode="Markdown")

if __name__ == "__main__":
    asyncio.run(main())

