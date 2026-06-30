import aiosqlite
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from config import ADMIN_IDS
from database import DB_NAME, get_user_title
from constants import STATUS_NAMES

router = Router()

def get_main_keyboard():
    """Генерация кнопок Главного меню P2P-платформы"""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⚙️ Мои Реквизиты", callback_data="lk_requisites")],
        [
            types.InlineKeyboardButton(text="📊 Моя Статистика", callback_data="lk_stats"),
            types.InlineKeyboardButton(text="📜 Моя История", callback_data="lk_history")
        ],
        [types.InlineKeyboardButton(text="🔄 GRAM ⇄ Карты", callback_data="nav_gram_card")],
        [types.InlineKeyboardButton(text="🔄 GRAM ⇄ Piastrix", callback_data="nav_gram_piastrix")],
        [types.InlineKeyboardButton(text="🔄 Карты ⇄ Piastrix", callback_data="nav_card_piastrix")]
    ])

# --- ВОЗВРАТ В ГЛАВНОЕ МЕНЮ (СТРОГО РЕДАКТИРОВАНИЕМ) ---
@router.callback_query(F.data == "open_main_menu")
async def open_menu_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    user_id = callback.from_user.id
    
    # Защита: Если кнопку нажал админ, возвращаем его в админку
    if user_id in ADMIN_IDS:
        import admin
        await callback.message.edit_text(
            "🛠 **Панель управления Администратора P2P**\n\nВыберите необходимый раздел для модерации платформы:",
            reply_markup=admin.get_admin_keyboard()
        )
    else:
        # Обычный пользователь возвращается к торговым разделам без нового сообщения
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
        [types.InlineKeyboardButton(text="⬅ Назад в меню", callback_data="open_main_menu")]
    ])

    if not my_history:
        await callback.message.edit_text("📜 Ваша история сделок пока пуста. Вы еще не совершали обменов.", reply_markup=kb)
        return

    text = "📜 **Вашие последние 5 P2P-сделок:**\n\n"
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
