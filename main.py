import asyncio
import random
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from config import BOT_TOKEN
from database import init_db, DB_NAME

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
                return user[0]

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
                # Транзакция откатилась, уходим на новую итерацию генерации.
                continue

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    tg_id = message.from_user.id
    
    # Безопасно регистрируем и получаем постоянный анонимный ник
    nickname = await register_user_safely(tg_id)
    
    # Проверяем текущий статус верификации
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT is_verified FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            res = await cursor.fetchone()
            is_verified = res[0] if res else 0

    if is_verified:
        await message.answer(
            f"Добро пожаловать обратно, **{nickname}**!\n"
            f"Вы верифицированы и можете использовать P2P-обмен."
        )
    else:
        # Для неверифицированных пользователей доступна только кнопка верификации
        # Логику отправки заявки админам мы привяжем к этой кнопке на следующем шаге
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🛡 Пройти верификацию", callback_data="start_verification")]
        ])
        await message.answer(
            f"Привет! Твой анонимный никнейм в системе: **{nickname}**.\n\n"
            f"Для безопасности участников, все сделки доступны только после ручной проверки администратором.\n"
            f"Нажмите на кнопку ниже, чтобы отправить заявку на верификацию.",
            reply_markup=kb
        )

async def main():
    # Инициализируем структуру таблиц при запуске проекта
    await init_db()
    print("База данных проверена. Запуск пуллинга бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
