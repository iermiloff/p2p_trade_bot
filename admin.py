import aiosqlite
from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from config import ADMIN_IDS
from database import DB_NAME
from constants import STATUS_NAMES

router = Router()

def get_admin_keyboard():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📈 Общая статистика", callback_data="admin_stats")],
        [types.InlineKeyboardButton(text="📋 Заявки на верификацию", callback_data="admin_view_kyc")],
        [types.InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_view_users")],
        [types.InlineKeyboardButton(text="🚫 Список забаненных", callback_data="admin_view_banned")]
    ])

@router.message(Command("admin"))
async def cmd_admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("🛠 **Панель управления Администратора P2P**", reply_markup=get_admin_keyboard())

# --- 1. СТАТИСТИКА ---
@router.callback_query(F.data == "admin_stats")
async def admin_show_stats(callback: types.CallbackQuery):
    await callback.answer()
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c: total_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_verified = 1") as c: verified_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM offers WHERE status = 'active'") as c: active_offers = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM deals WHERE status = 'completed'") as c: completed_deals = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM deals WHERE status = 'dispute'") as c: active_disputes = (await c.fetchone())[0]

    text = f"📈 **Общая статистика p2p-платформы:**\n\n👥 Всего: **{total_users}** | Из них верифицировано: **{verified_users}**\n📊 Активных ордеров: **{active_offers}**\n🎉 Успешных обменов: **{completed_deals}**\n🚨 Текущих диспутов: **{active_disputes}**"
    await callback.message.edit_text(text, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]]))

# --- 2. ПРОСМОТР ЗАЯВОК НА ВЕРИФИКАЦИЮ (С ВЫВОДОМ ССЫЛОК И С КНОПКОЙ СКАНИРОВАНИЯ) ---
@router.callback_query(F.data == "admin_view_kyc")
async def admin_view_kyc_list(callback: types.CallbackQuery, bot: Bot):
    await callback.answer()
    async with aiosqlite.connect(DB_NAME) as db:
        # Тянем tg_id, никнейм и kyc_file_id для неверфицированных пользователей
        async with db.execute("SELECT tg_id, nickname, kyc_file_id FROM users WHERE is_verified = 0 LIMIT 5") as cursor:
            unverified = await cursor.fetchall()
            
    if not unverified:
        await callback.message.edit_text("📋 Нет новых заявок на верификацию.", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]]))
        return
        
    await callback.message.edit_text("📋 **Пользователи, ожидающие верификацию:**", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад в админку", callback_data="back_to_admin")]]))
    
    for tg_id, nickname, kyc_file_id in unverified:
        inline_buttons = [
            types.InlineKeyboardButton(text="👍 Одобрить", callback_data=f"verify_approve_{tg_id}"),
            types.InlineKeyboardButton(text="👎 Отклонить", callback_data=f"verify_decline_{tg_id}")
        ]
        
        # Если в базе сохранен файл документа, добавляем кнопку его просмотра для нового админа
        kb_list = [inline_buttons]
        if kyc_file_id:
            kb_list.insert(0, [types.InlineKeyboardButton(text="🖼 Посмотреть документ/скан", callback_data=f"admin_show_doc_{tg_id}")])
            
        kb_manage = types.InlineKeyboardMarkup(inline_keyboard=kb_list)
        
        # Прямая системная ссылка на профиль
        user_link = f"[{nickname}](tg://user?id={tg_id})"
        
        await callback.message.answer(
            f"👤 **Анонимный ник:** {nickname}\n"
            f"🔗 **Реальный профиль:** {user_link}\n"
            f"🆔 Telegram ID: `{tg_id}`",
            reply_markup=kb_manage,
            parse_mode="Markdown"
        )

# Хэндлер показа скана документа из базы данных по запросу админа
@router.callback_query(F.data.startswith("admin_show_doc_"))
async def admin_show_stored_document(callback: types.CallbackQuery, bot: Bot):
    await callback.answer()
    target_id = int(callback.data.replace("admin_show_doc_", ""))
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT kyc_file_id FROM users WHERE tg_id = ?", (target_id,)) as cursor:
            res = await cursor.fetchone()
            
    if res and res[0]:
        await bot.send_photo(
            chat_id=callback.from_user.id, 
            photo=res[0], 
            caption=f"📄 Документ верификации пользователя `{target_id}` поднят из базы данных."
        )
    else:
        await callback.message.answer("⚠️ Документ не найден в базе данных (возможно, пользователь отправил только текст).")
        
# --- 3. СПИСОК ВСЕХ ПОЛЬЗОВАТЕЛЕЙ С РЕАЛЬНЫМИ ССЫЛКАМИ ---
@router.callback_query(F.data == "admin_view_users")
async def admin_view_users_list(callback: types.CallbackQuery):
    await callback.answer()
    async with aiosqlite.connect(DB_NAME) as db:
        # ⚡ ДОБАВИЛИ: вытаскиваем флаг is_verified из базы данных
        async with db.execute("SELECT tg_id, nickname, user_status, rating, deals_count, is_verified FROM users LIMIT 15") as cursor:
            users = await cursor.fetchall()
            
    text = "👥 **Список пользователей системы (до 15 человек):**\n\n"
    for tg_id, nick, status, rating, deals, is_verified in users:
        # Динамически определяем, прошел ли пользователь ручную проверку
        if is_verified == 1:
            kyc_badge = "🟢 Доступ разрешен"
            # Если это админ, у него статус super_trader, иначе подставляем имя статуса
            status_name = STATUS_NAMES.get(status, "🟢 Верифицированный")
        else:
            kyc_badge = "⏳ Ожидает верификацию"
            status_name = "❌ Доступ закрыт"
            
        real_profile_link = f"[{nick}](tg://user?id={tg_id})"
        text += f"• Профиль: {real_profile_link} | ID: `{tg_id}`\n  └ Проверка KYC: **{kyc_badge}**\n  └ Ранг: {status_name} | ⭐ {rating:.1f} | 🤝 Сделок: {deals}\n\n"
        
    await callback.message.edit_text(text, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]]), parse_mode="Markdown")

# --- 4. СПИСОК ЗАБАНЕННЫХ ---
@router.callback_query(F.data == "admin_view_banned")
async def admin_view_banned_list(callback: types.CallbackQuery):
    await callback.answer()
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT tg_id, nickname, is_banned, ban_until FROM users WHERE is_banned = 1 OR ban_until > 0") as cursor:
            banned = await cursor.fetchall()
            
    if not banned:
        await callback.message.edit_text("🚫 Список заблокированных пуст.", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]]))
        return
        
    text = "🚫 **Заблокированные пользователи:**\n\n"
    for tg_id, nick, is_perm, until in banned:
        ban_type = "Вечный бан ⛔" if is_perm == 1 else f"Временный бан до (Unix): `{until}` ⏳"
        real_profile_link = f"[{nick}](tg://user?id={tg_id})"
        text += f"• Профиль: {real_profile_link} (ID: `{tg_id}`)\n  └ Тип: {ban_type}\n  └ Разбанить: `/unban {tg_id}`\n\n"
        
    await callback.message.edit_text(text, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]]), parse_mode="Markdown")

@router.callback_query(F.data == "back_to_admin")
async def back_to_admin_callback(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("🛠 **Панель управления Администратора P2P**\n\nВыберите необходимый раздел для модерации платформы:", reply_markup=get_admin_keyboard())

