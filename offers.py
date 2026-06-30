import aiosqlite
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from config import ADMIN_IDS
from database import DB_NAME, get_user_title
from constants import STATUS_NAMES, STATUS_LIMITS

router = Router()

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
        [types.InlineKeyboardButton(text="🕒 По новизне (Свежие)", callback_data=f"view_page_{direction}_id_0")],
        [types.InlineKeyboardButton(text="⭐ По рейтингу автора", callback_data=f"view_page_{direction}_rating_0")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"nav_{direction}")]
    ])
    
    await callback.message.edit_text("Выберите тип сортировки объявлений в стакане:", reply_markup=kb)

# --- ➕ НАЧАЛО СОЗДАНИЯ ЗАЯВКИ (СТРОГИЙ КОНТРОЛЬ ЛИМИТОВ ВЕРИФИКАЦИИ) ---
@router.callback_query(F.data.startswith("create_start_"))
async def start_create_offer(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    direction = callback.data.replace("create_start_", "")
    
    if user_id in ADMIN_IDS:
        await callback.message.answer("⚠️ Администраторам запрещено создавать торговые заявки.")
        return

    # Запрашиваем из базы данных статус верификации пользователя
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_status FROM users WHERE tg_id = ?", (user_id,)) as cursor:
            res = await cursor.fetchone()
            user_status = res[0] if res else "verified"

        # ⚡ ИСПРАВЛЕНО: Извлекаем чистое число активных объявлений (разворачиваем кортеж)
        async with db.execute("SELECT COUNT(*) FROM offers WHERE creator_id = ? AND status = 'active'", (user_id,)) as cursor:
            count_res = await cursor.fetchone()
            current_active_count = count_res[0] if count_res else 0

    # Получаем лимит для статуса верификации из констант (обычная=1, продвинутая=3, супер=5, VIP=10)
    max_allowed_limit = STATUS_LIMITS.get(user_status, 1)

    if current_active_count >= max_allowed_limit:
        await callback.message.answer(
            f"⚠️ **Превышен лимит объявлений!**\n\n"
            f"Для вашего уровня верификации доступно максимум активных объявлений: **{max_allowed_limit}**.\n"
            f"У вас в стакане уже открыто: **{current_active_count}**.\n\n"
            f"Дождитесь завершения сделок или закройте старые ордера."
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
# --- 🔍 ИНТЕРАКТИВНЫЙ СТАКАН ОРДЕРОВ С ПАГИНАЦИЕЙ ПО 5 ШТУК ---
@router.callback_query(F.data.startswith("view_page_"))
async def show_offers_page(callback: types.CallbackQuery):
    await callback.answer()
    
    # Структура callback_data: view_page_[direction]_[sort_type]_[page]
    parts = callback.data.split("_")
    page = int(parts[-1])
    sort_type = parts[-2]
    direction = f"{parts[-4]}_{parts[-3]}"
    
    # Вычисляем сисадминский отступ для постраничной пагинации SQL
    limit = 5
    offset = page * limit
    
    # Жесткие и статичные запросы для 100% защиты от SQL-инъекций
    if sort_type == "id":
        query = f"""
            SELECT offers.id, offers.offer_type, offers.amount, offers.rate, 
                   users.nickname, users.rating, users.deals_count
            FROM offers 
            JOIN users ON offers.creator_id = users.tg_id
            WHERE offers.direction = ? AND offers.status = 'active'
            ORDER BY offers.id DESC LIMIT {limit} OFFSET {offset}
        """
    else:
        query = f"""
            SELECT offers.id, offers.offer_type, offers.amount, offers.rate, 
                   users.nickname, users.rating, users.deals_count
            FROM offers 
            JOIN users ON offers.creator_id = users.tg_id
            WHERE offers.direction = ? AND offers.status = 'active'
            ORDER BY users.rating DESC, offers.id DESC LIMIT {limit} OFFSET {offset}
        """
        
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(query, (direction,)) as cursor:
            offers = await cursor.fetchall()
            
        # Проверяем, есть ли ордера на СЛЕДУЮЩЕЙ странице для отрисовки кнопки "Вперед"
        async with db.execute(
            "SELECT COUNT(*) FROM offers WHERE direction = ? AND status = 'active'", (direction,)
        ) as cursor:
            total_res = await cursor.fetchone()
            total_count = total_res[0] if total_res else 0

    kb_back = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅️ Назад к сортировке", callback_data=f"view_sort_{direction}")]
    ])
    
    if not offers and page == 0:
        await callback.message.edit_text("📭 В данном направлении пока нет активных заявок.", reply_markup=kb_back)
        return
        
    dir_labels = {"gram_card": "GRAM ⇄ Карты", "gram_piastrix": "GRAM ⇄ Piastrix", "card_piastrix": "Карты ⇄ Piastrix"}
    sort_labels = {"id": "🕒 По новизне", "rating": "⭐ По рейтингу автора"}
    
    text = (
        f"📊 **Торговый стакан ордеров ({dir_labels.get(direction, direction)})**\n"
        f"🔍 Сортировка: _{sort_labels.get(sort_type, sort_type)}_\n"
        f"📄 Страница: **{page + 1}** (Всего активных лотов: {total_count})\n"
        f"────────────────────\n\n"
    )
    
    # Собираем пачку инлайн-кнопок действий для каждого выведенного ордера
    inline_keyboard = []
    
    for offer_id, o_type, amount, rate, nick, rating, deals_cnt in offers:
        type_emoji = "🟢" if o_type == "buy" else "🔴"
        type_text = "КУПИТ" if o_type == "buy" else "ПРОДАСТ"
        user_title = await get_user_title(deals_cnt, rating)
        
        text += (
            f"🆔 **Ордер #{offer_id}** | {type_emoji} **{type_text}**\n"
            f"👤 Автор: {nick} ({user_title})\n"
            f"📊 Репутация: ⭐ {rating:.2f} | 🤝 Сделок: {deals_cnt}\n"
            f"💰 Объем: `{amount}`\n"
            f"📈 Курс/Условия: `{rate}`\n"
            f"────────────────────\n\n"
        )
        # Кнопка быстрого открытия сделки прямо по ID ордера
        inline_keyboard.append([
            types.InlineKeyboardButton(text=f"🤝 Начать обмен #{offer_id}", callback_data=f"deal_open_direct_{offer_id}"),
            types.InlineKeyboardButton(text=f"🛡️ С Гарантом #{offer_id}", callback_data=f"deal_open_guarantor_{offer_id}")
        ])
        
    # Формируем стрелочки постраничного листания ордеров (Вперед / Назад)
    nav_row = []
    if page > 0:
        nav_row.append(types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_page_{direction}_{sort_type}_{page - 1}"))
    if total_count > (offset + limit):
        nav_row.append(types.InlineKeyboardButton(text="Вперед ➡️", callback_data=f"view_page_{direction}_{sort_type}_{page + 1}"))
        
    if nav_row:
        inline_keyboard.append(nav_row)
        
    # Добавляем системную кнопку возврата
    inline_keyboard.append([types.InlineKeyboardButton(text="⬅️ Назад к сортировке", callback_data=f"view_sort_{direction}")])
    
    kb_pagination = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    
    # Выводим стакан строго РЕДАКТИРОВАНИЕМ сообщения — бесшовно и без флуда
    await callback.message.edit_text(text, reply_markup=kb_pagination, parse_mode="Markdown")


# --- ➕ СОХРАНЕНИЕ ДАННЫХ И ШАГИ СОЗДАНИЯ ЗАЯВОК ПОЛЬЗОВАТЕЛЯМИ ---

@router.callback_query(F.data.startswith("create_type_"))
async def save_offer_type(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    
    parts = callback.data.split("_")
    direction = f"{parts[-3]}_{parts[-2]}"
    offer_type = parts[-1]
    
    await state.set_state(OfferCreateStates.waiting_for_amount)
    await state.update_data(direction=direction, offer_type=offer_type)
    
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

