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
        # Извлекаем новые реквизиты сторон (без Piastrix, добавляем fkwallet и универсальный crypto_address)
        async with db.execute("SELECT card, fkwallet, crypto_address FROM requisites WHERE tg_id = ?", (buyer_id,)) as b_cur:
            b_req = await b_cur.fetchone()
        async with db.execute("SELECT card, fkwallet, crypto_address FROM requisites WHERE tg_id = ?", (seller_id,)) as s_cur:
            s_req = await s_cur.fetchone()
            
        # Узнаем параметры лота для вывода Гаранту четкого направления
        async with db.execute("SELECT direction, amount FROM offers JOIN deals ON deals.offer_id = offers.id WHERE deals.id = ?", (deal_id,)) as o_cur:
            offer_data = await o_cur.fetchone()
        await db.commit()
        
    b_card, b_fk, b_crypto = b_req if b_req else ("не указано", "не указано", "не указано")
    s_card, s_fk, s_crypto = s_req if s_req else ("не указано", "не указано", "не указано")
    
    raw_dir = offer_data[0] if offer_data else "Неизвестно"
    dir_title_text = DIRECTION_TITLES.get(raw_dir, raw_dir)
    amount_val = offer_data[1] if offer_data else "Неизвестно"
    
    # Переводим сделку в статус ожидания оплаты, так как Гарант зашел для подтверждения крипто-депозита
    # (Если это был вызов на диспут, статус 'dispute' не перезаписывается кнопкой прикрепления)
    if status == "waiting_deposit":
        async with aiosqlite.connect(DB_NAME) as db:
            current_time = str(int(time.time()))
            await db.execute("UPDATE deals SET status = 'waiting_payment', timer_start = ? WHERE id = ?", (current_time, deal_id))
            await db.commit()
            
    # Пульт управления для Гаранта в его диалоге с ботом
    kb_admin_control = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ Закрыть спор (Выпустить крипту)", callback_data=f"guarantor_complete_{deal_id}")],
        [types.InlineKeyboardButton(text="❌ Отменить сделку (Вернуть крипту)", callback_data=f"guarantor_cancel_{deal_id}")]
    ])
    
    await callback.message.edit_text(
        f"🔷 **Вы вошли в сделку #{deal_id} в роли Гаранта.**\n"
        f"Анонимный чат для участников открыт. Ваши сообщения будут выделены меткой `[ГАРАНТ]`.\n\n"
        f"🧭 **Четкое направление:** `{dir_title_text}`\n"
        f"💰 **Объем обмена:** `{amount_val}`\n"
        f"----------------------------------------\n"
        f"📋 **ДАННЫЕ ДЛЯ ПРОВЕРКИ ТРАНЗАКЦИЙ:**\n\n"
        f"👤 **Покупатель крипты (ID: `{buyer_id}`):**\n"
        f"• Вывод крипты/Адрес: `{b_crypto}`\n"
        f"• Кошелек FkWallet: `{b_fk}`\n\n"
        f"👤 **Продавец крипты (ID: `{seller_id}`):**\n"
        f"• Карта получения фиата: `{s_card}`\n",
        reply_markup=kb_admin_control,
        parse_mode="Markdown"
    )
    
    # Оповещаем участников об успешном подключении модератора
    # Покупателю автоматически отправляются интерфейсы шага 'waiting_payment' (с реквизитами карты Продавца)
    from actions import send_deal_interface_to_user
    await send_deal_interface_to_user(bot, buyer_id, deal_id, "waiting_payment", buyer_id, seller_id, user_id)
    await send_deal_interface_to_user(bot, seller_id, deal_id, "waiting_payment", buyer_id, seller_id, user_id)
# --- ОБРАБОТКА ДЕЙСТВИЙ ГАРАНТА (РУЧНОЙ ВЫПУСК / ОТМЕНА ПРИ ДИСПУТАХ) ---
@router.callback_query(F.data.startswith("guarantor_"))
async def handle_guarantor_actions(callback: types.CallbackQuery, bot: Bot):
    """Принятие окончательного решения Арбитром/Гарантом по спорной сделке"""
    await callback.answer()
    
    parts = callback.data.split("_")
    action = parts[1]  # 'complete' или 'cancel'
    deal_id = int(parts[2])
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        query = "SELECT buyer_id, seller_id, status, guarantor_id, offer_id FROM deals WHERE id = ?"
        async with db.execute(query, (deal_id,)) as cursor:
            deal = await cursor.fetchone()
            
    if not deal:
        await callback.message.edit_text("❌ Ошибка: Сделка не найдена в базе данных.")
        return
        
    buyer_id, seller_id, status, guarantor_id, offer_id = deal
    
    # Жесткая защита от несанкционированного доступа к кнопкам модерации
    if not guarantor_id or guarantor_id != user_id:
        await callback.answer("🛑 Вы не являетесь назначенным Гарантом этой сделки!", show_alert=True)
        return
        
    if status in ["completed", "cancelled"]:
        await callback.answer("🔒 Эта сделка уже была закрыта или аннулирована ранее.", show_alert=True)
        return

    # Вне зависимости от решения, после вердикта чат закрывается, вызываем меню отзывов из rating.py
    kb_rate_buyer = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"⭐ {i}", callback_data=f"rate_user_{buyer_id}_{i}") for i in range(1, 6)],
        [types.InlineKeyboardButton(text="🏠 В главное меню", callback_data="open_main_menu")]
    ])
    kb_rate_seller = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"⭐ {i}", callback_data=f"rate_user_{seller_id}_{i}") for i in range(1, 6)],
        [types.InlineKeyboardButton(text="🏠 В главное меню", callback_data="open_main_menu")]
    ])

    async with aiosqlite.connect(DB_NAME) as db:
        # --- СЦЕНАРИЙ А: Гарант подтверждает факт оплаты и принудительно выпускает крипту Покупателю ---
        if action == "complete":
            await db.execute("UPDATE deals SET status = 'completed' WHERE id = ?", (deal_id,))
            await db.execute("UPDATE users SET deals_count = deals_count + 1 WHERE tg_id = ?", (buyer_id,))
            await db.execute("UPDATE users SET deals_count = deals_count + 1 WHERE tg_id = ?", (seller_id,))
            await db.commit()
            
            await callback.message.edit_text(f"✅ **Сделка #{deal_id} принудительно закрыта.** Криптовалютный депозит присужден Покупателю.")
            
            await bot.send_message(
                chat_id=buyer_id, 
                text=f"⚖️ **Решение по Диспуту #{deal_id}!**\n\n"
                     f"Арбитр проверил предоставленные чеки и закрыл сделку в вашу пользу. Криптовалютный актив отправлен на ваши реквизиты.\n"
                     f"Пожалуйста, оцените контрагента:", 
                reply_markup=kb_rate_seller,
                parse_mode="Markdown"
            )
            await bot.send_message(
                chat_id=seller_id, 
                text=f"⚖️ **Решение по Диспуту #{deal_id}!**\n\n"
                     f"Арбитр принудительно закрыл сделку в пользу Покупателя на основании подтверждения оплаты.\n"
                     f"Пожалуйста, оцените контрагента:", 
                reply_markup=kb_rate_buyer,
                parse_mode="Markdown"
            )
            return
            
        # --- СЦЕНАРИЙ Б: Гарант отменяет сделку и возвращает крипту Продавцу ---
        elif action == "cancel":
            await db.execute("UPDATE deals SET status = 'cancelled' WHERE id = ?", (deal_id,))
            # Возвращаем исходное объявление обратно в стакан (активируем его)
            await db.execute("UPDATE offers SET status = 'active' WHERE id = ?", (offer_id,))
            await db.commit()
            
            await callback.message.edit_text(f"❌ **Сделка #{deal_id} отменена.** Криптовалютный депозит возвращен Продавцу. Ордер возвращен в торговый стакан.")
            
            cancel_text_buyer = (
                f"❌ **Решение по Диспуту #{deal_id}!**\n\n"
                f"Арбитр аннулировал сделку. Факт оплаты не подтвержден или транзакция отклонена банком. Крипта возвращена Продавцу."
            )
            cancel_text_seller = (
                f"❌ **Решение по Диспуту #{deal_id}!**\n\n"
                f"Арбитр аннулировал сделку в вашу пользу. Криптовалютный депозит разморожен и возвращен на ваш баланс. Ордер снова доступен в стакане."
            )
            
            await bot.send_message(chat_id=buyer_id, text=cancel_text_buyer, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="🏠 В меню", callback_data="open_main_menu")]]), parse_mode="Markdown")
            await bot.send_message(chat_id=seller_id, text=cancel_text_seller, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="🏠 В меню", callback_data="open_main_menu")]]), parse_mode="Markdown")
            return
