import aiosqlite
import time
from aiogram import Router, F, types, Bot
from config import ADMIN_IDS
from database import DB_NAME

router = Router()

@router.callback_query(F.data.startswith("deal_action_"))
async def handle_deal_actions(callback: types.CallbackQuery, bot: Bot):
    await callback.answer()
    parts = callback.data.split("_")
    action = parts[2]  # 'accept', 'reject', 'paid', 'completed', 'dispute'
    deal_id = int(parts[3])
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT buyer_id, seller_id, status, use_guarantor, offer_id FROM deals WHERE id = ?", (deal_id,)) as cursor:
            deal = await cursor.fetchone()
            
        if not deal:
            return
        buyer_id, seller_id, status, use_guarantor, offer_id = deal
        
        # --- Действие: Продавец принял сделку (Таймер 2) ---
        if action == "accept" and user_id == seller_id and status == "waiting_seller":
            current_time = str(int(time.time()))
            await db.execute("UPDATE deals SET status = 'waiting_payment', timer_start = ? WHERE id = ?", (current_time, deal_id))
            
            async with db.execute("SELECT card, piastrix, ton FROM requisites WHERE tg_id = ?", (seller_id,)) as c_cur:
                s_req = await c_cur.fetchone()
            async with db.execute("SELECT card, piastrix, ton FROM requisites WHERE tg_id = ?", (buyer_id,)) as b_cur:
                b_req = await b_cur.fetchone()
            await db.commit()
            
            s_card, s_pias, s_ton = s_req if s_req else ("не указано", "не указано", "не указано")
            b_card, b_pias, b_ton = b_req if b_req else ("не указано", "не указано", "не указано")
            
            # ВЕТКА А: СДЕЛКА С ГАРАНТОМ
            if use_guarantor == 1:
                await bot.send_message(
                    chat_id=buyer_id,
                    text=f"🛡️ **Сделка #{deal_id} принята продавцом ЧЕРЕЗ ГАРАНТА!**\n💬 Анонимный чат открыт.\n\n"
                         f"⚠️ **ВАЖНО:** Пожалуйста, **НЕ ПЕРЕВОДИТЕ** средства продавцу напрямую!\n"
                         f"Дождитесь Гаранта. Из итоговой суммы обмена будет удержано **5% комиссии** сервиса."
                )
                await bot.send_message(
                    chat_id=seller_id,
                    text=f"🛡️ **Сделка #{deal_id} открыта ЧЕРЕЗ ГАРАНТА!**\n💬 Анонимный чат открыт.\n\n"
                         f"Ожидайте подключения Гаранта. Напоминаем, что выплата средств получателю производится за вычетом **5% комиссии** платформы."
                )

                # Отправляем алерт всей команде Гарантов
                kb_admin = types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="⚡ Взять сделку как Гарант", callback_data=f"admin_claim_deal_{deal_id}")]
                ])
                async with db.execute("SELECT direction, amount FROM offers WHERE id = ?", (offer_id,)) as o_cur:
                    o_res = await o_cur.fetchone()
                o_dir = o_res[0] if o_res else "Неизвестно"
                o_amt = o_res[1] if o_res else "Неизвестно"

                all_guarantor_ids = list(ADMIN_IDS)
                async with db.execute("SELECT tg_id FROM users WHERE user_status = 'guarantor_member'") as g_cursor:
                    rows = await g_cursor.fetchall()
                    for row in rows:
                        if row[0] not in all_guarantor_ids: 
                            all_guarantor_ids.append(row[0])

                for receiver_id in all_guarantor_ids:
                    try:
                        await bot.send_message(
                            chat_id=receiver_id, 
                            text=f"🚨 **Требуется Гарант для сделки #{deal_id}!**\nНаправление: `{o_dir}`\nСумма: `{o_amt}`", 
                            reply_markup=kb_admin
                        )
                    except: 
                        continue
                return

            # ВЕТКА Б: ОБЫЧНАЯ ПРЯМАЯ СДЕЛКА
            else:
                kb_buyer = types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="🟩 Я перевел средства", callback_data=f"deal_action_paid_{deal_id}")]
                ])

                try:
                    # Так как мы пишем Покупателю от имени клика Продавца, нам нужен bot.edit_message_text
                    # Для этого вытащим message_id Покупателя. Но чтобы не усложнять, мы просто обновим 
                    # сообщение Продавца, а Покупателю отправим чистый пульт, удалив старый.
                    # Давайте сделаем самый надежный и бесшовный вариант:
                    
                    # 1. Продавцу перерисовываем его экран принятия сделки в статус ожидания:
                    await callback.message.edit_text(
                        f"🤝 **Вы подтвердили прямую сделку #{deal_id}.**\n"
                        f"💬 Анонимный чат открыт.\n\n"
                        f"Реквизиты покупателя для сверки:\n"
                        f"💳 Карты: `{b_card}` | 📱 Piastrix: `{b_pias}` | 💎 TON: `{b_ton}`\n\n"
                        f"Ожидайте оплату. Покупателю отправлены ваши реквизиты."
                    )
                    
                    # 2. Покупателю шлем чистую карточку оплаты (старую плашку Таймера 1 он закроет ЛК или старт)
                    await bot.send_message(
                        chat_id=buyer_id,
                        text=f"✅ **Продавец подтвердил прямую сделку #{deal_id}!**\n"
                             f"💬 Анонимный чат открыт.\n\n"
                             f"📋 **ОФИЦИАЛЬНЫЕ РЕКВИЗИТЫ ПРОДАВЦА:**\n"
                             f"💳 Карты: `{s_card}`\n📱 Piastrix: `{s_pias}`\n💎 TON: `{s_ton}`\n\n"
                             f"⚠️ Переводите средства СТРОГО по указанным реквизитам. Если контрагент просит другую карту в чате — это мошенник!\n\n"
                             f"⏳ Запущен **Таймер 2 (10 минут)**. После перевода нажмите кнопку ниже:",
                        reply_markup=kb_buyer
                    )
                except Exception as e:
                    print(f"Ошибка UX рендеринга: {e}")
                return


        # --- Действие: Продавец отклонил сделку ---
        elif action == "reject" and user_id == seller_id and status == "waiting_seller":
            await db.execute("UPDATE deals SET status = 'cancelled' WHERE id = ?", (deal_id,))
            await db.execute("UPDATE offers SET status = 'active' WHERE id = ?", (offer_id,))
            await db.commit()
            await callback.message.edit_text(f"❌ Вы отклонили сделку #{deal_id}. Объявление вернулось в стакан.")
            await bot.send_message(chat_id=buyer_id, text=f"❌ Продавец отклонил сделку #{deal_id}. Ордер вернулся в стакан.")
            return

        # --- Действие: Покупатель отметил "Оплачено" (Таймер 3) ---
        elif action == "paid" and user_id == buyer_id and status == "waiting_payment":
            current_time = str(int(time.time()))
            await db.execute("UPDATE deals SET status = 'waiting_delivery', timer_start = ? WHERE id = ?", (current_time, deal_id))
            await db.commit()
            
            kb_seller = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🎉 Обмен завершен (Средства у меня)", callback_data=f"deal_action_completed_{deal_id}")],
                [types.InlineKeyboardButton(text="🚨 Вызвать Гаранта (Спор)", callback_data=f"deal_action_dispute_{deal_id}")]
            ])
            await callback.message.answer("🟩 Вы подтвердили отправку средств. Ожидаем встречного подтверждения от продавца.")
            await bot.send_message(
                chat_id=seller_id,
                text=f"💰 Покупатель отметил сделку #{deal_id} как **ОПЛАЧЕННУЮ**.\nПроверьте ваш счет.\n⏳ Запущен **Таймер 3 (10 минут)**. Нажмите кнопку для завершения:",
                reply_markup=kb_seller
            )
            return

        # --- Действие: Успешное закрытие прямой сделки Продавцом ---
        elif action == "completed" and user_id == seller_id and status == "waiting_delivery":
            async with db.execute("SELECT status FROM deals WHERE id = ?", (deal_id,)) as check_cur:
                res_status = await check_cur.fetchone()
            if res_status and res_status[0] == "completed":
                return

            await db.execute("UPDATE deals SET status = 'completed' WHERE id = ?", (deal_id,))
            await db.execute("UPDATE users SET deals_count = deals_count + 1 WHERE tg_id = ?", (buyer_id,))
            await db.execute("UPDATE users SET deals_count = deals_count + 1 WHERE tg_id = ?", (seller_id,))
            await db.commit()
            
            kb_rate_seller = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text=f"⭐️ {i}", callback_data=f"rate_user_{seller_id}_{i}") for i in range(1, 6)]])
            kb_rate_buyer = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text=f"⭐️ {i}", callback_data=f"rate_user_{buyer_id}_{i}") for i in range(1, 6)]])
            
            await callback.message.edit_text(f"🎉 **Сделка #{deal_id} успешно завершена!**\nЧат закрыт. Пожалуйста, оцените Покупателя от 1 до 5 звёзд:", reply_markup=kb_rate_buyer)
            await bot.send_message(chat_id=buyer_id, text=f"🎉 **Сделка #{deal_id} успешно завершена!**\nПродавец подтвердил получение. Пожалуйста, оцените Продавца от 1 до 5 звёзд:", reply_markup=kb_rate_seller)
            return

        # --- Действие: Открытие диспута вручную ---
        elif action == "dispute" and status == "waiting_delivery":
            await db.execute("UPDATE deals SET status = 'dispute' WHERE id = ?", (deal_id,))
            await db.commit()
            
            dispute_text = "🚨 **Открыт спор по сделке!**\nТаймеры заморожены. К анонимному чату вызывается Администратор-Гарант для проверки чеков."
            await callback.message.answer(dispute_text)
            await bot.send_message(chat_id=buyer_id, text=dispute_text)
            
            all_guarantor_ids = list(ADMIN_IDS)
            async with db.execute("SELECT tg_id FROM users WHERE user_status = 'guarantor_member'") as g_cursor:
                rows = await g_cursor.fetchall()
                for row in rows:
                    if row[0] not in all_guarantor_ids: 
                        all_guarantor_ids.append(row[0])

            for g_id in all_guarantor_ids:
                try:
                    await bot.send_message(chat_id=g_id, text=f"⚠️ **ВНИМАНИЕ! Открыт спор (Диспут) по сделке #{deal_id}!** Требуется вмешательство.")
                except: 
                    continue
            return
