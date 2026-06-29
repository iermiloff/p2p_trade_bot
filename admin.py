import aiosqlite
from aiogram import Router, F, types, Bot  
from aiogram.filters import Command
from config import ADMIN_IDS
from database import DB_NAME
from constants import STATUS_NAMES

router = Router()

def get_admin_keyboard():
    """Клавиатура главного меню админ-панели"""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📈 Общая статистика", callback_data="admin_stats")],
        [types.InlineKeyboardButton(text="📋 Заявки на верификацию", callback_data="admin_view_kyc")],
        [types.InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_view_users")],
        [types.InlineKeyboardButton(text="🚫 Список забаненных", callback_data="admin_view_banned")]
    ])

@router.message(Command("admin"))
async def cmd_admin_panel(message: types.Message):
    """Вход в админку по прямой команде /admin"""
    if message.from_user.id not in ADMIN_IDS:
        return
        
    await message.answer(
        "🛠 **Панель управления Администратора P2P**\n\n"
        "Выберите необходимый раздел для модерации платформы:",
        reply_markup=get_admin_keyboard()
    )

# --- 1. ОБЩАЯ СТАТИСТИКА ПЛАТФОРМЫ ---
@router.callback_query(F.data == "admin_stats")
async def admin_show_stats(callback: types.CallbackQuery):
    await callback.answer()
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            res = await c.fetchone()
            total_users = res[0] if res else 0
            
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_verified = 1") as c:
            res = await c.fetchone()
            verified_users = res[0] if res else 0
            
        async with db.execute("SELECT COUNT(*) FROM offers WHERE status = 'active'") as c:
            res = await c.fetchone()
            active_offers = res[0] if res else 0
            
        async with db.execute("SELECT COUNT(*) FROM deals WHERE status = 'completed'") as c:
            res = await c.fetchone()
            completed_deals = res[0] if res else 0
            
        async with db.execute("SELECT COUNT(*) FROM deals WHERE status = 'dispute'") as c:
            res = await c.fetchone()
            active_disputes = res[0] if res else 0

    text = (
        f"📈 **Общая статистика p2p-платформы:**\n\n"
        f"👥 Всего пользователей: **{total_users}**\n"
        f"✅ Из них верифицировано: **{verified_users}**\n\n"
        f"📊 Активных объявлений в стакане: **{active_offers}**\n"
        f"🎉 Завершено p2p-обменов: **{completed_deals}**\n"
        f"🚨 Текущих активных споров (диспутов): **{active_disputes}**\n"
    )
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅️ Назад в админку", callback_data="back_to_admin")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)

# --- 2. ПРОСМОТР ЗАЯВОК НА ВЕРИФИКАЦИЮ (С КНОПКАМИ УПРАВЛЕНИЯ) ---
@router.callback_query(F.data == "admin_view_kyc")
async def admin_view_kyc_list(callback: types.CallbackQuery, bot: Bot):
    await callback.answer()
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Находим пользователей, у которых is_verified = 0 (ждут проверку)
        async with db.execute("SELECT tg_id, nickname FROM users WHERE is_verified = 0 LIMIT 5") as cursor:
            unverified = await cursor.fetchall()
            
    if not unverified:
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]
        ])
        await callback.message.edit_text("📋 Нет новых необработанных заявок на верификацию.", reply_markup=kb)
        return
        
    # Сначала пишем заголовок, заменяя текст текущего сообщения
    kb_back = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅️ Назад в админку", callback_data="back_to_admin")]
    ])
    await callback.message.edit_text("📋 **Пользователи, ожидающие верификацию:**\n(Вы можете подтвердить их прямо отсюда)", reply_markup=kb_back)
    
    # Выводим каждого пользователя ОТДЕЛЬНЫМ сообщением с его личными кнопками одобрения!
    # Мы используем те же callback_data, что и в модуле верификации (verify_approve_ / verify_decline_)
    for tg_id, nickname in unverified:
        kb_manage = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="👍 Одобрить", callback_data=f"verify_approve_{tg_id}"),
                types.InlineKeyboardButton(text="👎 Отклонить", callback_data=f"verify_decline_{tg_id}")
            ]
        ])
        
        await callback.message.answer(
            f"👤 **Пользователь:** {nickname}\n"
            f"🆔 Telegram ID: `{tg_id}`",
            reply_markup=kb_manage,
            parse_mode="Markdown"
        )

# --- 3. СПИСОК ВСЕХ ПОЛЬЗОВАТЕЛЕЙ ПЛАТФОРМЫ ---
@router.callback_query(F.data == "admin_view_users")
async def admin_view_users_list(callback: types.CallbackQuery):
    await callback.answer()
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT tg_id, nickname, user_status, rating, deals_count FROM users LIMIT 15") as cursor:
            users = await cursor.fetchall()
            
    text = "👥 **Список пользователей системы (до 15 человек):**\n\n"
    for tg_id, nick, status, rating, deals in users:
        status_name = STATUS_NAMES.get(status, status)
        text += f"• **{nick}** | ID: `{tg_id}`\n  └ Статус: {status_name} | ⭐ {rating:.1f} | 🤝 Сделок: {deals}\n\n"
        
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

# --- 4. СПИСОК ЗАБАНЕННЫХ ПОЛЬЗОВАТЕЛЕЙ ---
@router.callback_query(F.data == "admin_view_banned")
async def admin_view_banned_list(callback: types.CallbackQuery):
    await callback.answer()
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT tg_id, nickname, is_banned, ban_until FROM users WHERE is_banned = 1 OR ban_until > 0") as cursor:
            banned = await cursor.fetchall()
            
    if not banned:
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]
        ])
        await callback.message.edit_text("🚫 Список заблокированных пользователей пуст.", reply_markup=kb)
        return
        
    text = "🚫 **Заблокированные пользователи:**\n\n"
    for tg_id, nick, is_perm, until in banned:
        ban_type = "Вечный бан ⛔" if is_perm == 1 else f"Временный бан до (Unix): `{until}` ⏳"
        text += f"• **{nick}** (ID: `{tg_id}`)\n  └ Тип: {ban_type}\n  └ Разбанить: `/unban {tg_id}`\n\n"
        
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

# --- ВОЗВРАТ В КОРЕНЬ АДМИНКИ ---
@router.callback_query(F.data == "back_to_admin")
async def back_to_admin_callback(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "🛠 **Панель управления Администратора P2P**\n\n"
        "Выберите необходимый раздел для модерации платформы:",
        reply_markup=get_admin_keyboard()
    )
