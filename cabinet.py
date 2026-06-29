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

# Возврат в главное меню
@router.callback_query(F.data == "open_main_menu")
async def open_menu_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear() # На всякий случай очищаем FSM при возврате в меню
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

# --- РАЗДЕЛ: РЕКВИЗИТЫ (ОСНОВНОЕ ОКНО) ---
@router.callback_query(F.data == "lk_requisites")
async def show_requisites_menu(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    await render_requisites(callback.message, user_id)

async def render_requisites(message: types.Message, user_id: int):
    """Вспомогательная асинхронная функция отрисовки реквизитов из БД"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT card, piastrix, ton FROM requisites WHERE tg_id = ?", 
            (user_id,)
        ) as cursor:
            req_data = await cursor.fetchone()
            
    card, piastrix, ton = req_data if req_data else ("", "", "")
    
    # Красивое форматирование для вывода пользователю
    card_display = card if card and card.strip() else "❌ Не указано"
    piastrix_display = piastrix if piastrix and piastrix.strip() else "❌ Не указано"
    ton_display = ton if ton and ton.strip() else "❌ Не указано"
    
    text = (
        f"⚙️ **Ваши платежные реквизиты для сделок:**\n\n"
        f"💳 **Банковская карта:**\n`{card_display}`\n\n"
        f"📱 **Кошелек Piastrix:**\n`{piastrix_display}`\n\n"
        f"💎 **TON (GRAM) кошелек:**\n`{ton_display}`\n\n"
        f"Вы можете в любой момент обновить их, нажав на кнопки ниже."
    )
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✏ Изменить Карту", callback_data="edit_card")],
        [types.InlineKeyboardButton(text="✏ Изменить Piastrix", callback_data="edit_piastrix")],
        [types.InlineKeyboardButton(text="✏ Изменить TON", callback_data="edit_ton")],
        [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
    ])
    
    # Перерисовываем текущее окно, чтобы интерфейс не прыгал от новых сообщений
    try:
        await message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        # Если текст сообщения не изменился, редактирование вызовет ошибку, тогда просто шлем новое
        await message.answer(text, reply_markup=kb, parse_mode="Markdown")

# --- БЛОК ИЗМЕНЕНИЯ РЕКВИЗИТОВ ---

# 1. КАРТА
@router.callback_query(F.data == "edit_card")
async def edit_card_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(RequisitesStates.waiting_for_card)
    await callback.message.answer("💳 **Ввод карты:**\nПришлите в ответном сообщении номер вашей карты, название банка и имя получателя:")

@router.message(RequisitesStates.waiting_for_card)
async def edit_card_save(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text.strip()
    await state.clear() # Сбрасываем FSM
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE requisites SET card = ? WHERE tg_id = ?", (text, user_id))
        await db.commit() # Фиксируем в БД
        
    # Отправляем новое сообщение-подтверждение
    await message.answer("✅ Реквизиты банковской карты успешно зафиксированы в системе!")
    # Перерисовываем меню реквизитов, чтобы пользователь сразу увидел изменения
    await render_requisites(message, user_id)

# 2. PIASTRIX
@router.callback_query(F.data == "edit_piastrix")
async def edit_piastrix_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(RequisitesStates.waiting_for_piastrix)
    await callback.message.answer("📱 **Ввод Piastrix:**\nПришлите в ответном сообщении номер вашего кошелька Piastrix (например, P12345678):")

@router.message(RequisitesStates.waiting_for_piastrix)
async def edit_piastrix_save(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text.strip()
    await state.clear()
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE requisites SET piastrix = ? WHERE tg_id = ?", (text, user_id))
        await db.commit()
        
    await message.answer("✅ Реквизиты кошелька Piastrix успешно зафиксированы в системе!")
    await render_requisites(message, user_id)

# 3. TON / GRAM
@router.callback_query(F.data == "edit_ton")
async def edit_ton_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(RequisitesStates.waiting_for_ton)
    await callback.message.answer("💎 **Ввод TON:**\nПришлите ваш TON-адрес (EQ... / UQ...) и Memo через пробел (если Memo нужен):")

@router.message(RequisitesStates.waiting_for_ton)
async def edit_ton_save(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text.strip()
    await state.clear()
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE requisites SET ton = ? WHERE tg_id = ?", (text, user_id))
        await db.commit()
        
    await message.answer("✅ Реквизиты TON (GRAM) успешно зафиксированы в системе!")
    await render_requisites(message, user_id)
