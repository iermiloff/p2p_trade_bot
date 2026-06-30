import aiosqlite
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from config import ADMIN_IDS
from database import DB_NAME, check_offer_limit, has_required_requisites, get_user_title
from constants import STATUS_NAMES

router = Router()

# --- ВЫБОР ДЕЙСТВИЯ В РАЗДЕЛЕ ОБМЕНА ---
@router.callback_query(F.data.startswith("nav_"))
async def process_navigation(callback: types.CallbackQuery):
    await callback.answer()
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
    
    # СТРОГО РЕДАКТИРУЕМ ТЕКУЩЕЕ СООБЩЕНИЕ
    await callback.message.edit_text(
        f"📂 Раздел: **{dir_text}**\nЧто вы хотите сделать?", 
        reply_markup=kb, 
        parse_mode="Markdown"
    )


# --- ВЫБОР ТИПА СОРТИРОВКИ ---
@router.callback_query(F.data.startswith("view_sort_"))
async def process_sorting_menu(callback: types.CallbackQuery):
    await callback.answer()
    direction = callback.data.replace("view_sort_", "")
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🕒 По новизне (Свежие)", callback_data=f"view_list_{direction}_id")],
        [types.InlineKeyboardButton(text="⭐ По рейтингу автора", callback_data=f"view_list_{direction}_rating")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"nav_{direction}")]
    ])
    
    # СТРОГО РЕДАКТИРУЕМ, ИСКЛЮЧАЯ ДУБЛИКАЦИЮ ПЛАШЕК
    await callback.message.edit_text("Выберите тип сортировки объявлений:", reply_markup=kb)


# --- ПОКАЗ ОБЪЯВЛЕНИЙ СТАКАНА ---
@router.callback_query(F.data.startswith("view_list_"))
async def show_offers_list(callback: types.CallbackQuery):
    await callback.answer()
    
    # Парсим callback_data (формат: view_list_[direction]_[sort_type])
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
        # Редактируем старое сообщение, а не шлем новую плашку
        await callback.message.edit_text(f"📭 В данном направлении пока нет активных заявок.", reply_markup=kb_back)
        return
        
    # Сносим старое меню выбора сортировки перед выводом первой карточки
    await callback.message.delete()
    
    # Выводим заявку (здесь message.answer нужен, так как ордера — это новые объекты с кнопками действий)
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

