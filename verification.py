import aiosqlite
from aiogram import Router, F, types, Bot
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from config import ADMIN_IDS
from database import DB_NAME

router = Router()

# Определяем состояния для машины состояний (FSM)
class VerificationStates(StatesGroup):
    waiting_for_data = State()

@router.callback_query(F.data == "start_verification")
async def process_verification_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    
    # Ссылка на Telegra.ph или другую внешнюю страницу с инструкцией
    instruction_url = "https://telegra.ph" # Замените на реальную ссылку при деплое
    
    await state.set_state(VerificationStates.waiting_for_data)
    await callback.message.answer(
        f"📖 **Инструкция по верификации:**\n"
        f"Пожалуйста, ознакомьтесь с правилами по ссылке:\n{instruction_url}\n\n"
        f"После ознакомления, пришлите в ответном сообщении подтверждающий скриншот "
        f"или текст (например, ваш юзернейм на бирже/кошельке) для проверки администратором."
    )

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
            # Формируем кликабельную ссылку на реальный профиль для админы
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

# Обработчик кнопок администратора ( Approve / Decline )
@router.callback_query(F.data.startswith("verify_"))
async def process_admin_decision(callback: types.CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    if admin_id not in ADMIN_IDS:
        await callback.answer("⚠ Вы не являетесь администратором!", show_alert=True)
        return
        
    # Разбираем callback_data (например: verify_approve_12345678)
    data_parts = callback.data.split("_")
    action = data_parts[1] # approve или decline
    target_user_id = int(data_parts[2])
    
    async with aiosqlite.connect(DB_NAME) as db:
        if action == "approve":
            # Меняем статус верификации на 1 (Истина)
            await db.execute("UPDATE users SET is_verified = 1 WHERE tg_id = ?", (target_user_id,))
            await db.commit()
            
            await callback.message.edit_text(f"✅ Пользователь `{target_user_id}` успешно верифицирован.")
            try:
                # Уведомляем пользователя об успешной верификации
                await bot.send_message(
                    chat_id=target_user_id,
                    text="🎉 **Поздравляем!** Ваша верификация успешно одобрена администратором.\n"
                         "Используйте команду `/start` или нажмите кнопку, чтобы открыть Главное меню."
                )
            except Exception:
                pass
                
        elif action == "decline":
            await callback.message.edit_text(f"❌ Заявка пользователя `{target_user_id}` была отклонена.")
            try:
                await bot.send_message(
                    chat_id=target_user_id,
                    text="❌ К сожалению, ваша заявка на верификацию была отклонена администратором.\n"
                         "Вы можете попробовать отправить данные повторно, нажав кнопку верификации."
                )
            except Exception:
                pass
                
    await callback.answer()
