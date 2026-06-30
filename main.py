import asyncio
import random
import time
import aiosqlite
from aiogram import Bot, Dispatcher, types, Router
from aiogram.filters import CommandStart, Command
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN, ADMIN_IDS
from database import init_db, DB_NAME
from ban_middleware import BanCheckMiddleware

# Импортируем наши функциональные модули
import verification
import cabinet
import offers
import deals
import admin  # Наша админ-панель

# Инициализируем бота и Диспетчер строго с MemoryStorage
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Главный роутер для базовых команд (старт, дебаг, баны)
main_router = Router()

ADJECTIVES = ["Epic", "Brave", "Silent", "Golden", "Swift", "Mad", "Crazy", "Happy"]
NOUNS = ["Whale", "Punk", "Trader", "Shark", "Phoenix", "Falcon", "Tiger", "Bear"]

async def register_user_safely(tg_id: int) -> str:
    """Атомарная регистрация пользователя с гарантией уникальности никнейма"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT nickname FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            user = await cursor.fetchone()
            if user:
                return user[0]

        while True:
            nickname = f"{random.choice(ADJECTIVES)} {random.choice(NOUNS)}"
            try:
                await db.execute("INSERT INTO users (tg_id, nickname) VALUES (?, ?)", (tg_id, nickname))
                await db.execute("INSERT INTO requisites (tg_id) VALUES (?)", (tg_id,))
                await db.commit()
                return nickname
            except aiosqlite.IntegrityError:
                continue

@main_router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: types.Message):
    tg_id = message.from_user.id
    nickname = await register_user_safely(tg_id)
    
    # ⚡ ВАЖНО: Принудительный апдейт для администраторов при ЛЮБОМ вводе /start
    if tg_id in ADMIN_IDS:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET is_verified = 1, user_status = 'super_trader' WHERE tg_id = ?", (tg_id,))
            await db.commit()

    # Проверяем текущий статус верификации в базе данных
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT is_verified FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            res = await cursor.fetchone()
            is_verified = res[0] if res else 0

    # ⚡ 1. ПЕРВЫМ ДЕЛОМ ДЛЯ ВСЕХ ПРОВЕРЯЕМ АКТИВНУЮ СДЕЛКУ
    async with aiosqlite.connect(DB_NAME) as db:
        query = """
            SELECT id, status, buyer_id, seller_id, use_guarantor 
            FROM deals 
            WHERE (buyer_id = ? OR seller_id = ?) 
            AND status IN ('waiting_payment', 'waiting_delivery', 'dispute')
        """
        async with db.execute(query, (tg_id, tg_id)) as cursor:
            active_deal = await cursor.fetchone()

    if active_deal:
        deal_id, status, buyer_id, seller_id, use_guarantor = active_deal
        kb = None
        role_text = "Покупатель" if tg_id == buyer_id else "Продавец"
        
        if status == 'waiting_payment' and tg_id == buyer_id:
            btn_text = "🟩 Я перевел средства Гаранту" if use_guarantor else "🟩 Я перевел средства"
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text=btn_text, callback_data=f"deal_action_paid_{deal_id}")]
            ])
        elif status == 'waiting_delivery' and tg_id == seller_id:
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🎉 Обмен завершен (Средства у меня)", callback_data=f"deal_action_completed_{deal_id}")],
                [types.InlineKeyboardButton(text="🚨 Вызвать Гаранта (Спор)", callback_data=f"deal_action_dispute_{deal_id}")]
            ])
        elif status == 'waiting_delivery' and tg_id == buyer_id:
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🚨 Вызвать Гаранта (Спор)", callback_data=f"deal_action_dispute_{deal_id}")]
            ])

        status_labels = {
            'waiting_payment': 'Ожидание оплаты от Покупателя',
            'waiting_delivery': 'Ожидание подтверждения/выдачи от Продавца',
            'dispute': 'Внештатная ситуация (Открыт спор)'
        }

        await message.answer(
            f"🔄 **Вы вернулись в активную сделку #{deal_id}!**\n\n"
            f"👤 Ваша роль: **{role_text}**\n"
            f"📊 Текущий статус: _{status_labels.get(status, status)}_\n"
            f"💬 Анонимный чат по-прежнему активен.\n\n"
            f"Если кнопки управления пропали, используйте панель ниже:",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        return

    # ⚡ 2. ЕСЛИ АКТИВНОЙ СДЕЛКИ НЕТ — ВЫДАЕМ СООТВЕТСТВУЮЩЕЕ МЕНЮ
    if is_verified:
        if tg_id in ADMIN_IDS:
            await message.answer(
                f"🛠 **Добро пожаловать в панель управления, {nickname}!**\n"
                f"Вам, как администратору, отключены стандартные торговые функции платформы.\n\n"
                f"Выберите необходимый раздел для модерации:",
                reply_markup=admin.get_admin_keyboard()
            )
        else:
            await message.answer(
                f"Добро пожаловать обратно, **{nickname}**!\nВы можете использовать P2P-обмен. Выберите нужный раздел:",
                reply_markup=cabinet.get_main_keyboard()
            )
    else:
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🛡 Пройти верификацию", callback_data="start_verification")]
        ])
        await message.answer(
            f"Привет! Твой анонимный никнейм: **{nickname}**.\n\nДля безопасности сделки доступны только после верификации администратором.\nНажмите на кнопку ниже, чтобы отправить заявку:",
            reply_markup=kb
        )

# --- ПАНЕЛЬ ДИАГНОСТИКИ ---
@main_router.message(Command("debug"), F.chat.type == "private")
async def cmd_debug_db(message: types.Message):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT * FROM users WHERE tg_id = ?", (user_id,)) as c1:
            u_data = await c1.fetchone()
        async with db.execute("SELECT * FROM requisites WHERE tg_id = ?", (user_id,)) as c2:
            r_data = await c2.fetchone()
            
    text = (
        f"🔍 **Диагностика базы данных:**\n\n"
        f"Ваш Telegram ID: `{user_id}`\n"
        f"Запись в Users: `{u_data}`\n"
        f"Запись в Requisites: `{r_data}`"
    )
    await message.answer(text)

# --- ПАНЕЛЬ МОДЕРАЦИИ: БАНЫ ---
@main_router.message(lambda msg: msg.from_user.id in ADMIN_IDS and msg.chat.type == "private" and msg.text and msg.text.startswith("/"))
async def admin_ban_commands(message: types.Message):
    text = message.text.strip()
    
    if text.startswith("/permban"):
        args = text.split()
        if len(args) < 2 or not args[1].isdigit():
            await message.answer("⚠ Использование: `/permban [tg_id]`")
            return
        target_id = int(args[1])
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET is_banned = 1 WHERE tg_id = ?", (target_id,))
            await db.commit()
        await message.answer(f"⛔ Пользователь `{target_id}` забанен НАВСЕГДА.")

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
        await message.answer(f"⏳ Пользователь `{target_id}` заблокирован на `{minutes}` минут.")

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

async def main():
    await init_db()
    
    # Внутренний Middleware модерации банов
    dp.message.middleware(BanCheckMiddleware())
    dp.callback_query.middleware(BanCheckMiddleware())
    
    # ⚡ СУПЕР-ИСПРАВЛЕНИЕ: Точный приоритет роутеров. 
    # Сначала проверяются базовые команды (старт), затем админка, а ЛК и обмены — в конце!
    dp.include_router(main_router)              # 1. Базовые команды (/start, /debug)
    dp.include_router(admin.router)             # 2. Роутер админ-панели (admin.py)
    dp.include_router(verification.router)      # 3. Верификация пользователей
    dp.include_router(cabinet.router)           # 4. Личный кабинет 
    dp.include_router(offers.router)            # 5. Торговый стакан заявок
    dp.include_router(deals.router)             # 6. Сделки и Анонимный чат
    
    import tasks
    asyncio.create_task(tasks.auto_cancel_expired_deals(bot))
    
    print("Base checked. Background timers active. Starting polling...")
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())
