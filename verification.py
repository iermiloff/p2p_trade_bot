import aiosqlite
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from config import ADMIN_IDS, REQUIRED_CHANNEL_ID, CHANNEL_INVITE_LINK
from database import DB_NAME

router = Router()

class VerificationStates(StatesGroup):
    waiting_for_data = State()

async def check_user_subscription(bot: Bot, user_id: int) -> bool:
    """
    Проверяет, подписан ли пользователь на обязательный канал/чат.
    Возвращает True, если подписка активна, иначе False.
    """
    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL_ID, user_id=user_id)
        if member.status in ["member", "administrator", "creator", "restricted"]:
            return True
    except Exception as e:
        print(f"[ОШИБКА ПР ПРОВЕРКЕ ПОДПИСКИ ДЛЯ {user_id}]: {e}")
    return False

@router.callback_query(F.data == "start_verification")
async def start_verification_cmd(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    user_id = callback.from_user.id
    
    # Защита от ботоферм: Проверяем подписку перед выдачей FSM-формы
    is_subscribed = await check_user_subscription(bot, user_id)
    
    if not is_subscribed:
        kb_retry = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="📢 Вступить в канал", url=CHANNEL_INVITE_LINK)],
            [types.InlineKeyboardButton(text="🔄 Я вступил, проверить заново", callback_data="start_verification")]
        ])
        await callback.message.answer(
            "⚠️ **Доступ ограничен!**\n\n"
            "Для защиты платформы от спам-ботов, подача заявки на верификацию доступна только для участников нашего официального закрытого сообщества.\n\n"
            "Пожалуйста, вступите в канал по ссылке ниже и нажмите кнопку проверки:",
            reply_markup=kb_retry
        )
        return

    # Если подписан — запускаем стандартный FSM-процесс ввода данных
    await state.set_state(VerificationStates.waiting_for_data)
    await callback.message.answer("📥 Пожалуйста, отправьте скан/фотографию вашего документа или введите текстовые данные для проверки администрацией:")

@router.message(VerificationStates.waiting_for_data)
async def process_verification_data(message: types.Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    await state.clear()
    
    # Извлекаем file_id, если пользователь прислал фотографию
    file_id = message.photo[-1].file_id if message.photo else None
    
    # Записываем file_id в базу данных под этого пользователя
    async with aiosqlite.connect(DB_NAME) as db:
        if file_id:
            await db.execute("UPDATE users SET kyc_file_id = ? WHERE tg_id = ?", (file_id, user_id))
            await db.commit()
            
    await message.answer("⏳ Ваша заявка успешно отправлена администраторам. Ожидайте решения.")
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="👍 Одобрить", callback_data=f"verify_approve_{user_id}"),
            types.InlineKeyboardButton(text="👎 Отклонить", callback_data=f"verify_decline_{user_id}")
        ]
    ])
    
    for admin_id in ADMIN_IDS:
        try:
            # Формируем кликабельную ссылку на реальный профиль для админов
            user_mention = f"[{message.from_user.full_name}](tg://user?id={user_id})"
            username_text = f" | @{message.from_user.username}" if message.from_user.username else ""
            
            await bot.send_message(
                chat_id=admin_id,
                text=f"🔔 **Новая заявка на верификацию!**\n"
                     f"Профиль: {user_mention}{username_text}\n"
                     f"ID пользователя: `{user_id}`\n",
                reply_markup=kb,
                parse_mode="Markdown"
            )
            if message.photo:
                await bot.send_photo(chat_id=admin_id, photo=file_id, caption=message.caption)
            else:
                await bot.send_message(chat_id=admin_id, text=f"Данные заявки:\n{message.text}")
        except Exception:
            continue

@router.callback_query(F.data.startswith("verify_approve_"))
async def approve_verification(callback: types.CallbackQuery, bot: Bot):
    await callback.answer()
    target_id = int(callback.data.replace("verify_approve_", ""))
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET is_verified = 1 WHERE tg_id = ?", (target_id,))
        await db.commit()
        
    await callback.message.edit_text(f"✅ Заявка пользователя `{target_id}` успешно одобрена.")
    try:
        import cabinet
        await bot.send_message(
            chat_id=target_id,
            text="🎉 **Поздравляем! Ваша верификация успешно одобрена администрацией.**\nВам открыт полный доступ к P2P-платформе:",
            reply_markup=cabinet.get_main_keyboard()
        )
    except Exception:
        pass

@router.callback_query(F.data.startswith("verify_decline_"))
async def decline_verification(callback: types.CallbackQuery, bot: Bot):
    await callback.answer()
    target_id = int(callback.data.replace("verify_decline_", ""))
    
    await callback.message.edit_text(f"❌ Заявка пользователя `{target_id}` была отклонена.")
    try:
        await bot.send_message(
            chat_id=target_id,
            text="❌ **Ваша заявка на верификацию была отклонена администрацией.**\nПожалуйста, проверьте корректность отправленных данных и попробуйте снова."
        )
    except Exception:
        pass
