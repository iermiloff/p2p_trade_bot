import aiosqlite
import time
from aiogram import Router, F, types, Bot
from config import ADMIN_IDS
from database import DB_NAME, is_user_guarantor
from constants import DIRECTION_TITLES

router = Router()

# --- ВХОД АДМИНИСТРАТОРА ИЛИ ГАРАНТА КОМЬЮНИТИ В СДЕЛКУ ---
@router.callback_query(F.data.startswith("admin_claim_deal_"))
async def admin_claim_deal(callback: types.CallbackQuery, bot: Bot):
    """Назначение Гаранта/Арбитра на сделку для проверки депозита или разбора диспута"""
    await callback.answer()
    
    user_id = callback.from_user.id
    deal_id = int(callback.data.split("_")[-1]) 
    
    # 1. Защита от конфликта гарантов (Race Condition)
    async with aiosqlite.connect(DB_NAME) as db:
        query = "SELECT guarantor_id, buyer_id, seller_id, status FROM deals WHERE id = ?"
        async with db.execute(query, (deal_id,)) as cursor:
            deal_data = await cursor.fetchone()
            
    if not deal_data:
        await callback.answer("❌ Сделка не найдена в системе.", show_alert=True)
        return
        
    current_guarantor_id, buyer_id, seller_id, status = deal_data
    
    # Проверяем, не перехвачена ли сделка другим админом
    if current_guarantor_id is not None and current_guarantor_id != 0:
        if current_guarantor_id != user_id:
            await callback.answer("❌ Эта сделка уже взята другим Гарантом!", show_alert=True)
            try: await callback.message.edit_text(f"🔒 Сделка #{deal_id} уже обрабатывается другим Гарантом.")
            except Exception: pass
            return
            
    # ИЗОЛЯЦИЯ РОЛЕЙ: Гарант не должен быть участником сделки
    if user_id == buyer_id or user_id == seller_id:
        await callback.answer("❌ Вы являетесь участником этой сделки! Вы не можете взять её на модерацию.", show_alert=True)
        return
        
    # 2. Проверка прав доступа модератора
    is_allowed = user_id in ADMIN_IDS
    if not is_allowed:
        is_allowed = await is_user_guarantor(user_id)
        
    if not is_allowed:
        await callback.answer("🛑 У вас нет прав Гаранта для модерации этой сделки!", show_alert=True)
        return

    # 3. Бронируем сделку за текущим Гарантом
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE deals SET guarantor_id = ? WHERE id = ?", (user_id, deal_id))
        
        # Запрос ко всем 5 полям реквизитов
        req_query = "SELECT card, crypto_bot, bybit, other_wallets, fkwallet FROM requisites WHERE tg_id = ?"
        async with db.execute(req_query, (buyer_id,)) as b_cur: b_req = await b_cur.fetchone()
        async with db.execute(req_query, (seller_id,)) as s_cur: s_req = await s_cur.fetchone()
            
        # Узнаем параметры лота для вывода Гаранту четкого направления
        async with db.execute("SELECT direction, amount FROM offers JOIN deals ON deals.offer_id = offers.id WHERE deals.id = ?", (deal_id,)) as o_cur:
            offer_data = await o_cur.fetchone()
        await db.commit()
        
    b_card, b_cbot, b_bybit, b_other, b_fk = b_req if b_req else ("не указано", "не указано", "не указано", "не указано", "не указано")
    s_card, s_cbot, s_bybit, s_other, s_fk = s_req if s_req else ("не указано", "не указано", "не указано", "не указано", "не указано")
    
    raw_dir = offer_data if offer_data else "Неизвестно"
    dir_title_text = DIRECTION_TITLES.get(raw_dir, raw_dir)
    amount_val = offer_data if offer_data else "Неизвестно"
    
    # ИСПРАВЛЕНО: Сделка ОСТАЕТСЯ в статусе waiting_deposit! Мы не переводим её в waiting_payment раньше времени.
    # Пульт управления для Гаранта, пока он ждет монеты от Продавца
    kb_admin_control = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ Крипта на балансе (Открыть фиатный шаг)", callback_data=f"guarantor_confirm_crypto_{deal_id}")],
        [types.InlineKeyboardButton(text="❌ Отменить сделку", callback_data=f"guarantor_cancel_{deal_id}")]
    ])
    
    await callback.message.edit_text(
        f"🔷 **Вы вошли в сделку #{deal_id} в роли Гаранта.**\n"
        f"Анонимный чат для участников открыт. Ваши сообщения выделены меткой `[ГАРАНТ]`.\n\n"
        f"🧭 **Четкое направление:** `{dir_title_text}`\n"
        f"💰 **Объем обмена:** `{amount_val}`\n"
        f"----------------------------------------\n"
        f"📋 **ДАННЫЕ ДЛЯ ПРОВЕРКИ ТРАНЗАКЦИЙ (Покупатель):**\n"
        f"• Crypto Bot: `{b_cbot}`\n"
        f"• Bybit UID/Wallet: `{b_bybit}`\n"
        f"• Внешний кошелек: `{b_other}`\n"
        f"• Кошелек FkWallet: `{b_fk}`\n\n"
        f"📋 **ДАННЫЕ ДЛЯ ПРОВЕРКИ ТРАНЗАКЦИЙ (Продавец):**\n"
        f"• Карта получения фиата: `{s_card}`\n\n"
        f"💬 **Чат открыт.** Напишите продавцу адрес вашего кошелька. После того как он переведет крипту, нажмите верхнюю кнопку:",
        reply_markup=kb_admin_control,
        parse_mode="Markdown"
    )
    
    # Оповещаем участников. Статус передаем строго 'waiting_deposit'
    from deals.actions import send_deal_interface_to_user
    await send_deal_interface_to_user(bot, buyer_id, deal_id, "waiting_deposit", buyer_id, seller_id, user_id)
    await send_deal_interface_to_user(bot, seller_id, deal_id, "waiting_deposit", buyer_id, seller_id, user_id)
@router.callback_query(F.data.startswith("guarantor_confirm_crypto_"))
async def guarantor_confirm_crypto_received(callback: types.CallbackQuery, bot: Bot):
    """Гарант лично проверил кошелёк, увидел крипту и даёт отмашку Покупателю платить рубли"""
    await callback.answer()
    deal_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Защита от повторного нажатия (Double-Spend / Click)
        async with db.execute("SELECT status, buyer_id, seller_id FROM deals WHERE id = ?", (deal_id,)) as cursor:
            deal_check = await cursor.fetchone()
            
        if not deal_check:
            await callback.message.answer("❌ Сделка не найдена.")
            return
            
        status, buyer_id, seller_id = deal_check
        if status != "waiting_deposit":
            await callback.answer("⚠️ Эта сделка уже переведена на следующий шаг!", show_alert=True)
            return
            
        # Переводим сделку на этап оплаты фиатом ТОЛЬКО ТЕПЕРЬ
        current_time = str(int(time.time()))
        await db.execute("UPDATE deals SET status = 'waiting_payment', timer_start = ? WHERE id = ?", (current_time, deal_id))
        await db.commit()
        
    # Меняем пульт Гаранта на финальный (Где кнопки ручного закрытия/отмены диспута)
    kb_admin_final = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ Закрыть спор (Выпустить крипту)", callback_data=f"guarantor_complete_{deal_id}")],
        [types.InlineKeyboardButton(text="❌ Отменить сделку (Вернуть крипту)", callback_data=f"guarantor_cancel_{deal_id}")]
    ])
    
    try:
        await callback.message.edit_reply_markup(reply_markup=kb_admin_final)
    except Exception:
        pass
    
    # Перерисовываем интерфейсы пользователям. Покупатель НАКОНЕЦ-ТО видит карту Продавца и платит рубли!
    from deals.actions import send_deal_interface_to_user
    await send_deal_interface_to_user(bot, buyer_id, deal_id, "waiting_payment", buyer_id, seller_id, user_id)
    await send_deal_interface_to_user(bot, seller_id, deal_id, "waiting_payment", buyer_id, seller_id, user_id)
    
    await callback.message.answer(f"🚀 **Депозит подтверждён!** Покупателю отправлены реквизиты для перевода рублей на карту.")

