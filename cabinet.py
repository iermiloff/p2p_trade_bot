import aiosqlite
import time
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from config import ADMIN_IDS
from database import DB_NAME, get_user_title, get_user_active_offers, cancel_user_offer
from constants import DIRECTION_TITLES

router = Router()

# Локальные статусы для истории сделок
STATUS_LABELS_LOCAL = {
    'completed': '✅Успешно завершена',
    'cancelled': '❌Отменена',
    'dispute': '⚠️ Диспут (Арбитраж)',
    'waiting_deposit': '⏳ Ожидание депозита крипты',
    'waiting_payment': '💸 Ожидание перевода фиата',
    'waiting_delivery': '📦 Проверка оплаты продавцом'
}

# 5 новых честных состояний FSM под ТЗ
class RequisitesStates(StatesGroup):
    waiting_for_card = State()
    waiting_for_crypto_bot = State()
    waiting_for_bybit = State()
    waiting_for_other = State()
    waiting_for_fkwallet = State()

def get_main_keyboard():
    """Клавиатура Главного меню P2P-платформы"""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⚙️ Мои Реквизиты", callback_data="lk_requisites")],
        [
            types.InlineKeyboardButton(text="📊 Статистика", callback_data="lk_stats"),
            types.InlineKeyboardButton(text="🔄 Активные сделки", callback_data="lk_active_deals"),
            types.InlineKeyboardButton(text="📜 История лотов", callback_data="lk_history")
        ],
        [types.InlineKeyboardButton(text="💎 Открыть Торговый Маркет (P2P)", callback_data="nav_gram_card")]
    ])

@router.callback_query(F.data == "open_main_menu")
async def open_menu_callback(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в Главное меню с жестким разделением: Юзер / Админ"""
    await callback.answer()
    await state.clear()
    user_id = callback.from_user.id
    
    # Если это Администратор — принудительно включаем админку и блокируем P2P-меню
    if user_id in ADMIN_IDS:
        import admin # Локальный импорт для генерации кнопок
        await callback.message.edit_text(
            "🛠 **Панель управления Администратора P2P**\n\nВыберите необходимый раздел для модерации платформы:",
            reply_markup=admin.get_admin_keyboard()
        )
    else:
        # Если обычный пользователь — отдаем стандартный P2P-интерфейс
        await callback.message.edit_text(
            "🏠 **Главное меню P2P платформы:**\n\n"
            "🛡 Все операции проходят строго через асинхронного Гаранта системы для исключения мошенничества и блокировок по 115-ФЗ.\n\n"
            "Используйте интерактивное меню ниже для работы:",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )

@router.callback_query(F.data == "lk_stats")
async def show_statistics(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        query = "SELECT nickname, user_status, rating, deals_count FROM users WHERE tg_id = ?"
        async with db.execute(query, (user_id,)) as cursor:
            user_data = await cursor.fetchone()
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="open_main_menu")]])
    if user_data:
        nickname, user_status, rating, deals_count = user_data
        user_title = await get_user_title(deals_count, rating)
        text = (
            f"👤 **Ваша статистика:**\n\n"
            f"• Никнейм: **{nickname}**\n"
            f"• Титул: **{user_title}**\n"
            f"• Роль: {user_status}\n"
            f"• ⭐Рейтинг: **{rating:.2f}**\n"
            f"• ✔️ Сделок: **{deals_count}**\n"
        )
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await callback.message.edit_text("❌ Ошибка: Профиль не найден.", reply_markup=kb)
@router.callback_query(F.data == "lk_history")
async def show_user_history(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        query = """
            SELECT deals.id, deals.buyer_id, deals.status, offers.direction, offers.amount 
            FROM deals
            JOIN offers ON deals.offer_id = offers.id
            WHERE deals.buyer_id = ? OR deals.seller_id = ?
            ORDER BY deals.id DESC LIMIT 5
        """
        async with db.execute(query, (user_id, user_id)) as cursor:
            my_history = await cursor.fetchall()
            
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="open_main_menu")]
    ])
    
    if not my_history:
        await callback.message.edit_text("📭 Ваша история сделок пока пуста.", reply_markup=kb)
        return
        
    text = "📜 **Ваши последние 5 P2P-сделок:**\n\n"
    for d_id, b_id, status, direction, amount in my_history:
        role = "🟢 Покупатель" if user_id == b_id else "🔴 Продавец"
        st_text = STATUS_LABELS_LOCAL.get(status, status)
        text += f"• **Сделка #{d_id}**\n  └ Объем: `{amount}`\n  └ Роль: {role}\n  └ Статус: {st_text}\n\n"
                
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@router.callback_query(F.data == "lk_requisites")
async def show_requisites_menu(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        query = "SELECT card, crypto_bot, bybit, other_wallets, fkwallet FROM requisites WHERE tg_id = ?"
        async with db.execute(query, (user_id,)) as cursor:
            req = await cursor.fetchone()
            
    card, c_bot, bybit, other, fk = req if req else ("", "", "", "", "")
    
    text = (
        f"⚙️ **Ваши реквизиты для получения выплат:**\n\n"
        f"💳 **1. Банковская Карта (Куда получаете рубли):**\n`{card if card else 'не заполнено'}`\n\n"
        f"🤖 **2. Адрес / Чек Крипта (Bot):**\n`{c_bot if c_bot else 'не заполнено'}`\n\n"
        f"📈 **3. Адрес / UID Крипта (Bybit):**\n`{bybit if bybit else 'не заполнено'}`\n\n"
        f"🌐 **4. Крипта (Другие кошельки):**\n`{other if other else 'не заполнено'}`\n\n"
        f"👛 **5. Номер кошелька FkWallet:**\n`{fk if fk else 'не заполнено'}`\n\n"
        f"Выберите раздел ниже для изменения данных:"
    )
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✏️ Изменить Карту", callback_data="req_edit_card")],
        [types.InlineKeyboardButton(text="✏️ Изменить Крипта (Bot)", callback_data="req_edit_cbot")],
        [types.InlineKeyboardButton(text="✏️ Изменить Крипта (Bybit)", callback_data="req_edit_bybit")],
        [types.InlineKeyboardButton(text="✏️ Изменить Крипта (Другие)", callback_data="req_edit_other")],
        [types.InlineKeyboardButton(text="✏️ Изменить FkWallet", callback_data="req_edit_fk")],
        [types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="open_main_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@router.callback_query(F.data == "req_edit_card")
async def edit_card_init(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(RequisitesStates.waiting_for_card)
    await callback.message.edit_text("💳 Введите номер вашей карты и название банка (одним сообщением):")

@router.callback_query(F.data == "req_edit_cbot")
async def edit_cbot_init(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(RequisitesStates.waiting_for_crypto_bot)
    await callback.message.edit_text("🤖 Введите реквизиты/адрес для получения активов через Telegram Crypto Bot:")

@router.callback_query(F.data == "req_edit_bybit")
async def edit_bybit_init(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(RequisitesStates.waiting_for_bybit)
    await callback.message.edit_text("📈 Введите ваш адрес кошелька или UID для зачисления монет на биржу Bybit:")

@router.callback_query(F.data == "req_edit_other")
async def edit_other_init(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(RequisitesStates.waiting_for_other)
    await callback.message.edit_text("🌐 Введите адрес вашего внешнего кошелька (USDT TRC20, TON, TrustWallet и т.д.):")

@router.callback_query(F.data == "req_edit_fk")
async def edit_fk_init(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(RequisitesStates.waiting_for_fkwallet)
    await callback.message.edit_text("👛 Введите номер вашего электронного кошелька FkWallet (например: F12345678):")
# --- ХЭНДЛЕРЫ ПРИЕМА ТЕКСТА И ЗАПИСИ В БД (MESSAGES) ---

@router.message(StateFilter(RequisitesStates.waiting_for_card), F.text)
async def process_card_saving(message: types.Message, state: FSMContext):
    text = message.text.strip()
    user_id = message.from_user.id
    await state.clear()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE requisites SET card = ? WHERE tg_id = ?", (text, user_id))
        await db.commit()
    try: await message.delete()        
    except: pass
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⚙️ Вернуться в Реквизиты", callback_data="lk_requisites")]])
    await message.answer("✅ **Реквизиты банковской карты успешно сохранены!**", reply_markup=kb, parse_mode="Markdown")

@router.message(StateFilter(RequisitesStates.waiting_for_crypto_bot), F.text)
async def process_cbot_saving(message: types.Message, state: FSMContext):
    text = message.text.strip()
    user_id = message.from_user.id
    await state.clear()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE requisites SET crypto_bot = ? WHERE tg_id = ?", (text, user_id))
        await db.commit()
    try: await message.delete()        
    except: pass
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⚙️ Вернуться в Реквизиты", callback_data="lk_requisites")]])
    await message.answer("✅ **Реквизиты для Crypto Bot успешно привязаны!**", reply_markup=kb, parse_mode="Markdown")

@router.message(StateFilter(RequisitesStates.waiting_for_bybit), F.text)
async def process_bybit_saving(message: types.Message, state: FSMContext):
    text = message.text.strip()
    user_id = message.from_user.id
    await state.clear()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE requisites SET bybit = ? WHERE tg_id = ?", (text, user_id))
        await db.commit()
    try: await message.delete()        
    except: pass
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⚙️ Вернуться в Реквизиты", callback_data="lk_requisites")]])
    await message.answer("✅ **Реквизиты Bybit успешно зафиксированы!**", reply_markup=kb, parse_mode="Markdown")

@router.message(StateFilter(RequisitesStates.waiting_for_other), F.text)
async def process_other_saving(message: types.Message, state: FSMContext):
    text = message.text.strip()
    user_id = message.from_user.id
    await state.clear()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE requisites SET other_wallets = ? WHERE tg_id = ?", (text, user_id))
        await db.commit()
    try: await message.delete()        
    except: pass
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⚙️ Вернуться в Реквизиты", callback_data="lk_requisites")]])
    await message.answer("✅ **Адрес внешнего кошелька успешно обновлен!**", reply_markup=kb, parse_mode="Markdown")

@router.message(StateFilter(RequisitesStates.waiting_for_fkwallet), F.text)
async def process_fk_saving(message: types.Message, state: FSMContext):
    text = message.text.strip()
    user_id = message.from_user.id
    await state.clear()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE requisites SET fkwallet = ? WHERE tg_id = ?", (text, user_id))
        await db.commit()
    try: await message.delete()        
    except: pass
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⚙️ Вернуться в Реквизиты", callback_data="lk_requisites")]])
    await message.answer("✅ **Номер кошелька FkWallet успешно сохранен!**", reply_markup=kb, parse_mode="Markdown")


# --- МОДУЛЬ ПЕРЕХВАТА АКТИВНЫХ СДЕЛК ИЗ ЛК ---
@router.callback_query(F.data == "lk_active_deals")
async def show_active_deals_from_menu(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.clear()
    tg_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        query = """
            SELECT id, status, buyer_id, seller_id, guarantor_id 
            FROM deals 
            WHERE (buyer_id = ? OR seller_id = ? OR guarantor_id = ?) 
            AND status IN ('waiting_deposit', 'waiting_payment', 'waiting_delivery', 'dispute')
            ORDER BY id DESC LIMIT 1
        """
        async with db.execute(query, (tg_id, tg_id, tg_id)) as cursor:
            active_deal = await cursor.fetchone()
            
    kb_back = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="open_main_menu")]])
    
    if not active_deal:
        await callback.message.edit_text("📭 **У вас нет active-сделок на данный момент.**", reply_markup=kb_back)
        return

    deal_id, status, buyer_id, seller_id, guarantor_id = active_deal
    
    # Передаем явный именованный параметр edit_message_obj=callback для пуленепробиваемой отрисовки без крашей
    from deals.actions import send_deal_interface_to_user
    await send_deal_interface_to_user(bot, tg_id, deal_id, status, buyer_id, seller_id, guarantor_id, edit_message_obj=callback)

