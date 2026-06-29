import aiosqlite
import time
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext  
from config import ADMIN_IDS
from database import DB_NAME, has_active_deal, has_required_requisites, is_user_guarantor

router = Router()

# --- ОТКРЫТИЕ СДЕЛКИ (ЗАЩИТА И ПЕРВЫЙ ТАЙМЕР) ---
@router.callback_query(F.data.startswith("deal_open_"))
async def process_deal_opening(callback: types.CallbackQuery, bot: Bot):
    buyer_id = callback.from_user.id
    
    # Разбираем callback: deal_open_[direct/guarantor]_[offer_id]
    parts = callback.data.split("_")
    
    # ⚡ СТРОГОЕ ИСПРАВЛЕНИЕ: берём индекс 3 (четвертый элемент списка)
    # Это гарантирует, что мы превращаем в число именно строку '15', а не весь список
    offer_id = int(parts[3]) 
    mode = parts[2]  # 'direct' или 'guarantor'
    
    # 🛡️ ЗАЩИТА: Проверяем, заполнил ли ПОКУПАТЕЛЬ реквизиты для этого направления
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT direction FROM offers WHERE id = ?", (offer_id,)) as cursor:
            res_dir = await cursor.fetchone()
            
    if res_dir:
        direction = res_dir[0]
        if not await has_required_requisites(buyer_id, direction):
            await callback.answer(
                "⚠️ Отказано в сделке!\n\n"
                "Вы не можете принять это объявление, пока сами не заполните свои реквизиты для данного направления в Личном Кабинете.",
                show_alert=True
            )
            return

    # 🛡️ ЗАЩИТА 1: У покупателя не должно быть других активных сделок
    if await has_active_deal(buyer_id):
        await callback.answer("⚠️ Вы не можете открыть новую сделку, пока не завершите или не отмените текущую!", show_alert=True)
        return
                
    async with aiosqlite.connect(DB_NAME) as db:
        # Проверяем, существует ли еще объявление и активно ли оно
        async with db.execute("SELECT creator_id, direction, amount, rate FROM offers WHERE id = ? AND status = 'active'", (offer_id,)) as cursor:
            offer = await cursor.fetchone()
            
        if not offer:
            await callback.answer("⚠️ Данная заявка уже неактивна или принята кем-то другим.", show_alert=True)
            return
            
        seller_id, direction, amount, rate = offer
        use_guarantor = 1 if mode == "guarantor" else 0
        current_time = str(int(time.time()))
        
        # Меняем статус объявления на 'closed' (бронируем под эту сделку)
        await db.execute("UPDATE offers SET status = 'closed' WHERE id = ?", (offer_id,))
        
        # Создаем саму сделку (Статус: waiting_seller — ожидание Таймера 1)
        cursor = await db.execute(
            """INSERT INTO deals (offer_id, buyer_id, seller_id, status, use_guarantor, timer_start) 
               VALUES (?, ?, ?, 'waiting_seller', ?, ?)""",
            (offer_id, buyer_id, seller_id, use_guarantor, current_time)
        )
        deal_id = cursor.lastrowid
        await db.commit()
        
    await callback.answer()
    
    # Оповещаем продавца (Таймер 1)
    kb_seller = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ Принять сделку", callback_data=f"deal_action_accept_{deal_id}"),
         types.InlineKeyboardButton(text="❌ Отклонить", callback_data=f"deal_action_reject_{deal_id}")]
    ])
    
    await bot.send_message(
        chat_id=seller_id,
        text=f"🔔 **Вашу заявку хотят принять! (Сделка #{deal_id})**\n"
             f"Объем: `{amount}`, Курс: `{rate}`\n"
             f"Тип сделки: {'🛡️ С ГАРАНТОМ' if use_guarantor else 'Прямая'}\n\n"
             f"⏳ У вас есть **10 минут** на подтверждение, иначе сделка аннулируется автоматически.",
        reply_markup=kb_seller
    )
    
# ⚡ ДОБАВЛЯЕМ ПЛАНШЕТ С ИНФОРМАЦИЕЙ О КОМИССИИ ДЛЯ ПОКУПАТЕЛЯ
    fee_text = ""
    if use_guarantor:
        fee_text = "\n\n⚠️ **Обратите внимание:** Вы выбрали безопасную сделку. Комиссия Гаранта составляет **10%** от суммы обмена (покрывает транзакционные издержки сети/Piastrix)."

    await callback.message.answer(
        f"⏳ Сделка #{deal_id} инициирована!\n"
        f"Запущен **Таймер 1 (10 минут)**. Ожидаем подтверждения от продавца...{fee_text}",
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("deal_action_"))
async def handle_deal_actions(callback: types.CallbackQuery, bot: Bot):
    await callback.answer()
    parts = callback.data.split("_")
    action = parts[2] # 'accept', 'reject', 'paid', 'completed', 'dispute'
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
            
            # Достаем реквизиты обеих сторон из базы
            async with db.execute("SELECT card, piastrix, ton FROM requisites WHERE tg_id = ?", (seller_id,)) as c_cur:
                s_req = await c_cur.fetchone()
            async with db.execute("SELECT card, piastrix, ton FROM requisites WHERE tg_id = ?", (buyer_id,)) as b_cur:
                b_req = await b_cur.fetchone()
                
            await db.commit()
            
            s_card, s_pias, s_ton = s_req if s_req else ("не указано", "не указано", "не указано")
            b_card, b_pias, b_ton = b_req if b_req else ("не указано", "не указано", "не указано")
            
            # ⚡ РАЗВЕТВЛЕНИЕ А: СДЕЛКА С ГАРАНТОМ
            if use_guarantor == 1:
                await bot.send_message(
                    chat_id=buyer_id,
                    text=f"🛡️ **Сделка #{deal_id} принята продавцом ЧЕРЕЗ ГАРАНТА!**\n"
                         f"💬 Анонимный чат открыт.\n\n"
                         f"⚠️ **ВАЖНО:** Пожалуйста, **НЕ ПЕРЕВОДИТЕ** средства продавцу напрямую!\n"
                         f"Дождитесь Гаранта. Из итоговой суммы обмена будет удержано **10% комиссии** сервиса."
                )
                
                await bot.send_message(
                    chat_id=seller_id,
                    text=f"🛡️ **Сделка #{deal_id} открыта ЧЕРЕЗ ГАРАНТА!**\n"
                         f"💬 Анонимный чат открыт.\n\n"
                         f"Ожидайте подключения Гаранта. Напоминаем, что выплата средств получателю производится за вычетом **10% комиссии** платформы."
                )

                # 🔔 ТЕПЕРЬ АЛЕРТ ОТПРАВЛЯЕТСЯ СТРОГО ЗДЕСЬ (ПОСЛЕ ПОДТВЕРЖДЕНИЯ ПРОДАВЦА):
                kb_admin = types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="⚡ Взять сделку как Гарант", callback_data=f"admin_claim_deal_{deal_id}")]
                ])
                
                # Извлекаем данные объявления для красивого алерта Гаранту
                async with aiosqlite.connect(DB_NAME) as db:
                    async with db.execute("SELECT direction, amount FROM offers WHERE id = ?", (offer_id,)) as o_cur:
                        o_res = await o_cur.fetchone()
                
                o_dir = o_res if o_res else "Неизвестно"
                o_amt = o_res if o_res else "Неизвестно"

                all_guarantor_ids = list(ADMIN_IDS)
                try:
                    async with aiosqlite.connect(DB_NAME) as db:
                        async with db.execute("SELECT tg_id FROM users WHERE user_status = 'guarantor_member'") as cursor:
                            rows = await cursor.fetchall()
                            for row in rows:
                                uid = row
                                if uid not in all_guarantor_ids:
                                    all_guarantor_ids.append(uid)
                except Exception as e:
                    print(f"[ОШИБКА СБОРА ГАРАНТОВ]: {e}")

                # Рассылаем уведомление Гарантам
                for receiver_id in all_guarantor_ids:
                    try:
                        await bot.send_message(
                            chat_id=receiver_id,
                            text=f"🚨 **Требуется Гарант для сделки #{deal_id}!**\n"
                                 f"Направление: `{o_dir}`\n"
                                 f"Сумма/Объем: `{o_amt}`",
                            reply_markup=kb_admin
                        )
                    except Exception:
                        continue

                
            # 🟢 РАЗВЕТВЛЕНИЕ Б: ОБЫЧНАЯ ПРЯМАЯ СДЕЛКА
            else:
                kb_buyer = types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="🟩 Я перевел средства", callback_data=f"deal_action_paid_{deal_id}")]
                ])
                
                await bot.send_message(
                    chat_id=buyer_id,
                    text=f"✅ Продавец подтвердил прямую сделку #{deal_id}!\n"
                         f"💬 **Анонимный чат открыт.**\n\n"
                         f"📋 **Реквизиты продавца для оплаты:**\n"
                         f"💳 Карты: `{s_card}`\n📱 Piastrix: `{s_pias}`\n💎 TON: `{s_ton}`\n\n"
                         f"⏳ Запущен **Таймер 2 (10 минут)** на оплату. После перевода нажмите кнопку ниже:",
                    reply_markup=kb_buyer
                )
                
                await bot.send_message(
                    chat_id=seller_id,
                    text=f"🤝 Вы подтвердили прямую сделку #{deal_id}.\n"
                         f"💬 **Анонимный чат открыт.**\n\n"
                         f"Реквизиты покупателя на случай встречной отправки:\n"
                         f"💳 Карты: `{b_card}` | 📱 Piastrix: `{b_pias}` | 💎 TON: `{b_ton}`\n\n"
                         f"Ожидайте, пока покупатель совершит перевод."
                )

        # --- Действие: Продавец отклонил сделку ---
        elif action == "reject" and user_id == seller_id and status == "waiting_seller":
            await db.execute("UPDATE deals SET status = 'cancelled' WHERE id = ?", (deal_id,))
            await db.execute("UPDATE offers SET status = 'active' WHERE id = ?", (offer_id,)) # Возвращаем ордер в стакан
            await db.commit()
            
            await callback.message.edit_text(f"❌ Вы отклонили сделку #{deal_id}. Объявление вернулось в общий список.")
            await bot.send_message(chat_id=buyer_id, text=f"❌ Продавец отклонил сделку #{deal_id}. Поищите другие варианты в стакане.")

        # --- Действие: Покупатель нажал "Я отправил" (Таймер 3) ---
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
                text=f"💰 Покупатель отметил сделку #{deal_id} как **ОПЛАЧЕННУЮ**.\n"
                     f"Пожалуйста, проверьте свой счет (Банк / Piastrix / TON).\n"
                     f"⏳ Запущен **Таймер 3 (10 минут)**. Если средства пришли, обязательно нажмите завершение:",
                reply_markup=kb_seller
            )
        # --- Действие: Успешное закрытие сделки Продавцом ---
        elif action == "completed" and user_id == seller_id and status == "waiting_delivery":
            await db.execute("UPDATE deals SET status = 'completed' WHERE id = ?", (deal_id,))
            await db.execute("UPDATE users SET deals_count = deals_count + 1 WHERE tg_id IN (?, ?)", (buyer_id, seller_id))
            await db.commit()
            
            # Генерируем ряды кнопок. Покупатель оценивает Продавца (seller_id), Продавец — Покупателя (buyer_id)
            kb_rate_seller = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text=f"⭐️ {i}", callback_data=f"rate_user_{seller_id}_{i}") for i in range(1, 6)]
            ])
            kb_rate_buyer = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text=f"⭐️ {i}", callback_data=f"rate_user_{buyer_id}_{i}") for i in range(1, 6)]
            ])
            
            # Обновляем сообщение Продавца
            await callback.message.edit_text(
                f"🎉 **Сделка #{deal_id} успешно завершена!**\n"
                f"Чат закрыт. Пожалуйста, оцените работу Покупателя от 1 до 5 звёзд:",
                reply_markup=kb_rate_buyer
            )
            # Отправляем сообщение Покупателю
            await bot.send_message(
                chat_id=buyer_id,
                text=f"🎉 **Сделка #{deal_id} успешно завершена!**\n"
                     f"Продавец подтвердил получение средств. Пожалуйста, оцените Продавца от 1 до 5 звёзд:",
                reply_markup=kb_rate_seller
            )

        # --- Действие: Открытие диспута вручную ---
        elif action == "dispute" and status == "waiting_delivery":
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(chat_id=admin_id, text=f"⚠️ **ВНИМАНИЕ! Открыт спор...")
                except Exception:
                    continue

        # --- Действие Гаранта: Ручное успешное завершение сделки ---
        elif action == "gcomplete":
            # (Тут остаётся ваша старая проверка res_g != user_id)
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute("SELECT guarantor_id FROM deals WHERE id = ?", (deal_id,)) as g_cur:
                    res_g = await g_cur.fetchone()
            
            if not res_g or res_g[0] != user_id:
                await callback.answer("⚠️ Вы не являетесь назначенным Гарантом этой сделки!", show_alert=True)
                return

            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("UPDATE deals SET status = 'completed' WHERE id = ?", (deal_id,))
                await db.execute("UPDATE users SET deals_count = deals_count + 1 WHERE tg_id IN (?, ?)", (buyer_id, seller_id))
                await db.commit()
            
            # Точно так же генерируем клавиатуры со звёздами для участников
            kb_rate_seller = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text=f"⭐️ {i}", callback_data=f"rate_user_{seller_id}_{i}") for i in range(1, 6)]
            ])
            kb_rate_buyer = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text=f"⭐️ {i}", callback_data=f"rate_user_{buyer_id}_{i}") for i in range(1, 6)]
            ])

            await callback.message.edit_text(f"✅ Вы успешно закрыли сделку #{deal_id} в качестве Гаранта.")
            
            await bot.send_message(
                chat_id=buyer_id,
                text=f"🎉 **Сделка #{deal_id} успешно завершена Гарантом!**\nПожалуйста, оцените работу Продавца от 1 до 5 звёзд:",
                reply_markup=kb_rate_seller
            )
            await bot.send_message(
                chat_id=seller_id,
                text=f"🎉 **Сделка #{deal_id} успешно завершена Гарантом!**\nПожалуйста, оцените работу Покупателя от 1 до 5 звёзд:",
                reply_markup=kb_rate_buyer
            )

        # --- Действие Гаранта: Ручная отмена сделки ---
        elif action == "gcancel":
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute("SELECT guarantor_id FROM deals WHERE id = ?", (deal_id,)) as g_cur:
                    res_g = await g_cur.fetchone()
            
            if not res_g or res_g[0] != user_id:
                await callback.answer("⚠️ Вы не являетесь назначенным Гарантом этой сделки!", show_alert=True)
                return

            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("UPDATE deals SET status = 'cancelled' WHERE id = ?", (deal_id,))
                await db.execute("UPDATE offers SET status = 'active' WHERE id = ?", (offer_id,))
                await db.commit()
            
            cancel_text = f"❌ **Сделка #{deal_id} ОТМЕНЕНА ГАРАНТОМ!**\nЗаявка вернулась в стакан, средства подлежат возврату."
            await callback.message.edit_text(f"❌ Вы отменили сделку #{deal_id}.")
            await bot.send_message(chat_id=buyer_id, text=cancel_text)
            await bot.send_message(chat_id=seller_id, text=cancel_text)

                    
# --- ВХОД АДМИНИСТРАТОРА ИЛИ ГАРАНТА КОМЬЮНИТИ В СДЕЛКУ ---
@router.callback_query(F.data.startswith("admin_claim_deal_"))
async def admin_claim_deal(callback: types.CallbackQuery, bot: Bot):
    await callback.answer()
    
    user_id = callback.from_user.id
    deal_id = int(callback.data.split("_")[3]) # Четкий парсинг ID сделки из callback
    
    # 🛡️ ЗАЩИТА 1: Проверяем, не занята ли сделка другим гарантом
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

    # 🛡️ ЗАЩИТА 2: Проверяем права доступа (Либо в ADMIN_IDS, либо роль guarantor_member в БД)
    is_allowed = user_id in ADMIN_IDS
    if not is_allowed:
        is_allowed = await is_user_guarantor(user_id)
        
    if not is_allowed:
        await callback.answer("⚠️ У вас нет прав Гаранта для модерации этой сделки!", show_alert=True)
        return
        
    # ЕСЛИ СДЕЛКА СВОБОДНА И ДОСТУП ПРОВЕРЕН — БРОНИРУЕМ ЕЁ ЗА СОБОЙ
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
        
    # Создаем пульт управления для Гаранта
    kb_admin_control = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🎉 Закрыть (Выпустить средства)", callback_data=f"deal_action_gcomplete_{deal_id}")],
        [types.InlineKeyboardButton(text="❌ Отменить (Вернуть средства)", callback_data=f"deal_action_gcancel_{deal_id}")]
    ])
        
    await callback.message.edit_text(
        f"✅ Вы вошли в сделку #{deal_id} как официальный Гарант.\n"
        f"💬 Напишите свои реквизиты в анонимный чат для депонирования.\n\n"
        f"📋 **ДАННЫЕ ДЛЯ ПРОВЕРКИ ЧЕКОВ:**\n\n"
        f"👤 Покупатель (ID: `{buyer_id}`):\n• Карты: `{b_card}`\n• Piastrix: `{b_pias}`\n• TON: `{b_ton}`\n\n"
        f"👤 Продавец (ID: `{seller_id}`):\n• Карты: `{s_card}`\n• Piastrix: `{s_pias}`\n• TON: `{s_ton}`\n\n"
        f"Используйте кнопки ниже для ручного закрытия или отмены обмена:",
        reply_markup=kb_admin_control,
        parse_mode="Markdown"
    )
    
    kb_buyer = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🟩 Я перевел средства Гаранту", callback_data=f"deal_action_paid_{deal_id}")]
    ])
    
    await bot.send_message(chat_id=buyer_id, text="⚡ **Гарант подключился к сделке!** Ожидайте реквизиты в анонимном чате.", reply_markup=kb_buyer)
    await bot.send_message(chat_id=seller_id, text="⚡ **Гарант подключился к сделке!** Ожидайте депонирования.")

    
# --- БЕЗОПАСНЫЙ АНОНИМНЫЙ ЧАТ (РЕТРАНСЛЯТОР С МАСКИРОВКОЙ ТЕКСТА И ФОТО) ---
# Меняем фильтр в декораторе: теперь ловим и текст (F.text), и фотографии (F.photo)
@router.message((F.text | F.photo) & ~F.text.startswith("/"))
async def anonymous_chat_relay(message: types.Message, bot: Bot, state: FSMContext = None):
    sender_id = message.from_user.id
    
    # ⚡ ЗАЩИТА ЛК: Если пользователь сейчас вводит карту или кошелек,
    # мы мгновенно выходим и даем сработать хэндлерам Личного Кабинета!
    if state is not None:
        current_state = await state.get_state()
        if current_state and "waiting_for_" in current_state:
            return
            
    async with aiosqlite.connect(DB_NAME) as db:
        # Ищем активную сделку, где участвует этот пользователь
        query = """
            SELECT id, buyer_id, seller_id, guarantor_id, status FROM deals 
            WHERE (buyer_id = ? OR seller_id = ? OR guarantor_id = ?) 
            AND status IN ('waiting_payment', 'waiting_delivery', 'dispute')
        """
        async with db.execute(query, (sender_id, sender_id, sender_id)) as cursor:
            active_deal = await cursor.fetchone()
            
    if not active_deal:
        return # Если у пользователя нет активной сделки — просто игнорируем

    deal_id, buyer_id, seller_id, guarantor_id, status = active_deal
    
    # Достаем анонимные никнеймы участников из базы данных для подстановки
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT tg_id, nickname FROM users WHERE tg_id IN (?, ?)", (buyer_id, seller_id)) as cursor:
            users_nicks = await cursor.fetchall()
            
    nicks_dict = {uid: name for uid, name in users_nicks}
    
    # Определяем, кто пишет, и формируем защищенный префикс
    if sender_id == guarantor_id:
        # Если ID гаранта сделки находится в ADMIN_IDS — это Главный Админ, иначе — Гарант
        if sender_id in ADMIN_IDS:
            prefix = f"⚡ **[ГАРАНТ (Admin)]**"
        else:
            prefix = f"🛡️ **[ГАРАНТ (Guarantor)]**"
    elif sender_id == buyer_id:
        prefix = f"👤 **[{nicks_dict.get(buyer_id, 'Покупатель')}]**"
    elif sender_id == seller_id:
        prefix = f"👤 **[{nicks_dict.get(seller_id, 'Продавец')}]**"
    else:
        return

    # Формируем список получателей (отправляем всем, кроме самого себя)
    targets = [buyer_id, seller_id]
    if guarantor_id:
        targets.append(guarantor_id)
        
    for target_id in targets:
        if target_id and target_id != sender_id:
            try:
                # 📸 ВЕТКА А: Пользователь отправил КАРТИНКУ (ЧЕК)
                if message.photo:
                    # Берем самое лучшее качество фото (последний элемент в списке)
                    photo_id = message.photo[-1].file_id
                    # Текст подписи под фото (если пользователь что-то написал вместе с фото, добавляем это)
                    user_caption = f"\n📝 {message.caption}" if message.caption else ""
                    full_caption = f"{prefix} отправил фото:{user_caption}"
                    
                    await bot.send_photo(
                        chat_id=target_id, 
                        photo=photo_id, 
                        caption=full_caption, 
                        parse_mode="Markdown"
                    )
                
                # 💬 ВЕТКА Б: Пользователь отправил ОБЫЧНЫЙ ТЕКСТ
                elif message.text:
                    full_message_text = f"{prefix}: {message.text}"
                    await bot.send_message(
                        chat_id=target_id, 
                        text=full_message_text, 
                        parse_mode="Markdown"
                    )
            except Exception as e:
                print(f"[ОШИБКА РЕТРАНСЛЯЦИИ ЧАТА СДЕЛКИ #{deal_id}]: {e}")
                continue

# --- ХЭНДЛЕР НАЧИСЛЕНИЯ ОЦЕНОК И ПЕРЕРАСЧЕТА СРЕДНЕГО РЕЙТИНГА ---
@router.callback_query(F.data.startswith("rate_user_"))
async def process_user_rating(callback: types.CallbackQuery):
    await callback.answer()
    
    # Разбираем callback_data (формат: rate_user_[target_id]_[stars])
    parts = callback.data.split("_")
    target_id = int(parts[2])
    stars = int(parts[3])
    
    async with aiosqlite.connect(DB_NAME) as db:
        # 1. Извлекаем текущую сумму звезд и количество оценок контрагента
        async with db.execute("SELECT rating_sum, rating_count FROM users WHERE tg_id = ?", (target_id,)) as cursor:
            res = await cursor.fetchone()
            
        if not res:
            await callback.message.edit_text("⚠️ Ошибка: Пользователь не найден в базе данных.")
            return
            
        current_sum, current_count = res
        
        # 2. Точный математический перерасчет: добавляем новую оценку к общей сумме
        new_sum = current_sum + stars
        new_count = current_count + 1
        new_rating = round(float(new_sum) / float(new_count), 2)
        
        # 3. Записываем новые значения в профиль пользователя
        await db.execute(
            "UPDATE users SET rating_sum = ?, rating_count = ?, rating = ? WHERE tg_id = ?", 
            (new_sum, new_count, new_rating, target_id)
        )
        await db.commit()
        
    # Схлопываем клавиатуру звезд, чтобы защитить от повторного нажатия
    await callback.message.edit_text(f"✅ Спасибо! Вы успешно выставили оценку контрагенту: **⭐️ {stars}**.")
