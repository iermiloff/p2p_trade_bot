import aiosqlite
from aiogram import Router, F, types, Bot
from config import ADMIN_IDS
from database import DB_NAME, is_user_guarantor

router = Router()

# --- ВХОД АДМИНИСТРАТОРА ИЛИ ГАРАНТА КОМЬЮНИТИ В СДЕЛКУ ---
@router.callback_query(F.data.startswith("admin_claim_deal_"))
async def admin_claim_deal(callback: types.CallbackQuery, bot: Bot):
    await callback.answer()
    
    user_id = callback.from_user.id
    # Гарантированно берем ID сделки с самого конца строки
    deal_id = int(callback.data.split("_")[-1]) 
    
    # 1. Защита от конфликта гарантов
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT guarantor_id FROM deals WHERE id = ?", (deal_id,)) as cursor:
            res_g = await cursor.fetchone()
            
    if res_g and res_g[0] is not None:
        if res_g[0] != user_id:
            await callback.answer("❌ Эта сделка уже взята другим Гарантом!", show_alert=True)
            try:
                await callback.message.edit_text(f"🔒 Сделка #{deal_id} уже обрабатывается другим Гарантом.")
            except Exception: pass
            return

    # 2. Проверка прав доступа
    is_allowed = user_id in ADMIN_IDS
    if not is_allowed:
        is_allowed = await is_user_guarantor(user_id)
        
    if not is_allowed:
        await callback.answer("⚠️ У вас нет прав Гаранта для модерации этой сделки!", show_alert=True)
        return
        
    # 3. Бронируем сделку за собой
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE deals SET guarantor_id = ? WHERE id = ?", (user_id, deal_id))
        async with db.execute("SELECT buyer_id, seller_id FROM deals WHERE id = ?", (deal_id,)) as cursor:
            buyer_id, seller_id = await cursor.fetchone()
        async with db.execute("SELECT card, piastrix, ton FROM requisites WHERE tg_id = ?", (buyer_id,)) as b_cur:
            b_req = await b_cur.fetchone()
        async with db.execute("SELECT card, piastrix, ton FROM requisites WHERE tg_id = ?", (seller_id,)) as s_cur:
            s_req = await s_cur.fetchone()
        await db.commit()
        
    b_card, b_pias, b_ton = b_req if b_req else ("не указано", "не указано", "не указано")
    s_card, s_pias, s_ton = s_req if s_req else ("не указано", "не указано", "не указано")
        
    # Пульт управления для Гаранта (Четкий синтаксис callback_data из 4 элементов)
    kb_admin_control = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🎉 Закрыть (Выпустить средства)", callback_data=f"deal_action_gcomplete_{deal_id}")],
        [types.InlineKeyboardButton(text="❌ Отменить (Вернуть средства)", callback_data=f"deal_action_gcancel_{deal_id}")]
    ])
        
    await callback.message.edit_text(
        f"✅ Вы вошли в сделку #{deal_id} как официальный Гарант.\n"
        f"💬 Напишите свои реквизиты в анонимный чат для депонирования.\n\n"
        f"📋 **ДАННЫЕ ДЛЯ ПРОВЕРКИ ЧЕКОВ:**\n\n"
        f"⚠️ **Внимание:** Удержите **5% комиссии** платформы при выплате средств!\n\n"
        f"👤 **Покупатель (ID: `{buyer_id}`):**\n• Карты: `{b_card}`\n• Piastrix: `{b_pias}`\n• TON: `{b_ton}`\n\n"
        f"👤 **Продавец (ID: `{seller_id}`):**\n• Карты: `{s_card}`\n• Piastrix: `{s_pias}`\n• TON: `{s_ton}`\n\n",
        reply_markup=kb_admin_control,
        parse_mode="Markdown"
    )
    
    # ⚡ ПРИНУДИТЕЛЬНЫЙ АВТО-ВЫВОД КНОПКИ ПОКУПАТЕЛЮ:
    # Гарант зашел, значит Покупатель обязан МГНОВЕННО получить рабочий пульт взамен заглушки ожидания
    kb_buyer_pay = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🟩 Я перевел средства Гаранту", callback_data=f"deal_action_paid_{deal_id}")]
    ])
    
    await bot.send_message(
        chat_id=buyer_id, 
        text=f"⚡ **Гарант успешно подключился к сделке #{deal_id}!**\n\n"
             f"Ожидайте официальные реквизиты Гаранта в анонимном чате ниже.\n"
             f"После того как вы переведете фиат на указанные Гарантом счета, нажмите кнопку активации:", 
        reply_markup=kb_buyer_pay
    )
    await bot.send_message(chat_id=seller_id, text=f"⚡ **Гарант успешно подключился к сделке #{deal_id}!**\nОжидайте депонирования средств Покупателем и команды от Гаранта в чате.")


# --- ОБРАБОТКА ДЕЙСТВИЙ ГАРАНТА (РУЧНОЙ ВЫПУСК / ОТМЕНА) ---
@router.callback_query(F.data.startswith("deal_action_g"))
async def handle_guarantor_actions(callback: types.CallbackQuery, bot: Bot):
    await callback.answer()
    
    # ⚡ ЖЕСТКИЙ ПРЯМОЙ ПАРСИНГ: Извлекаем экшен и ID по точным индексам (строго делим строку deal_action_gcomplete_ID)
    parts = callback.data.split("_")
    action = parts[2]         # Индекс 2 — это строго 'gcomplete' или 'gcancel'
    deal_id = int(parts[3])    # Индекс 3 — это строго числовой ID сделки
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT buyer_id, seller_id, status, guarantor_id, offer_id FROM deals WHERE id = ?", (deal_id,)) as cursor:
            deal = await cursor.fetchone()
            
    if not deal:
        await callback.message.edit_text("❌ Ошибка: Сделка не найдена в базе данных.")
        return
        
    buyer_id, seller_id, status, guarantor_id, offer_id = deal
    
    if not guarantor_id or guarantor_id != user_id:
        await callback.answer("⚠️ Вы не являетесь назначенным Гарантом этой сделки!", show_alert=True)
        return
        
    if status == "completed" or status == "cancelled":
        await callback.answer("⚠️ Эта сделка уже была закрыта или аннулирована ранее.", show_alert=True)
        return

    async with aiosqlite.connect(DB_NAME) as db:
        # 🎉 А: Ручной выпуск средств Гарантом
        if action == "gcomplete":
            await db.execute("UPDATE deals SET status = 'completed' WHERE id = ?", (deal_id,))
            await db.execute("UPDATE users SET deals_count = deals_count + 1 WHERE tg_id = ?", (buyer_id,))
            await db.execute("UPDATE users SET deals_count = deals_count + 1 WHERE tg_id = ?", (seller_id,))
            await db.commit()
            
            kb_rate_seller = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text=f"⭐️ {i}", callback_data=f"rate_user_{seller_id}_{i}") for i in range(1, 6)],
                [types.InlineKeyboardButton(text="🏠 В главное меню", callback_data="open_main_menu")]
            ])
            kb_rate_buyer = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text=f"⭐️ {i}", callback_data=f"rate_user_{buyer_id}_{i}") for i in range(1, 6)],
                [types.InlineKeyboardButton(text="🏠 В главное меню", callback_data="open_main_menu")]
            ])

            await callback.message.edit_text(f"✅ Вы успешно закрыли сделку #{deal_id} в качестве Гаранта. Сделка зафиксирована на диске.")
            
            await bot.send_message(
                chat_id=buyer_id, 
                text=f"🎉 **Сделка #{deal_id} успешно завершена Гарантом!**\n\nПожалуйста, оцените работу Продавца от 1 до 5 звёзд или вернитесь в меню:", 
                reply_markup=kb_rate_seller
            )
            await bot.send_message(
                chat_id=seller_id, 
                text=f"🎉 **Сделка #{deal_id} успешно завершена Гарантом!**\n\nОжидайте ручной перевод фиата от Гаранта на ваши реквизиты.\nПожалуйста, оцените работу Покупателя от 1 до 5 звёзд или вернитесь в меню:", 
                reply_markup=kb_rate_buyer
            )
            return

        # ❌ Б: Ручная отмена сделки Гарантом
        elif action == "gcancel":
            await db.execute("UPDATE deals SET status = 'cancelled' WHERE id = ?", (deal_id,))
            await db.execute("UPDATE offers SET status = 'active' WHERE id = ?", (offer_id,))
            await db.commit()
            
            cancel_text = f"❌ **Сделка #{deal_id} ОТМЕНЕНА ГАРАНТОМ!**\nЗаявка вернулась в стакан, средства подлежат возврату."
            await callback.message.edit_text(f"❌ Вы успешно отменили сделку #{deal_id}. Ордер возвращен в стакан.")
            
            await bot.send_message(chat_id=buyer_id, text=cancel_text)
            await bot.send_message(chat_id=seller_id, text=cancel_text)
            return

