import aiosqlite
from aiogram import Router, F, types
from database import DB_NAME

router = Router()

@router.callback_query(F.data.startswith("rate_user_"))
async def process_user_rating(callback: types.CallbackQuery):
    await callback.answer()
    
    parts = callback.data.split("_")
    target_id = int(parts[2])
    stars = int(parts[3])
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT rating_sum, rating_count FROM users WHERE tg_id = ?", (target_id,)) as cursor:
            res = await cursor.fetchone()
            
        if not res:
            await callback.message.edit_text("⚠️ Ошибка: Пользователь не найден в базе данных.")
            return
            
        current_sum, current_count = res
        
        new_sum = current_sum + stars
        new_count = current_count + 1
        new_rating = round(float(new_sum) / float(new_count), 2)
        
        await db.execute(
            "UPDATE users SET rating_sum = ?, rating_count = ?, rating = ? WHERE tg_id = ?", 
            (new_sum, new_count, new_rating, target_id)
        )
        await db.commit()
        
    # ⚡ ГЕЙМИФИКАЦИЯ И УДОБСТВО: Создаем кнопку быстрого бесшовного возврата в Личный Кабинет
    kb_to_menu = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🏠 В главное меню", callback_data="open_main_menu")]
    ])
        
    # Перерисовываем клавиатуру звезд на аккуратную кнопку возврата
    await callback.message.edit_text(
        f"✅ Спасибо! Вы успешно выставили оценку контрагенту: **⭐️ {stars}**.\n"
        f"Сделка полностью закрыта и архивирована. Вы можете вернуться к торговле:", 
        reply_markup=kb_to_menu
    )
