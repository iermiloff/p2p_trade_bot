import aiosqlite
import time
from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from config import ADMIN_IDS
from database import DB_NAME
from constants import STATUS_NAMES

router = Router()

# Состояния машины состояний для модерации
class AdminManageStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_ban_time = State()

def get_admin_keyboard():
    """Главная клавиатура админ-панели"""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📈 Общая статистика", callback_data="admin_stats")],
        [types.InlineKeyboardButton(text="📋 Заявки на верификацию", callback_data="admin_view_kyc")],
        [types.InlineKeyboardButton(text="⚙️ Управление по ID", callback_data="admin_manage_user_start")],
        [types.InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_view_users")],
        [types.InlineKeyboardButton(text="🚫 Список забаненных", callback_data="admin_view_banned")]
    ])

@router.message(Command("admin"), F.chat.type == "private")
async def cmd_admin_panel(message: types.Message, state: FSMContext):
    """Вход в админку по команде /admin с авто-очисткой зависших стейтов"""
    await state.clear()
    await message.answer("🛠 **Панель управления Администратора P2P**", reply_markup=get_admin_keyboard())

@router.callback_query(F.data == "back_to_admin")
async def back_to_admin_callback(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в корень админки с авто-очисткой стейтов"""
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        "🛠 **Панель управления Администратора P2P**\n\nВыберите необходимый раздел для модерации платформы:", 
        reply_markup=get_admin_keyboard()
    )
# --- 1. ОБЩАЯ СТАТИСТИКА ПЛАТФОРМЫ ---
@router.callback_query(F.data == "admin_stats")
async def admin_show_stats(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()  # Сбрасываем стейты, если админ ушел из режима ввода ID
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c: total_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_verified = 1") as c: verified_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM offers WHERE status = 'active'") as c: active_offers = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM deals WHERE status = 'completed'") as c: completed_deals = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM deals WHERE status = 'dispute'") as c: active_disputes = (await c.fetchone())[0]

    text = (
        f"📈 **Общая статистика p2p-платформы:**\n\n"
        f"👥 Всего пользователей: **{total_users}**\n"
        f"✅ Верифицировано: **{verified_users}**\n"
        f"📊 Активных ордеров: **{active_offers}**\n"
        f"🎉 Успешных обменов: **{completed_deals}**\n"
        f"🚨 Текущих диспутов: **{active_disputes}**"
    )
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]])
    await callback.message.edit_text(text, reply_markup=kb)


# --- 2. ПРОСМОТР ЗАЯВОК НА ВЕРИФИКАЦИЮ (С СЫЛКАМИ И АВТОНОМНЫМ ПРОСМОТРОМ) ---
@router.callback_query(F.data == "admin_view_kyc")
async def admin_view_kyc_list(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    await callback.answer()
    await state.clear()
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT tg_id, nickname, kyc_file_id FROM users WHERE is_verified = 0 LIMIT 5") as cursor:
            unverified = await cursor.fetchall()
            
    if not unverified:
        kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]])
        await callback.message.edit_text("📋 Нет новых заявок на верификацию.", reply_markup=kb)
        return
        
    await callback.message.edit_text(
        "📋 **Пользователи, ожидающие верификацию:**", 
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад в админку", callback_data="back_to_admin")]])
    )
    
    for tg_id, nickname, kyc_file_id in unverified:
        inline_buttons = [
            types.InlineKeyboardButton(text="👍 Одобрить", callback_data=f"verify_approve_{tg_id}"),
            types.InlineKeyboardButton(text="👎 Отклонить", callback_data=f"verify_decline_{tg_id}")
        ]
        kb_list = [inline_buttons]
        
        # Если в базе сохранен файл документа, добавляем кнопку его просмотра для нового админа
        if kyc_file_id:
            kb_list.insert(0, [types.InlineKeyboardButton(text="🖼 Посмотреть документ/скан", callback_data=f"admin_show_doc_{tg_id}")])
            
        kb_manage = types.InlineKeyboardMarkup(inline_keyboard=kb_list)
        user_link = f"[{nickname}](tg://user?id={tg_id})"
        await callback.message.answer(
            f"👤 **Анонимный ник:** {nickname}\n"
            f"🔗 **Реальный профиль:** {user_link}\n"
            f"🆔 Telegram ID: `{tg_id}`", 
            reply_markup=kb_manage, 
            parse_mode="Markdown"
        )

# Хэндлер показа скана документа из базы данных по запросу любого админа
@router.callback_query(F.data.startswith("admin_show_doc_"))
async def admin_show_stored_document(callback: types.CallbackQuery, bot: Bot):
    await callback.answer()
    target_id = int(callback.data.replace("admin_show_doc_", ""))
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT kyc_file_id FROM users WHERE tg_id = ?", (target_id,)) as cursor:
            res = await cursor.fetchone()
    if res and res[0]:
        await bot.send_photo(chat_id=callback.from_user.id, photo=res[0], caption=f"📄 Документ верификации пользователя `{target_id}` поднят из БД.")
    else:
        await callback.message.answer("⚠️ Документ не найден в базе данных.")

# --- 3. ПОСТРАНИЧНЫЙ СПИСОК ПОЛЬЗОВАТЕЛЕЙ (ПАГИНАЦИЯ) ---
@router.callback_query(F.data.startswith("admin_view_users"))
async def admin_view_users_list(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    
    # Извлекаем номер страницы из callback_data (формат: admin_view_users_page_[номер])
    parts = callback.data.split("_")
    page = int(parts[-1]) if len(parts) > 3 and parts[-1].isdigit() else 1
    
    limit = 5  # Выводим строго по 5 пользователей на сообщение, чтобы не спамить
    offset = (page - 1) * limit
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Считаем общее количество пользователей для вычисления страниц
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            total_users = (await c.fetchone())[0]
            
        # Вытягиваем порцию пользователей строго для текущей страницы
        query = "SELECT tg_id, nickname, user_status, rating, deals_count, is_verified FROM users LIMIT ? OFFSET ?"
        async with db.execute(query, (limit, offset)) as cursor:
            users = await cursor.fetchall()
            
    # Вычисляем максимальное количество страниц
    import math
    max_pages = math.ceil(total_users / limit) if total_users > 0 else 1
    
    text = f"👥 **Список пользователей системы (Страница {page}/{max_pages}):**\n\n"
    
    # Собираем инлайн-кнопки для каждого пользователя на этой странице
    inline_keyboard = []
    
    for tg_id, nick, status, rating, deals, is_verified in users:
        kyc_badge = "🟢 Доступ" if is_verified == 1 else "⏳ Ожидает"
        status_name = STATUS_NAMES.get(status, "❌ Закрыт") if is_verified == 1 else "❌ Закрыт"
        
        # Отрезаем хэштег из ника для красоты на кнопке, если нужно
        text += f"• **{nick}** | ID: `{tg_id}`\n  └ KYC: {kyc_badge} | {status_name} | ⭐ {rating:.1f} | 🤝 {deals}\n\n"
        
        # Добавляем персональную кнопку управления в один ряд с ником
        inline_keyboard.append([
            types.InlineKeyboardButton(text=f"⚙️ Управлять {nick.split(' #')[0]}", callback_data=f"usrmng_panel_{tg_id}")
        ])
        
    # Генерируем стрелочки навигации под списком
    navigation_row = []
    if page > 1:
        navigation_row.append(types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_view_users_page_{page - 1}"))
    
    navigation_row.append(types.InlineKeyboardButton(text=f"📄 {page} / {max_pages}", callback_data="dummy_page"))
    
    if page < max_pages:
        navigation_row.append(types.InlineKeyboardButton(text="Вперед ➡️", callback_data=f"admin_view_users_page_{page + 1}"))
        
    inline_keyboard.append(navigation_row)
    inline_keyboard.append([types.InlineKeyboardButton(text="⬅️ Главное меню админки", callback_data="back_to_admin")])
    
    kb_pagination = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    
    # ⚡ ВАЖНО: Мы РЕДАКТИРУЕМ текущее сообщение, а не шлем новые! Нет флуда.
    try:
        await callback.message.edit_text(text, reply_markup=kb_pagination, parse_mode="Markdown")
    except Exception:
        # На случай, если админ нажал ту же страницу и текст не поменялся
        pass
        
        # ГЕНЕРИРУЕМ КНОПКУ ПРЯМОГО ВХОДА В КАРТОЧКУ УПРАВЛЕНИЯ ЭТИМ ЮЗЕРОМ
        kb_user_control = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="⚙️ Открыть пульт модерации", callback_data=f"usrmng_panel_{tg_id}")]
        ])
        
        await callback.message.answer(
            f"• Профиль: {real_profile_link} | ID: `{tg_id}`\n"
            f"  └ Проверка KYC: **{kyc_badge}**\n"
            f"  └ Ранг: {status_name} | ⭐ {rating:.1f} | 🤝 Сделок: {deals}",
            reply_markup=kb_user_control,
            parse_mode="Markdown"
        )

# --- 5. МОДУЛЬ РУЧНОГО УПРАВЛЕНИЯ ПО ID И ОБРАБОТКА ПУЛЬТА МОДЕРАЦИИ ---
@router.callback_query(F.data == "admin_manage_user_start")
async def admin_manage_user_init(callback: types.CallbackQuery, state: FSMContext):
    """Инициализация ручного ввода ID пользователя"""
    await callback.answer()
    await state.set_state(AdminManageStates.waiting_for_user_id)
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Отмена", callback_data="back_to_admin")]])
    await callback.message.edit_text("⚙️ **Управление по ID**\n\nПришлите в ответном сообщении численный **Telegram ID** пользователя:", reply_markup=kb)

@router.message(StateFilter(AdminManageStates.waiting_for_user_id), F.text)
async def admin_handle_id_text(message: types.Message, state: FSMContext):
    """Получение ID текстом и вызов пульта"""
    user_text = message.text.strip()
    if not user_text.isdigit():
        await message.answer("⚠️ Ошибка: ID должен состоять только из цифр. Попробуйте еще раз:")
        return
    await state.clear()
    await render_control_panel(message, int(user_text))

async def render_control_panel(message_obj: types.Message, target_id: int):
    """Вспомогательная функция отрисовки пульта управления пользователем"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT nickname, user_status, rating, deals_count, is_banned, ban_until FROM users WHERE tg_id = ?", (target_id,)) as cursor:
            user_data = await cursor.fetchone()
            
    if not user_data:
        if isinstance(message_obj, types.Message):
            await message_obj.answer("❌ Пользователь с таким ID не найден в базе данных.")
        elif isinstance(message_obj, types.CallbackQuery):
            await message_obj.answer("❌ Данные пользователя не найдены.", show_alert=True)
        return
        
    nick, status, rating, deals, is_banned, ban_until = user_data
    status_text = STATUS_NAMES.get(status, status)
    
    current_time = int(time.time())
    if is_banned == 1: 
        ban_status = "举️ Вечный бан"
    elif ban_until > current_time: 
        ban_status = f"⏳ Временный бан до {time.strftime('%d.%m %H:%M', time.localtime(ban_until))}"
    else: 
        ban_status = "🟢 Чист / Активен"
    
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
    text = (
        f"👤 **ПУЛЬТ МОДЕРАЦИИ ПОЛЬЗОВАТЕЛЯ:**\n\n"
        f"• Профиль: {real_profile_link}\n"
        f"• ID: `{target_id}`\n"
        f"• Текущий ранг: **{status_text}**\n"
        f"• Репутация: ⭐ {rating:.1f} | 🤝 Сделок: {deals}\n"
        f"• Статус ограничений: **{ban_status}**\n\n"
        f"Выберите необходимое действие:"
    )
    
    if isinstance(message_obj, types.CallbackQuery):
        await message_obj.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await message_obj.answer(text, reply_markup=kb, parse_mode="Markdown")

@router.callback_query(F.data.startswith("usrmng_"))
async def admin_process_user_moderation_buttons(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    """Обработчик всех кнопок пульта модерации"""
    await callback.answer()
    parts = callback.data.split("_")
    action = parts[1] # 'panel', 'permban', 'tempban', 'unban', 'setrole', 'saverole'
    target_id = int(parts[2])
    
    # Если кликнули «Открыть пульт» из интерактивного списка
    if action == "panel":
        await render_control_panel(callback, target_id)
        return
    
    async with aiosqlite.connect(DB_NAME) as db:
        if action == "permban":
            await db.execute("UPDATE users SET is_banned = 1 WHERE tg_id = ?", (target_id,))
            await db.commit()
            await callback.message.answer(f"⛔ Пользователь `{target_id}` заблокирован НАВСЕГДА.")
        elif action == "unban":
            await db.execute("UPDATE users SET is_banned = 0, ban_until = 0 WHERE tg_id = ?", (target_id,))
            await db.commit()
            await callback.message.answer(f"✅ Все ограничения с пользователя `{target_id}` полностью сняты.")
        elif action == "tempban":
            await state.set_state(AdminManageStates.waiting_for_ban_time)
            await state.update_data(target_id=target_id)
            await callback.message.answer("⏳ **Ввод времени бана:**\nПришлите количество минут, на которое нужно заблокировать пользователя:")
            return
        elif action == "setrole":
            kb_roles = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🟢 Верифицированный", callback_data=f"usrmng_saverole_{target_id}_verified")],
                [types.InlineKeyboardButton(text="🔥 Трейдер", callback_data=f"usrmng_saverole_{target_id}_trader")],
                [types.InlineKeyboardButton(text="⚡... Трейдер", callback_data=f"usrmng_saverole_{target_id}_super_trader")],
                [types.InlineKeyboardButton(text="🛡️ Гарант Комьюнити", callback_data=f"usrmng_saverole_{target_id}_guarantor_member")],
                [types.InlineKeyboardButton(text="⬅ Назад", callback_data="back_to_admin")]
            ])
            await callback.message.edit_text(f"🎖 **Выбор нового ранга для пользователя {target_id}:**", reply_markup=kb_roles)
            return
        elif action == "saverole":
            new_role = parts[3]
            await db.execute("UPDATE users SET user_status = ? WHERE tg_id = ?", (new_role, target_id))
            await db.commit()
            role_title = STATUS_NAMES.get(new_role, new_role)
            await callback.message.edit_text(f"🎉 Ранг пользователя `{target_id}` успешно изменен на: **{role_title}**.")
            try: 
                await bot.send_message(chat_id=target_id, text=f"🔔 Ваш статус обновлен! Новый ранг: **{role_title}**.")
            except: pass

@router.message(StateFilter(AdminManageStates.waiting_for_ban_time), F.text)
async def admin_save_tempban_time(message: types.Message, state: FSMContext):
    """Сохранение времени временного бана"""
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

# --- 4. СПИСОК ЗАБАНЕННЫХ ПОЛЬЗОВАТЕЛЕЙ ---
@router.callback_query(F.data == "admin_view_banned")
async def admin_view_banned_list(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT tg_id, nickname, is_banned, ban_until FROM users WHERE is_banned = 1 OR ban_until > 0") as cursor:
            banned = await cursor.fetchall()
            
    if not banned:
        await callback.message.edit_text(
            "🚫 Список заблокированных пользователей пуст.", 
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]])
        )
        return
        
    await callback.message.edit_text(
        "🚫 **Заблокированные пользователи:**", 
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад в админку", callback_data="back_to_admin")]])
    )
    
    for tg_id, nick, is_perm, until in banned:
        ban_type = "Вечный бан ⛔" if is_perm == 1 else f"Временный бан до (Unix): `{until}` ⏳"
        real_profile_link = f"[{nick}](tg://user?id={tg_id})"
        
        # Кнопка быстрого перехода в пульт, чтобы разбанить или перенастроить
        kb_user_control = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="⚙️ Открыть пульт модерации", callback_data=f"usrmng_panel_{tg_id}")]
        ])
        
        await callback.message.answer(
            f"• Профиль: {real_profile_link} (ID: `{tg_id}`)\n"
            f"  └ Тип: {ban_type}", 
            reply_markup=kb_user_control, 
            parse_mode="Markdown"
        )

