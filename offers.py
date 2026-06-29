import aiosqlite
from database import DB_NAME, check_offer_limit, has_required_requisites
from aiogram import Router, F, types
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from database import DB_NAME, check_offer_limit

router = Router()

# Состояния FSM для создания заявки
class CreateOfferStates(StatesGroup):
    waiting_for_type = State()    # 'buy' или 'sell'
    waiting_for_amount = State()  # Сумма монет/фиата
    waiting_for_rate = State()    # Курс обмена

# Словарь для красивого отображения направлений
DIRECTION_LABELS = {
    "gram_card": "GRAM ⇄ Карты",
    "gram_piastrix": "GRAM ⇄ Piastrix",
    "card_piastrix": "Карты ⇄ Piastrix"
}

# --- НАВИГАЦИЯ И ВЫБОР ДЕЙСТВИЯ ---
@router.callback_query(F.data.startswith("nav_"))
async def handle_direction_menu(callback: types.CallbackQuery):
    await callback.answer()
    direction = callback.data.replace("nav_", "") # Получаем 'gram_card', etc.
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔍 Посмотреть заявки", callback_data=f"view_choose_{direction}")],
        [types.InlineKeyboardButton(text="➕ Создать заявку", callback_data=f"create_start_{direction}")],
        [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
    ])
    
    await callback.message.answer(
        f"📂 Раздел: **{DIRECTION_LABELS.get(direction, direction)}**\n"
        f"Что вы хотите сделать?",
        reply_markup=kb
    )

# --- БЛОК 1: СОЗДАНИЕ ЗАЯВКИ (С ПРОВЕРКОЙ ЛИМИТОВ) ---
@router.callback_query(F.data.startswith("create_start_"))
async def start_create_offer(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    direction = callback.data.replace("create_start_", "")
    
    # 🛡️ ЗАЩИТА 1: Проверяем, заполнены ли реквизиты для этого направления
    if not await has_required_requisites(user_id, direction):
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="⚙️ Заполнить реквизиты", callback_data="lk_requisites")],
            [types.InlineKeyboardButton(text="⬅ Назад", callback_data=f"nav_{direction}")]
        ])
        await callback.message.answer(
            f"⚠ **Внимание! Реквизиты не заполнены.**\n\n"
            f"Для создания заявки в направлении **{DIRECTION_LABELS.get(direction, direction)}** "
            f"у вас должны быть обязательно сохранены платежные данные в Личном Кабинете.\n"
            f"Пожалуйста, заполните их перед продолжением.",
            reply_markup=kb
        )
        return

    # 🛡️ ЗАЩИТА 2: Проверяем лимит активных заявок пользователя
    if not await check_offer_limit(user_id):
        await callback.message.answer(
            "⚠️ **Превышен лимит заявок!**\n"
            "Вы не можете создать новое объявление, так как достигли максимального лимита "
            "активных заявок для вашего текущего статуса трейдера.\n"
            "Удалите или завершите старые заявки, либо запросите у админа повышение статуса."
        )
        return

    await state.update_data(direction=direction)
    await state.set_state(CreateOfferStates.waiting_for_type)
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Я куплю", callback_data="type_buy"),
         types.InlineKeyboardButton(text="Я продам", callback_data="type_sell")]
    ])
    await callback.message.answer("Выберите тип вашей заявки:", reply_markup=kb)

@router.callback_query(CreateOfferStates.waiting_for_type, F.data.startswith("type_"))
async def process_offer_type(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    offer_type = callback.data.replace("type_", "") # 'buy' или 'sell'
    await state.update_data(offer_type=offer_type)
    
    await state.set_state(CreateOfferStates.waiting_for_amount)
    await callback.message.answer("Введите объем/сумму обмена (например: `100 GRAM` или `50000 RUB`):")

@router.message(CreateOfferStates.waiting_for_amount)
async def process_offer_amount(message: types.Message, state: FSMContext):
    await state.update_data(amount=message.text.strip())
    await state.set_state(CreateOfferStates.waiting_for_rate)
    await message.answer("Укажите желаемый курс или условия обмена текстам (например: `1 GRAM = 4.5 USD`):")

@router.message(CreateOfferStates.waiting_for_rate)
async def process_offer_rate(message: types.Message, state: FSMContext):
    rate = message.text.strip()
    data = await state.get_data()
    await state.clear() # Сбрасываем FSM
    
    creator_id = message.from_user.id
    direction = data["direction"]
    offer_type = data["offer_type"]
    amount = data["amount"]
    
    # Сохраняем новую заявку в базу данных
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO offers (creator_id, direction, offer_type, amount, rate, status) VALUES (?, ?, ?, ?, ?, 'active')",
            (creator_id, direction, offer_type, amount, rate)
        )
        await db.commit()
        
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅ В главное меню", callback_data="open_main_menu")]
    ])
    await message.answer("🎉 **Заявка успешно опубликована в торговом стакане!**", reply_markup=kb)

# --- БЛОК 2: ПРОСМОТР СТАКАНА (С СОРТИРОВКОЙ) ---
@router.callback_query(F.data.startswith("view_choose_"))
async def choose_sorting(callback: types.CallbackQuery):
    await callback.answer()
    direction = callback.data.replace("view_choose_", "")
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⏱ По новизне (Свежие)", callback_data=f"view_list_time_{direction}")],
        [types.InlineKeyboardButton(text="⭐ По рейтингу автора", callback_data=f"view_list_rate_{direction}")],
        [types.InlineKeyboardButton(text="⬅ Назад", callback_data=f"nav_{direction}")]
    ])
    await callback.message.answer("Выберите тип сортировки объявлений:", reply_markup=kb)

@router.callback_query(F.data.startswith("view_list_"))
async def show_offers_list(callback: types.CallbackQuery):
    await callback.answer()
    
    # Разбираем callback_data (формат: view_list_[time/rate]_[direction])
    parts = callback.data.split("_")
    sort_type = parts[2] # 'time' или 'rate'
    direction = f"{parts[3]}_{parts[4]}" # 'gram_card', etc.
    
    # Определяем SQL-сортировку
    order_by = "offers.id DESC" if sort_type == "time" else "users.rating DESC"
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Соединяем таблицы offers и users, чтобы вытащить никнейм и рейтинг создателя
        query = f"""
            SELECT offers.id, offers.offer_type, offers.amount, offers.rate, users.nickname, users.rating, users.user_status, offers.creator_id
            FROM offers 
            JOIN users ON offers.creator_id = users.tg_id
            WHERE offers.direction = ? AND offers.status = 'active'
            ORDER BY {order_by} LIMIT 10
        """
        async with db.execute(query, (direction,)) as cursor:
            offers = await cursor.fetchall()
            
    if not offers:
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="⬅ Назад", callback_data=f"view_choose_{direction}")]
        ])
        await callback.message.answer("📭 В данном направлении пока нет активных заявок.", reply_markup=kb)
        return
        
    await callback.message.answer(f"📋 **Активные заявки ({DIRECTION_LABELS.get(direction)}):**\n" + "—"*15)
    
    # Выводим каждую заявку отдельным сообщением с кнопками принятия сделки
    for offer_id, o_type, amount, rate, nick, rating, status, creator_id in offers:
        type_label = "🟢 КУПИТ" if o_type == "buy" else "🔴 ПРОДАСТ"
        
        # Защита: создатель объявления не должен принимать свою же заявку
        if creator_id == callback.from_user.id:
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="❌ Ваше объявление", callback_data="dummy_own_offer")]
            ])
        else:
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🤝 Принять сделку", callback_data=f"deal_open_direct_{offer_id}")],
                [types.InlineKeyboardButton(text="🛡 С Гарантом", callback_data=f"deal_open_guarantor_{offer_id}")]
            ])
            
        offer_text = (
            f"👤 **Профиль:** {nick} (⭐ {rating:.1f})\n"
            f"📋 **Действие:** {type_label}\n"
            f"💰 **Объем:** `{amount}`\n"
            f"📊 **Курс/Условия:** `{rate}`\n"
            f"ℹ _Реквизиты скрыты и будут выданы после открытия сделки._"
        )
        await callback.message.answer(offer_text, reply_markup=kb, parse_mode="Markdown")
