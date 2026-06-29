import aiosqlite
from aiogram import Router, F, types
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from database import DB_NAME
from constants import STATUS_NAMES

router = Router()

# Состояния FSM для поочередного ввода реквизитов
class RequisitesStates(StatesGroup):
    waiting_for_card = State()
    waiting_for_piastrix = State()
    waiting_for_ton = State()

def get_main_keyboard():
    """Генерация кнопок Главного меню для верифицированных пользователей"""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⚙️ Мои Реквизиты", callback_data="lk_requisites")],
        [types.InlineKeyboardButton(text="📊 Моя Статистика", callback_data="lk_stats")],
        [types.InlineKeyboardButton(text="🔄 GRAM ⇄ Карты", callback_data="nav_gram_card")],
        [types.InlineKeyboardButton(text="🔄 GRAM ⇄ Piastrix", callback_data="nav_gram_piastrix")],
        [types.InlineKeyboardButton(text="🔄 Карты ⇄ Piastrix", callback_data="nav_card_piastrix")]
    ])

# Меняем логику отображения меню (вызывается из main.py, если юзер прошел KYC)
@router.callback_query(F.data == "open_main_menu")
async def open_menu_callback(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer("🏠 Главное меню P2P платформы:", reply_markup=get_main_keyboard())

# --- РАЗДЕЛ: СТАТИСТИКА ---
@router.callback_query(F.data == "lk_stats")
async def show_statistics(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT nickname, user_status, rating, deals_count FROM users WHERE tg_id = ?", 
            (user_id,)
        ) as cursor:
            user_data = await cursor.fetchone()
            
    if user_data:
        nickname, user_status, rating, deals_count = user_data
        status_text = STATUS_NAMES.get(user_status, "🟢 Верифицированный")
        
        text = (
            f"📊 **Ваша статистика в системе:**\n\n"
            f"👤 Никнейм: **{nickname}**\n"
            f"🎖 Статус: {status_text}\n"
            f"⭐ Рейтинг: **{rating:.1f}**\n"
            f"🤝 Успешных сделок: **{deals_count}**\n"
        )
        
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
        ])
        await callback.message.answer(text, reply_markup=kb)

# --- РАЗДЕЛ: РЕКВИЗИТЫ ---
@router.callback_query(F.data == "lk_requisites")
async def show_requisites_menu(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT card, piastrix, ton FROM requisites WHERE tg_id = ?", 
            (user_id,)
        ) as cursor:
            req_data = await cursor.fetchone()
            
    card, piastrix, ton = req_data if req_data else ("Не указано", "Не указано", "Не указано")
    card = card if card else "❌ Не указано"
    piastrix = piastrix if piastrix else "❌ Не указано"
    ton = ton if ton else "❌ Не указано"
    
    text = (
        f"⚙ **Ваши платежные реквизиты для сделок:**\n\n"
        f"💳 Банковская карта:\n`{card}`\n\n"
        f"📱 Кошелек Piastrix:\n`{piastrix}`\n\n"
        f"💎 TON (GRAM) кошелек:\n`{ton}`\n\n"
        f"Вы можете в любой момент обновить их, нажав на кнопки ниже."
    )
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✏ Изменить Карту", callback_data="edit_card")],
        [types.InlineKeyboardButton(text="✏ Изменить Piastrix", callback_data="edit_piastrix")],
        [types.InlineKeyboardButton(text="✏ Изменить TON", callback_data="edit_ton")],
        [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
    ])
    
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")

# Ввод Карты
@router.callback_query(F.data == "edit_card")
async def edit_card_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(RequisitesStates.waiting_for_card)
    await callback.message.answer("💳 Введите номер вашей карты, название банка и имя получателя (одним сообщением):")

@router.message(RequisitesStates.waiting_for_card)
async def edit_card_save(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text.strip()
    await state.clear()
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE requisites SET card = ? WHERE tg_id = ?", (text, user_id))
        await db.commit()
        
    await message.answer("✅ Реквизиты банковской карты успешно обновлены!")
    # Имитируем переход обратно в меню реквизитов
    await show_requisites_menu_mock(message, user_id)

# Ввод Piastrix
@router.callback_query(F.data == "edit_piastrix")
async def edit_piastrix_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(RequisitesStates.waiting_for_piastrix)
    await callback.message.answer("📱 Введите номер вашего кошелька Piastrix (например, P12345678):")

@router.message(RequisitesStates.waiting_for_piastrix)
async def edit_piastrix_save(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text.strip()
    await state.clear()
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE requisites SET piastrix = ? WHERE tg_id = ?", (text, user_id))
        await db.commit()
        
    await message.answer("✅ Реквизиты Piastrix успешно обновлены!")
    await show_requisites_menu_mock(message, user_id)

# Ввод TON
@router.callback_query(F.data == "edit_ton")
async def edit_ton_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(RequisitesStates.waiting_for_ton)
    await callback.message.answer("💎 Введите ваш TON-адрес (EQ... / UQ...) и Memo через пробел, если он необходим:")

@router.message(RequisitesStates.waiting_for_ton)
async def edit_ton_save(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text.strip()
    await state.clear()
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE requisites SET ton = ? WHERE tg_id = ?", (text, user_id))
        await db.commit()
        
    await message.answer("✅ TON (GRAM) реквизиты успешно обновлены!")
    await show_requisites_menu_mock(message, user_id)

async def show_requisites_menu_mock(message: types.Message, user_id: int):
    """Вспомогательная функция для обновления экрана после сохранения ввода"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT card, piastrix, ton FROM requisites WHERE tg_id = ?", (user_id,)) as cursor:
            req_data = await cursor.fetchone()
    card, piastrix, ton = req_data if req_data else ("❌ Не указано", "❌ Не указано", "❌ Не указано")
    text = f"⚙ **Ваши платежные реквизиты для сделок:**\n\n" \
           f"💳 Банковская карта:\n`{card if card else '❌ Не указано'}`\n\n" \
           f"📱 Кошелек Piastrix:\n`{piastrix if piastrix else '❌ Не указано'}`\n\n" \
           f"💎 TON (GRAM) кошелек:\n`{ton if ton else '❌ Не указано'}`"
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✏ Изменить Карту", callback_data="edit_card")],
        [types.InlineKeyboardButton(text="✏ Изменить Piastrix", callback_data="edit_piastrix")],
        [types.InlineKeyboardButton(text="✏ Изменить TON", callback_data="edit_ton")],
        [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
    ])
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")
