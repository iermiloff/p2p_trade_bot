import aiosqlite
from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from config import ADMIN_IDS
from database import DB_NAME
from constants import STATUS_NAMES
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

class AdminManageStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_ban_time = State()

router = Router()

def get_admin_keyboard():
    """Клавиатура главного меню админ-панели"""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📈 Общая статистика", callback_data="admin_stats")],
        [types.InlineKeyboardButton(text="📋 Заявки на верификацию", callback_data="admin_view_kyc")],
        [types.InlineKeyboardButton(text="⚙️ Управление пользователем", callback_data="admin_manage_user_start")],
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

# --- МОДУЛЬ РУЧНОГО УПРАВЛЕНИЯ ПОЛЬЗОВАТЕЛЯМИ (БЕЗ ТЕКСТОВЫХ КОМАНД) ---

# 1. Старт процесса: запрашиваем ID
@router.callback_query(F.data == "admin_manage_user_start")
async def admin_manage_user_init(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminManageStates.waiting_for_user_id)
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Отмена", callback_data="back_to_admin")]])
    await callback.message.edit_text(
        "⚙️ **Управление пользователем**\n\n"
        "Пришлите в ответном сообщении численный **Telegram ID** пользователя, которого вы хотите забанить, разбанить или изменить ему ранг:",
        reply_markup=kb
    )

# 2. Ловим введенный ID и выводим пульт модератора
@router.message(StateFilter(AdminManageStates.waiting_for_user_id), F.text)
async def admin_render_user_control_panel(message: types.Message, state: FSMContext):
    user_text = message.text.strip()
    
    if not user_text.isdigit():
        await message.answer("⚠️ Ошибка: ID должен состоять только из цифр. Попробуйте еще раз:")
        return
        
    target_id = int(user_text)
    await state.clear() # Очищаем стейт, так как ID получен
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT nickname, user_status, rating, deals_count, is_banned, ban_until FROM users WHERE tg_id = ?", (target_id,)) as cursor:
            user_data = await cursor.fetchone()
            
    if not user_data:
        await message.answer("❌ Пользователь с таким ID не найден в базе данных бота. Проверьте цифры.")
        return
        
    nick, status, rating, deals, is_banned, ban_until = user_data
    status_text = STATUS_NAMES.get(status, status)
    
    # Формируем статус блокировки
    if is_banned == 1: ban_status = "⛔ Вечный бан"
    elif ban_until > int(time.time()): ban_status = f"⏳ Временный бан до {time.strftime('%d.%m %H:%M', time.localtime(ban_until))}"
    else: ban_status = "🟢 Чист / Активен"
    
    # Пульт управления кнопками
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="⛔ Пермбан", callback_data=f"usrmng_permban_{target_id}"),
            types.InlineKeyboardButton(text="⏳ Темпбан", callback_data=f"usrmng_tempban_{target_id}"),
            types.InlineKeyboardButton(text="✅ Разбанить", callback_data=f"usrmng_unban_{target_id}")
        ],
        [types.InlineKeyboardButton(text="🎖 Изменить Ранг / Роль", callback_data=f"usrmng_setrole_{target_id}")],
        [types.InlineKeyboardButton(text="⬅️ В главное меню админки", callback_data="back_to_admin")]
    ])
    
    real_profile_link = f"[{nick}](tg://user?id={target_id})"
    await message.answer(
        f"👤 **КАРТОЧКА МОДЕРАЦИИ ПОЛЬЗОВАТЕЛЯ:**\n\n"
        f"• Профиль: {real_profile_link}\n"
        f"• ID: `{target_id}`\n"
        f"• Текущий ранг: **{status_text}**\n"
        f"• Репутация: ⭐ {rating:.1f} | 🤝 Сделок: {deals}\n"
        f"• Статус ограничений: **{ban_status}**\n\n"
        f"Выберите необходимое действие на панели ниже:",
        reply_markup=kb,
        parse_mode="Markdown"
    )

# 3. Обработка кнопок Блокировок
@router.callback_query(F.data.startswith("usrmng_"))
async def admin_process_user_moderation_buttons(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    parts = callback.data.split("_")
    action = parts[1] # 'permban', 'tempban', 'unban', 'setrole', 'saverole'
    target_id = int(parts[2])
    
    async with aiosqlite.connect(DB_NAME) as db:
        # А: Вечный бан
        if action == "permban":
            await db.execute("UPDATE users SET is_banned = 1 WHERE tg_id = ?", (target_id,))
            await db.commit()
            await callback.message.answer(f"⛔ Пользователь `{target_id}` заблокирован НАВСЕГДА.")
            
        # Б: Снятие всех банов
        elif action == "unban":
            await db.execute("UPDATE users SET is_banned = 0, ban_until = 0 WHERE tg_id = ?", (target_id,))
            await db.commit()
            await callback.message.answer(f"✅ Все ограничения с пользователя `{target_id}` полностью сняты.")
            
        # В: Временный бан (запрашиваем время)
        elif action == "tempban":
            await state.set_state(AdminManageStates.waiting_for_ban_time)
            await state.update_data(target_id=target_id)
            await callback.message.answer("⏳ **Ввод времени бана:**\nПришлите количество минут, на которое нужно заблокировать пользователя:")
            return
            
        # Г: Вызов меню смены ролей
        elif action == "setrole":
            kb_roles = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🟢 Верифицированный", callback_data=f"usrmng_saverole_{target_id}_verified")],
                [types.InlineKeyboardButton(text="🔥 Трейдер", callback_data=f"usrmng_saverole_{target_id}_trader")],
                [types.InlineKeyboardButton(text="⚡ Супер-трейдер", callback_data=f"usrmng_saverole_{target_id}_super_trader")],
                [types.InlineKeyboardButton(text="🛡️ Гарант Комьюнити", callback_data=f"usrmng_saverole_{target_id}_guarantor_member")],
                [types.InlineKeyboardButton(text="⬅ Назад", callback_data="back_to_admin")]
            ])
            await callback.message.edit_text("🎖 **Выбор нового ранга для пользователя:**", reply_markup=kb_roles)
            return
            
        # Д: Сохранение нового ранга
        elif action == "saverole":
            new_role = parts[3]
            await db.execute("UPDATE users SET user_status = ? WHERE tg_id = ?", (new_role, target_id))
            await db.commit()
            
            role_title = STATUS_NAMES.get(new_role, new_role)
            await callback.message.edit_text(f"🎉 Ранг пользователя `{target_id}` успешно изменен на: **{role_title}**.")
            
            # Оповещаем пользователя, если он не забанен
            try:
                await bot.send_message(chat_id=target_id, text=f"🔔 Администратор обновил ваш статус на платформе!\nВаш новый ранг: **{role_title}**.")
            except Exception: pass

# 4. Ловим ввод минут для темпбана
@router.message(StateFilter(AdminManageStates.waiting_for_ban_time), F.text)
async def admin_save_tempban_time(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("⚠️ Ошибка: Введите число минут цифрами:")
        return
        
    minutes = int(text)
    data = await state.get_data()
    target_id = data["target_id"]
    await state.clear()
    
    ban_timestamp = int(time.time()) + (minutes * 60)
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET ban_until = ? WHERE tg_id = ?", (ban_timestamp, target_id))
        await db.commit()
        
    await message.answer(f"⏳ Пользователь `{target_id}` успешно заблокирован на **{minutes}** минут.")
