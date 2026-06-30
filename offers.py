import aiosqlite
import random
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from config import ADMIN_IDS
from database import DB_NAME, check_offer_limit, has_required_requisites, get_user_title
from constants import STATUS_NAMES, STATUS_LIMITS

router = Router()

# Состояния FSM для пошагового создания торговой заявки
class OfferCreateStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_rate = State()

# --- ВЫБОР ДЕЙСТВИЯ В РАЗДЕЛЕ ОБМЕНА ---
@router.callback_query(F.data.startswith("nav_"))
async def process_navigation(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    direction = callback.data.replace("nav_", "")
    
    dir_titles = {
        "gram_card": "GRAM ⇄ Карты",
        "gram_piastrix": "GRAM ⇄ Piastrix",
        "card_piastrix": "Карты ⇄ Piastrix"
    }
    dir_text = dir_titles.get(direction, direction)
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔍 Посмотреть заявки", callback_data=f"view_sort_{direction}")],
        [types.InlineKeyboardButton(text="➕ Создать заявку", callback_data=f"create_start_{direction}")],
        [types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="open_main_menu")]
    ])
    
    await callback.message.edit_text(
        f"📂 Раздел: **{dir_text}**\nЧто вы хотите сделать?", 
        reply_markup=kb, 
        parse_mode="Markdown"
    )

# --- ВЫБОР ТИПА СОРТИРОВКИ ---
@router.callback_query(F.data.startswith("view_sort_"))
async def process_sorting_menu(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    direction = callback.data.replace("view_sort_", "")
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🕒 По новизне (Свежие)", callback_data=f"view_list_{direction}_id")],
        [types.InlineKeyboardButton(text="⭐ По рейтингу автора", callback_data=f"view_list_{direction}_rating")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"nav_{direction}")]
    ])
    
    await callback.message.edit_text("Выберите тип сортировки объявлений:", reply_markup=kb)

# --- ПОКАЗ ОБЪЯВЛЕНИЙ СТАКАНА ---
@router.callback_query(F.data.startswith("view_list_"))
async def show_offers_list(callback: types.CallbackQuery):
    await callback.answer()
    
    parts = callback.data.split("_")
    direction = f"{parts[2]}_{parts[3]}"
    sort_type = parts[4]
    
    order_by = "offers.id DESC" if sort_type == "id" else "users.rating DESC"
    
    async with aiosqlite.connect(DB_NAME) as db:
        query = f"""
            SELECT offers.id, offers.offer_type, offers.amount, offers.rate, 
                   users.nickname, users.rating, users.user_status, offers.creator_id,
                   users.deals_count
            FROM offers 
            JOIN users ON offers.creator_id = users.tg_id
            WHERE offers.direction = ? AND offers.status = 'active'
            ORDER BY {order_by} LIMIT 1
        """
        async with db.execute(query, (direction,)) as cursor:
            offers = await cursor.fetchall()
            
    kb_back = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад к сортировке", callback_data=f"view_sort_{direction}")]])
    
    if not offers:
        await callback.message.edit_text(f"📭 В данном направлении пока нет активных заявок.", reply_markup=kb_back)
        return
        
    await callback.message.delete()
    
    for offer_id, o_type, amount, rate, nick, rating, status, creator_id, deals_cnt in offers:
        type_label = "🟢 КУПИТ" if o_type == "buy" else "🔴 ПРОДАСТ"
        user_title = await get_user_title(deals_cnt, rating)
        
        if creator_id == callback.from_user.id:
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="❌ Ваше объявление", callback_data="dummy_own_offer")],
                [types.InlineKeyboardButton(text="⬅️ В меню обмена", callback_data=f"nav_{direction}")]
            ])
        else:
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🤝 Принять сделку", callback_data=f"deal_open_direct_{offer_id}")],
                [types.InlineKeyboardButton(text="🛡️ С Гарантом (Комиссия 5%)", callback_data=f"deal_open_guarantor_{offer_id}")],
                [types.InlineKeyboardButton(text="⬅️ В меню обмена", callback_data=f"nav_{direction}")]
            ])
            
        offer_text = (
            f"👤 **Профиль:** {nick} ({user_title})\n"
            f"📊 **Репутация:** ⭐ {rating:.2f} | 🤝 Сделок: {deals_cnt}\n"
            f"📋 **Действие:** {type_label}\n"
            f"💰 **Объем:** `{amount}`\n"
            f"📊 **Курс/Условия:** `{rate}`\n\n"
            f"ℹ️ _Реквизиты будут зафиксированы системой и выданы строго после открытия сделки._"
        )
        await callback.message.answer(offer_text, reply_markup=kb, parse_mode="Markdown")

# --- ➕ ФУНКЦИОНАЛ СОЗДАНИЯ ЗАЯВОК (ВЕРНУЛИ И УЛУЧШИЛИ) ---
@router.callback_query(F.data.startswith("create_start_"))
async def start_create_offer(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    direction = callback.data.replace("create_start_", "")
    
    if user_id in ADMIN_IDS:
        await callback.message.answer(
            "⚠️ **Отказ системы:**\n"
            "Учетным записям администраторов строго запрещено создавать торговые заявки. Вы можете выступать только в роли Гаранта."
        )
        return

    # Извлекаем текущий ранг (user_status) пользователя из базы данных
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_status FROM users WHERE tg_id = ?", (user_id,)) as cursor:
            res = await cursor.fetchone()
            user_status = res[0] if res else "verified"

    # 🎮 ГЕЙМИФИКАЦИЯ: Считаем активные лоты и сопоставляем с увеличенным лимитом текущего ранга!
    current_active_count = await check_offer_limit(user_id)
    max_allowed_limit = STATUS_LIMITS.get(user_status, 1)

    # Жестко блокируем, только если количество реальных активных объявлений достигло или превысило лимит ранга
    if current_active_count >= max_allowed_limit:
        await callback.message.answer(
            f"⚠️ **Превышен лимит объявлений!**\n\n"
            f"Для вашего текущего ранга доступно максимум активных объявлений: **{max_allowed_limit}**.\n"
            f"У вас в стакане уже открыто: **{current_active_count}**.\n\n"
            f"Пожалуйста, дождитесь завершения текущих сделок, либо удалите/закройте ваши старые ордера через меню обмена."
        )
        return

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="🟢 Хочу Купить", callback_data=f"create_type_{direction}_buy"),
            types.InlineKeyboardButton(text="🔴 Хочу Продать", callback_data=f"create_type_{direction}_sell")
        ],
        [types.InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"nav_{direction}")]
    ])
    await callback.message.edit_text("Вы хотите выставить объявление о **Покупке** или **Продаже** актива?", reply_markup=kb, parse_mode="Markdown")

@router.callback_query(F.data.startswith("create_type_"))
async def save_offer_type(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    
    parts = callback.data.split("_")
    direction = f"{parts[2]}_{parts[3]}"
    offer_type = parts[4]
    
    await state.set_state(OfferCreateStates.waiting_for_amount)
    await state.update_data(direction=direction, offer_type=offer_type)
    
    # Отправляем сообщение, так как дальше юзер должен вводить текст в ЛС
    await callback.message.answer(
        "✍️ **Шаг 1 из 2: Укажите объем.**\n"
        "Введите сумму или количество средств для обмена (например: `500 GRAM` или `15 000 RUB`):",
        parse_mode="Markdown"
    )

@router.message(StateFilter(OfferCreateStates.waiting_for_amount), F.text)
async def process_amount_input(message: types.Message, state: FSMContext):
    amount = message.text.strip()
    await state.update_data(amount=amount)
    await state.set_state(OfferCreateStates.waiting_for_rate)
    
    await message.answer(
        "✍️ **Шаг 2 из 2: Укажите условия.**\n"
        "Введите желаемый курс обмена или банки/кошельки, с которыми вы работаете (например: `По курсу 1.2$ / Сбербанк, Тинькофф`):",
        parse_mode="Markdown"
    )

@router.message(StateFilter(OfferCreateStates.waiting_for_rate), F.text)
async def process_rate_and_save_offer(message: types.Message, state: FSMContext):
    rate = message.text.strip()
    data = await state.get_data()
    await state.clear()
    
    user_id = message.from_user.id
    direction = data["direction"]
    offer_type = data["offer_type"]
    amount = data["amount"]
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO offers (creator_id, direction, offer_type, amount, rate) VALUES (?, ?, ?, ?, ?)",
            (user_id, direction, offer_type, amount, rate)
        )
        await db.commit()
        
    type_label = "🟢 КУПЛЮ" if offer_type == "buy" else "🔴 ПРОДАМ"
    
    # Возвращаем пользователя в меню раздела красивой плашкой
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Вернуться в меню обмена", callback_data=f"nav_{direction}")]])
    await message.answer(
        f"🎉 **Ваше P2P-объявление успешно опубликовано в стакане!**\n\n"
        f"📋 Данные заявки:\n"
        f"• Тип: **{type_label}**\n"
        f"• Объем: `{amount}`\n"
        f"• Условия/Курс: `{rate}`\n\n"
        f"Как только контрагент примет ордер, бот моментально пришлет вам уведомление в этот чат.",
        reply_markup=kb,
        parse_mode="Markdown"
    )

