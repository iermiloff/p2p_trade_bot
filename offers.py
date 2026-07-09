import math
import aiosqlite
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter

from database import DB_NAME, check_offer_limit, has_required_requisites
from constants import DIRECTION_TITLES, STATUS_LIMITS

router = Router()

# Состояния FSM для публикации объявлений
class OfferCreateStates(StatesGroup):
    waiting_for_direction = State()
    waiting_for_type = State()
    waiting_for_amount = State()
    waiting_for_rate = State()

def get_offers_navigation_keyboard():
    """Генерирует клавиатуру со всеми 4 новыми направлениями обмена (все к Картам)"""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🤖 Крипта (Bot) ⇄ 💳 Карты", callback_data="nav_dir_crypto_bot")],
        [types.InlineKeyboardButton(text="📈 Крипта (Bybit) ⇄ 💳 Карты", callback_data="nav_dir_bybit")],
        [types.InlineKeyboardButton(text="🌐 Крипта (Другие) ⇄ 💳 Карты", callback_data="nav_dir_other_wallets")],
        [types.InlineKeyboardButton(text="👛 FkWallet ⇄ 💳 Карты", callback_data="nav_dir_fkwallet")],
        [types.InlineKeyboardButton(text="➕ Создать объявление", callback_data="offer_create_start")],
        [types.InlineKeyboardButton(text="⬅ В главное меню", callback_data="open_main_menu")]
    ])

@router.callback_query(F.data == "nav_gram_card")
async def process_p2p_hub(callback: types.CallbackQuery, state: FSMContext):
    """Точка входа в P2P-маркет из главного меню"""
    await callback.answer()
    await state.clear()
    
    await callback.message.edit_text(
        "💱 **P2P Торговая платформа**\n\n"
        "Все сделки на платформе проходят **строго через асинхронного Гаранта** для защиты ваших средств.\n"
        "Выберите интересующее вас направление обмена для просмотра стакана ордеров:",
        reply_markup=get_offers_navigation_keyboard(),
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("nav_dir_"))
async def process_direction_type_choice(callback: types.CallbackQuery):
    """Выбор типа операции внутри выбранного направления: Купить или Продать"""
    await callback.answer()
    direction = callback.data.replace("nav_dir_", "") # Получаем 'bybit', 'crypto_bot' и т.д.
    
    dir_title = DIRECTION_TITLES.get(direction, direction)
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="🟢 Купить (Стакан Sell)", callback_data=f"view_offers_{direction}_sell_1_time"),
            types.InlineKeyboardButton(text="🔴 Продать (Стакан Buy)", callback_data=f"view_offers_{direction}_buy_1_time")
        ],
        [types.InlineKeyboardButton(text="⬅ Назад к направлениям", callback_data="nav_gram_card")]
    ])
    
    await callback.message.edit_text(
        f"Вы выбрали направление: **{dir_title}**\n\n"
        f"• **Купить** — посмотреть объявления людей, которые продают крипту.\n"
        f"• **Продать** — посмотреть объявления людей, которые готовы купить вашу крипту.\n\n"
        f"Выберите тип операции:",
        reply_markup=kb,
        parse_mode="Markdown"
    )
@router.callback_query(F.data.startswith("view_offers_"))
async def display_offers_list(callback: types.CallbackQuery):
    """Вывод списка ордеров с поддержкой динамического парсинга направлений любой длины"""
    await callback.answer()
    
    # Шаблон callback_data: view_offers_[direction]_[offer_type]_[page]_[sort_by]
    parts = callback.data.split("_")
    
    # Забираем параметры строго с конца списка, чтобы исключить баг с составными именами (crypto_bot)
    sort_by = parts[-1]   # 'time' или 'rate' (всегда последний элемент)
    page = int(parts[-2]) # Номер страницы (всегда предпоследний)
    offer_type = parts[-3] # 'buy' или 'sell'
    
    # Собираем название направления из всех оставшихся элементов посередине
    # Отрезаем первые два элемента ('view', 'offers') и последние три (type, page, sort)
    direction = "_".join(parts[2:-3])
    
    limit = 5
    offset = (page - 1) * limit
    
    # Формируем SQL-запрос в зависимости от типа сортировки
    if sort_by == "rate":
        # Сортировка по рейтингу создателя (от большего к меньшему)
        query = """
            SELECT offers.id, offers.creator_id, offers.amount, offers.rate, users.nickname, users.rating, users.deals_count
            FROM offers
            JOIN users ON offers.creator_id = users.tg_id
            WHERE offers.direction = ? AND offers.offer_type = ? AND offers.status = 'active'
            ORDER BY users.rating DESC, offers.id DESC
            LIMIT ? OFFSET ?
        """
    else:
        # Сортировка по новизне (сначала новые лоты)
        query = """
            SELECT offers.id, offers.creator_id, offers.amount, offers.rate, users.nickname, users.rating, users.deals_count
            FROM offers
            JOIN users ON offers.creator_id = users.tg_id
            WHERE offers.direction = ? AND offers.offer_type = ? AND offers.status = 'active'
            ORDER BY offers.id DESC
            LIMIT ? OFFSET ?
        """
        
    async with aiosqlite.connect(DB_NAME) as db:
        # Считаем общее число подходящих активных объявлений для пагинации
        count_query = "SELECT COUNT(*) FROM offers WHERE direction = ? AND offer_type = ? AND status = 'active'"
        async with db.execute(count_query, (direction, offer_type)) as c_cursor:
            total_offers = (await c_cursor.fetchone())[0]
            
        # Загружаем порцию лотов для текущей страницы
        async with db.execute(query, (direction, offer_type, limit, offset)) as cursor:
            offers_list = await cursor.fetchall()
            
    max_pages = math.ceil(total_offers / limit) if total_offers > 0 else 1
    dir_title = DIRECTION_TITLES.get(direction, direction)
    type_title = "Покупка (Вы продаете)" if offer_type == "buy" else "Продажа (Вы покупаете)"
    
    kb_list = []
    
    # Кнопки переключения сортировки в шапке стакана
    time_active = "🔹 " if sort_by == "time" else ""
    rate_active = "🔹 " if sort_by == "rate" else ""
    kb_list.append([
        types.InlineKeyboardButton(text=f"{time_active}Новые", callback_data=f"view_offers_{direction}_{offer_type}_{page}_time"),
        types.InlineKeyboardButton(text=f"{rate_active}По рейтингу", callback_data=f"view_offers_{direction}_{offer_type}_{page}_rate")
    ])
    
    text = f"📊 **Стакан объявлений: {dir_title}**\nРежим: _{type_title}_\nСтраница: `{page}/{max_pages}`\n\n"
    
    if not offers_list:
        text += "📭 В данном разделе пока нет активных объявлений. Вы можете создать своё!"
    else:
        for offer_id, creator_id, amount, rate, nick, rating, deals in offers_list:
            text += f"▪️ **Лот #{offer_id}**\n" \
                    f"  ├ Объем/Сумма: `{amount}`\n" \
                    f"  ├ Курс/Условия: `{rate}`\n" \
                    f"  └ Трейдер: {nick} (⭐{rating:.2f} | ✔️{deals} сделок)\n\n"
            
            # СТРОГО ОДНА КНОПКА: Инициализация безопасного обмена через Гаранта
            kb_list.append([
                types.InlineKeyboardButton(text=f"🤝 Начать обмен по Лоту #{offer_id}", callback_data=f"deal_open_init_{offer_id}")
            ])
            
    # Нижняя навигация (Стрелочки пагинации)
    nav_row = []
    if page > 1:
        nav_row.append(types.InlineKeyboardButton(text="⬅ Назад", callback_data=f"view_offers_{direction}_{offer_type}_{page-1}_{sort_by}"))
    if page < max_pages:
        nav_row.append(types.InlineKeyboardButton(text="Вперед ➡", callback_data=f"view_offers_{direction}_{offer_type}_{page+1}_{sort_by}"))
        
    if nav_row:
        kb_list.append(nav_row)
        
    # Кнопка возврата в меню навигации
    kb_list.append([types.InlineKeyboardButton(text="⬅ Назад к направлениям", callback_data=f"nav_dir_{direction}")])
    
    try:
        await callback.message.edit_text(text, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb_list), parse_mode="Markdown")
    except Exception:
        # Защита от ошибок aiogram, если пользователь нажал на уже выбранный тип сортировки
        pass
@router.callback_query(F.data == "offer_create_start")
async def start_offer_creation(callback: types.CallbackQuery, state: FSMContext):
    """Инициализация создания объявления с проверкой лимитов активности"""
    await callback.answer()
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Проверяем уровень верификации и статус роли пользователя
        async with db.execute("SELECT is_verified, user_status FROM users WHERE tg_id = ?", (user_id,)) as cursor:
            u_data = await cursor.fetchone()
            
    if not u_data:
        await callback.message.edit_text("❌ Ошибка: Ваш профиль не найден.")
        return
        
    is_verified, user_status = u_data
    
    if is_verified != 1:
        kb_kyc = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Пройти верификацию", callback_data="start_verification")]
        ])
        await callback.message.edit_text("🛑 **Доступ ограничен!**\nВы не можете публиковать объявления в стакан, пока не пройдете верификацию у администратора.", reply_markup=kb_kyc, parse_mode="Markdown")
        return
        
    # Проверка лимитов на количество активных объявлений
    current_active_count = await check_offer_limit(user_id)
    max_allowed = STATUS_LIMITS.get(user_status, 1)
    
    if current_active_count >= max_allowed:
        kb_back = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="⬅ Назад в P2P", callback_data="nav_gram_card")]
        ])
        await callback.message.edit_text(
            f"🛑 **Лимит превышен!**\nВаш текущий ранг позволяет иметь не более `{max_allowed}` активных лотов в стакане.\n"
            f"У вас уже открыто: `{current_active_count}` лотов. Удалите старые, чтобы создать новый.",
            reply_markup=kb_back,
            parse_mode="Markdown"
        )
        return

    # Запускаем FSM процесс
    await state.set_state(OfferCreateStates.waiting_for_direction)
    
    kb_dirs = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🤖 Крипта (Bot) ⇄ Карты", callback_data="create_dir_crypto_bot")],
        [types.InlineKeyboardButton(text="📈 Крипта (Bybit) ⇄ Карты", callback_data="create_dir_bybit")],
        [types.InlineKeyboardButton(text="🌐 Крипта (Другие) ⇄ Карты", callback_data="create_dir_other_wallets")],
        [types.InlineKeyboardButton(text="👛 FkWallet ⇄ Карты", callback_data="create_dir_fkwallet")],
        [types.InlineKeyboardButton(text="❌ Отмена", callback_data="nav_gram_card")]
    ])
    
    await callback.message.edit_text("➕ **Создание объявления**\nШаг 1/4: Выберите платежное направление вашего лота:", reply_markup=kb_dirs, parse_mode="Markdown")

@router.callback_query(StateFilter(OfferCreateStates.waiting_for_direction), F.data.startswith("create_dir_"))
async def process_create_direction(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    direction = callback.data.replace("create_dir_", "")
    await state.update_data(direction=direction)
    
    await state.set_state(OfferCreateStates.waiting_for_type)
    
    kb_type = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="🟢 Я ПОКУПАЮ (Buy-лот)", callback_data="create_type_buy"),
            types.InlineKeyboardButton(text="🔴 Я ПРОДАЮ (Sell-лот)", callback_data="create_type_sell")
        ],
        [types.InlineKeyboardButton(text="❌ Отмена", callback_data="nav_gram_card")]
    ])
    
    await callback.message.edit_text(
        "➕ **Создание объявления**\nШаг 2/4: Выберите тип вашего объявления:\n\n"
        "• `Я ПОКУПАЮ` — вы отдаете рубли с карты и хотите получить актив (монеты).\n"
        "• `Я ПРОДАЮ` — вы отдаете актив (монеты) и хотите получить рубли на карту.",
        reply_markup=kb_type,
        parse_mode="Markdown"
    )

@router.callback_query(StateFilter(OfferCreateStates.waiting_for_type), F.data.startswith("create_type_"))
async def process_create_type(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    o_type = callback.data.replace("create_type_", "")
    await state.update_data(offer_type=o_type)
    
    await state.set_state(OfferCreateStates.waiting_for_amount)
    
    kb_cancel = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="❌ Отмена", callback_data="nav_gram_card")]])
    await callback.message.edit_text("➕ **Создание объявления**\nШаг 3/4: Введите в ответном сообщении **Объем / Сумму** сделки (например: `150 USDT` или `10 000 RUB`):", reply_markup=kb_cancel, parse_mode="Markdown")

@router.message(StateFilter(OfferCreateStates.waiting_for_amount), F.text)
async def process_create_amount_text(message: types.Message, state: FSMContext):
    amount_raw = message.text.strip().replace("<", "&lt;").replace(">", "&gt;")
    await state.update_data(amount=amount_raw)
    
    await state.set_state(OfferCreateStates.waiting_for_rate)
    
    kb_cancel = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="❌ Отмена", callback_data="nav_gram_card")]])
    await message.answer("➕ **Создание объявления**\nШаг 4/4: Укажите **Курс или условия** обмена (например: `По курсу СБЕР +2%` или `1 USDT = 94.5 RUB`):", reply_markup=kb_cancel, parse_mode="Markdown")

@router.message(StateFilter(OfferCreateStates.waiting_for_rate), F.text)
async def process_create_final_saving(message: types.Message, state: FSMContext):
    rate_raw = message.text.strip().replace("<", "&lt;").replace(">", "&gt;")
    user_id = message.from_user.id
    
    data = await state.get_data()
    await state.clear()
    
    direction = data["direction"]
    offer_type = data["offer_type"]
    amount = data["amount"]
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO offers (creator_id, direction, offer_type, amount, rate, status) VALUES (?, ?, ?, ?, ?, 'active')",
            (user_id, direction, offer_type, amount, rate_raw)
        )
        await db.commit()
        
    kb_done = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔄 Открыть P2P Маркет", callback_data="nav_gram_card")]
    ])
    await message.answer("🎉 **Объявление успешно опубликовано!**\nВаш лот добавлен в торговый стакан платформы и доступен другим трейдерам.", reply_markup=kb_done, parse_mode="Markdown")
