import aiosqlite
import time
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from config import ADMIN_IDS, ADMIN_CHAT_ID
from database import DB_NAME, get_user_title
from constants import STATUS_NAMES

router = Router()

# Состояния машины состояний (FSM) для пошагового ввода реквизитов
class RequisitesStates(StatesGroup):
    waiting_for_card = State()
    waiting_for_piastrix = State()
    waiting_for_ton = State()

def get_main_keyboard():
    """Генерация кнопок Главного меню P2P-платформы"""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⚙️ Мои Реквизиты", callback_data="lk_requisites")],
        [
            types.InlineKeyboardButton(text="📊 Статистика", callback_data="lk_stats"),
            types.InlineKeyboardButton(text="🔄 Активные сделки", callback_data="lk_active_deals"),
            types.InlineKeyboardButton(text="📜 История", callback_data="lk_history")
        ],
        [types.InlineKeyboardButton(text="🔄 GRAM ⇄ Карты", callback_data="nav_gram_card")],
        [types.InlineKeyboardButton(text="🔄 GRAM ⇄ Piastrix", callback_data="nav_gram_piastrix")],
        [types.InlineKeyboardButton(text="🔄 Карты ⇄ Piastrix", callback_data="nav_card_piastrix")]
    ])

# --- ВОЗВРАТ В ГЛАВНОЕ МЕНЮ ИЛИ АДМИНКУ (СТРОГО РЕДАКТИРОВАНИЕМ) ---
@router.callback_query(F.data == "open_main_menu")
async def open_menu_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    user_id = callback.from_user.id
    
    if user_id in ADMIN_IDS:
        import admin
        await callback.message.edit_text(
            "🛠 **Панель управления Администратора P2P**\n\nВыберите необходимый раздел для модерации платформы:",
            reply_markup=admin.get_admin_keyboard()
        )
    else:
        await callback.message.edit_text("🏠 **Главное меню P2P платформы:**", reply_markup=get_main_keyboard())
# --- РАЗДЕЛ: ПРОСМОТР ЛИЧНОЙ СТАТИСТИКИ И ТИТУЛА ---
@router.callback_query(F.data == "lk_stats")
async def show_statistics(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        query = "SELECT nickname, user_status, rating, deals_count FROM users WHERE tg_id = ?"
        async with db.execute(query, (user_id,)) as cursor:
            user_data = await cursor.fetchone()
            
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
    ])
    
    if user_data:
        nickname, user_status, rating, deals_count = user_data
        status_text = STATUS_NAMES.get(user_status, "🟢 Верифицированный")
        user_title = await get_user_title(deals_count, rating)
        
        text = (
            f"📊 **Ваша статистика в системе:**\n\n"
            f"👤 Никнейм: **{nickname}**\n"
            f"🎖 Текущий Титул: **{user_title}**\n"
            f"💼 Проф-роль: {status_text}\n"
            f"⭐ Средний рейтинг: **{rating:.2f}**\n"
            f"🤝 Успешных сделок: **{deals_count}**\n"
        )
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await callback.message.edit_text("❌ Ошибка: Профиль не найден в базе данных.", reply_markup=kb)
# --- РАЗДЕЛ: ЛИЧНАЯ ИСТОРИЯ СДЕЛОК (БЕЗ ФЛУДА) ---
@router.callback_query(F.data == "lk_history")
async def show_user_history(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id  # Переменная называется user_id!
    
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
        [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
    ])

    if not my_history:
        await callback.message.edit_text("📜 Ваша история сделок пока пуста. Вы еще не совершали обменов.", reply_markup=kb)
        return

    text = "📜 **Ваши последние 5 P2P-сделок:**\n\n"
    for d_id, b_id, status, direction, amount in my_history:
        role = "Покупатель 🟩" if user_id == b_id else "Продавец 🟥"
        
        status_labels = {
            'completed': '✅ Успешно завершена',
            'cancelled': '❌ Отменена / Аннулирована',
            'dispute': '🚨 Диспут (Разбирательство)'
        }
        st_text = status_labels.get(status, status)
        
        dir_labels = {"gram_card": "GRAM ⇄ Карты", "gram_piastrix": "GRAM ⇄ Piastrix", "card_piastrix": "Карты ⇄ Piastrix"}
        dir_text = dir_labels.get(direction, direction)

        text += f"• **Сделка #{d_id}** ({dir_text})\n" \
                f"  └ Объем: `{amount}`\n" \
                f"  └ Ваша роль: {role}\n" \
                f"  └ Статус: {st_text}\n\n"

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

# --- РАЗДЕЛ: НАСТРОЙКА РЕКВИЗИТОВ (СТРОГО НА ОДНОМ ЭКРАНЕ) ---
@router.callback_query(F.data == "lk_requisites")
async def show_requisites_menu(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT card, piastrix, ton FROM requisites WHERE tg_id = ?", (user_id,)) as cursor:
            req = await cursor.fetchone()
            
    card, piastrix, ton = req if req else ("", "", "")
    
    text = (
        f"⚙️ **Ваши сохраненные реквизиты для выплат:**\n\n"
        f"💳 Банковские карты:\n`{card if card else 'не указано'}`\n\n"
        f"📱 Эл. кошелек Piastrix:\n`{piastrix if piastrix else 'не указано'}`\n\n"
        f"💎 Адрес TON (Wallet):\n`{ton if ton else 'не указано'}`\n\n"
        f"Используйте кнопки ниже для быстрого изменения данных:"
    )
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Изменить Карты 💳", callback_data="req_edit_card")],
        [types.InlineKeyboardButton(text="Изменить Piastrix 📱", callback_data="req_edit_piastrix")],
        [types.InlineKeyboardButton(text="Изменить TON 💎", callback_data="req_edit_ton")],
        [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

# --- ХЭНДЛЕРЫ НАЖАТИЯ КНОПОК ИЗМЕНЕНИЯ РЕКВИЗИТОВ ---
@router.callback_query(F.data == "req_edit_card")
async def edit_card_init(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(RequisitesStates.waiting_for_card)
    await callback.message.edit_text("✍️ Введите и отправьте сообщением ваш номер банковской карты / название банка:")

@router.callback_query(F.data == "req_edit_piastrix")
async def edit_piastrix_init(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(RequisitesStates.waiting_for_piastrix)
    await callback.message.edit_text("✍️ Введите и отправьте сообщением ваш кошелек Piastrix (начинается с P...):")

@router.callback_query(F.data == "req_edit_ton")
async def edit_ton_init(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(RequisitesStates.waiting_for_ton)
    await callback.message.edit_text("✍️ Введите и отправьте сообщением ваш анонимный адрес TON:")

# --- ХЭНДЛЕРЫ ПРИЕМА ТЕКСТА И ЗАПИСИ В БАЗУ ДАННЫХ ---

@router.message(StateFilter(RequisitesStates.waiting_for_card), F.text)
async def process_card_saving(message: types.Message, state: FSMContext):
    text = message.text.strip()
    user_id = message.from_user.id
    await state.clear()
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE requisites SET card = ? WHERE tg_id = ?", (text, user_id))
        await db.commit()
        
    try:
        await message.delete()
    except Exception:
        pass
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⚙️ Вернуться в Реквизиты", callback_data="lk_requisites")]])
    await message.answer("✅ **Банковские карты успешно обновлены в базе данных!**", reply_markup=kb, parse_mode="Markdown")


@router.message(StateFilter(RequisitesStates.waiting_for_piastrix), F.text)
async def process_piastrix_saving(message: types.Message, state: FSMContext):
    text = message.text.strip()
    user_id = message.from_user.id
    await state.clear()
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE requisites SET piastrix = ? WHERE tg_id = ?", (text, user_id))
        await db.commit()
        
    try:
        await message.delete()
    except Exception:
        pass
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⚙️ Вернуться в Реквизиты", callback_data="lk_requisites")]])
    await message.answer("✅ **Кошелек Piastrix успешно сохранен в базе данных!**", reply_markup=kb, parse_mode="Markdown")


@router.message(StateFilter(RequisitesStates.waiting_for_ton), F.text)
async def process_ton_saving(message: types.Message, state: FSMContext):
    text = message.text.strip()
    user_id = message.from_user.id
    await state.clear()
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE requisites SET ton = ? WHERE tg_id = ?", (text, user_id))
        await db.commit()
        
    try:
        await message.delete()
    except Exception:
        pass
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⚙️ Вернуться в Реквизиты", callback_data="lk_requisites")]])
    await message.answer("✅ **Адрес TON Wallet успешно привязан к вашему профилю!**", reply_markup=kb, parse_mode="Markdown")


# --- КНОПКА ВОЗВРАТА В АКТИВНУЮ СДЕЛКУ ИЗ ГЛАВНОГО МЕНЮ ---

@router.callback_query(F.data == "lk_active_deals")
async def show_active_deals_from_menu(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.clear()
    tg_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        query = """
            SELECT id, status, buyer_id, seller_id, use_guarantor 
            FROM deals 
            WHERE (buyer_id = ? OR seller_id = ?) 
            AND status IN ('waiting_payment', 'waiting_delivery', 'dispute')
        """
        async with db.execute(query, (tg_id, tg_id)) as cursor:
            active_deal = await cursor.fetchone()

    kb_back = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
    ])

    if not active_deal:
        await callback.message.edit_text("🔄 **У вас нет активных сделок на данный момент.**\nВсе обмены завершены или отменены.", reply_markup=kb_back)
        return
        
        deal_id, status, buyer_id, seller_id, use_guarantor, guarantor_id = active_deal
    kb = None
    
    # ⚡ ИСПРАВЛЕНО: Четко определяем текстовую роль для трех участников
    if tg_id == guarantor_id:
        role_text = "🛡️ Официальный Гарант сделки"
    elif tg_id == buyer_id:
        role_text = "Покупатель 🟩"
    else:
        role_text = "Продавец 🟥"
    
    # --- ВЕТКА А: КНОПКИ ДЛЯ ГАРАНТА КОМЬЮНИТИ ---
    if tg_id == guarantor_id:
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🎉 Закрыть (Выпустить средства)", callback_data=f"deal_action_gcomplete_{deal_id}")],
            [types.InlineKeyboardButton(text="❌ Отменить (Вернуть средства)", callback_data=f"deal_action_gcancel_{deal_id}")],
            [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
        ])
    
    # --- ВЕТКА Б: КНОПКИ ДЛЯ ПОКУПАТЕЛЯ И ПРОДАВЦА ---
    else:
        if status == 'waiting_payment':
            if tg_id == buyer_id:
                # 🛡️ АНТИ-ФРОД: Проверяем, зашел ли Гарант
                if use_guarantor == 1 and (guarantor_id is None or guarantor_id == 0):
                    kb = types.InlineKeyboardMarkup(inline_keyboard=[
                        [types.InlineKeyboardButton(text="⏳ Ожидаем подключение Гаранта...", callback_data="dummy_waiting_g")],
                        [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
                    ])
                else:
                    btn_text = "🟩 Я перевел средства Гаранту" if use_guarantor else "🟩 Я перевел средства"
                    kb = types.InlineKeyboardMarkup(inline_keyboard=[
                        [types.InlineKeyboardButton(text=btn_text, callback_data=f"deal_action_paid_{deal_id}")],
                        [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
                    ])
            elif tg_id == seller_id:
                kb = types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="⏳ Ожидаем оплату от Покупателя", callback_data="dummy_waiting_pay")],
                    [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
                ])
        elif status == 'waiting_delivery':
            if tg_id == seller_id:
                if use_guarantor == 1:
                    kb = types.InlineKeyboardMarkup(inline_keyboard=[
                        [types.InlineKeyboardButton(text="⏳ Ожидайте, Гарант выпускает средства", callback_data="dummy_g_processing")],
                        [types.InlineKeyboardButton(text="🚨 Вызвать Гаранта (Спор)", callback_data=f"deal_action_dispute_{deal_id}")],
                        [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
                    ])
                else:
                    kb = types.InlineKeyboardMarkup(inline_keyboard=[
                        [types.InlineKeyboardButton(text="🎉 Обмен завершен (Средства у меня)", callback_data=f"deal_action_completed_{deal_id}")],
                        [types.InlineKeyboardButton(text="🚨 Вызвать Гаранта (Спор)", callback_data=f"deal_action_dispute_{deal_id}")],
                        [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
                    ])
            elif tg_id == buyer_id:
                kb = types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="⏳ Ожидайте выдачи монет от Продавца", callback_data="dummy_waiting_coins")],
                    [types.InlineKeyboardButton(text="🚨 Вызвать Гаранта (Спор)", callback_data=f"deal_action_dispute_{deal_id}")],
                    [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
                ])
        elif status == 'dispute':
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🚨 Спор модерируется Гарантом", callback_data="dummy_dispute_mode")],
                [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
            ])

    status_labels = {
        'waiting_payment': 'Ожидание оплаты от Покупателя',
        'waiting_delivery': 'Ожидание подтверждения/выдачи',
        'dispute': 'Внештатная ситуация (Открыт спор)'
    }

    await callback.message.edit_text(
        f"🔄 **Вы перешли в вашу активную сделку #{deal_id}!**\n\n"
        f"👤 Ваша роль: **{role_text}**\n"
        f"📊 Текущий статус: _{status_labels.get(status, status)}_\n"
        f"💬 Анонимный чат по-прежнему активен.\n\n"
        f"Используйте кнопки управления ниже для проведения обмена:",
        reply_markup=kb,
        parse_mode="Markdown"
    )
