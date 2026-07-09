import time
import aiosqlite
from aiogram import Router, F, types, Bot
from config import ADMIN_IDS, ADMIN_CHAT_ID
from database import DB_NAME
from constants import DIRECTION_TITLES, DEAL_STATUS_NAMES

router = Router()

async def send_deal_interface_to_user(bot: Bot, target_id: int, deal_id: int, status: str, buyer_id: int, seller_id: int, guarantor_id: int, edit_message_obj=None):
    """
    Централизованная функция генерации интерфейсов сделки.
    Автоматически подтягивает нужные реквизиты под направление обмена.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        # Извлекаем подробности лота
        query = """
            SELECT offers.direction, offers.amount, offers.rate, users.nickname 
            FROM deals
            JOIN offers ON deals.offer_id = offers.id
            JOIN users ON offers.creator_id = users.tg_id
            WHERE deals.id = ?
        """
        async with db.execute(query, (deal_id,)) as cursor:
            res = await cursor.fetchone()
            
    if not res:
        return
        
    direction, amount, rate, creator_nick = res
    dir_title = DIRECTION_TITLES.get(direction, direction)
    status_text = DEAL_STATUS_NAMES.get(status, status)
    
    # Базовая карточка сделки для вывода на экран
    base_text = (
        f"🤝 **Управление сделкой #{deal_id}**\n"
        f"🔄 Направление: `{dir_title}`\n"
        f"💰 Объем/Сумма: `{amount}`\n"
        f"📊 Условия/Курс: `{rate}`\n"
        f"---------------------------\n"
        f"📌 Текущий шаг: _{status_text}_\n\n"
    )
    
    kb_list = []
    final_text = base_text
    
    # --- СЦЕНАРИЙ ДЛЯ ПРОДАВЦА КРИПТЫ ---
    if target_id == seller_id:
        if status == "waiting_deposit":
            final_text += (
                "⚠️ **ВАШ ШАГ!** Для запуска обмена вам необходимо депонировать (заморозить) активы.\n\n"
                "Переведите указанный объем на официальный кошелек платформы/Гаранта и после успешной транзакции нажмите кнопку ниже.\n"
                "❌ **Внимание:** Покупатель не увидит реквизиты вашей карты, пока Гарант не подтвердит ваш депозит!"
            )
            kb_list.append([types.InlineKeyboardButton(text="💎 Я перевел депозит Гаранту", callback_data=f"deal_action_deposited_{deal_id}")])
            
        elif status == "waiting_payment":
            final_text += (
                "⏳ Гарант подтвердил ваш крипто-депозит!\n\n"
                "Ожидайте, пока Покупатель совершит прямой перевод фиата (рублей) на вашу Карту.\n"
                "Вы получите уведомление, как только он отметит сделку оплаченной. Анонимный чат активен."
            )
            kb_list.append([types.InlineKeyboardButton(text="💬 Анонимный чат активен (Пишите в бот)", callback_data="dummy")])
            
    # --- СЦЕНАРИЙ ДЛЯ ПОКУПАТЕЛЯ КРИПТЫ ---
    elif target_id == buyer_id:
        if status == "waiting_deposit":
            final_text += (
                "⏳ Ожидаем, пока Продавец внесет криптовалютный депозит Гаранту системы.\n\n"
                "Пожалуйста, ничего не переводите! Как только Гарант зафиксирует монеты на безопасном балансе, бот выдаст вам реквизиты для оплаты. Чат пока закрыт."
            )
            kb_list.append([types.InlineKeyboardButton(text="⏳ Ожидание депозита...", callback_data="dummy")])
            
        elif status == "waiting_payment":
            # ИСПРАВЛЕНО: Вытягиваем реквизиты Продавца и Покупателя для наглядности
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute("SELECT card FROM requisites WHERE tg_id = ?", (seller_id,)) as r_cursor:
                    s_req = await r_cursor.fetchone()
                # Вытягиваем целевую колонку Покупателя для вывода (чтобы он видел, куда ему зачислят крипту)
                async with db.execute("SELECT crypto_bot, bybit, other_wallets, fkwallet FROM requisites WHERE tg_id = ?", (buyer_id,)) as b_cursor:
                    b_req = await b_cursor.fetchone()
                    
            s_card = s_req[0] if s_req and s_req[0] else "не указано"
            c_bot, bybit, other, fk = b_req if b_req else ("", "", "", "")
            
            # Определяем, какие именно реквизиты получения крипты отобразить Покупателю для сверки
            target_wallet = "не заполнено"
            if direction == "crypto_bot": target_wallet = f"🤖 Crypto Bot: `{c_bot}`"
            elif direction == "bybit": target_wallet = f"📈 Bybit UID/Wallet: `{bybit}`"
            elif direction == "other_wallets": target_wallet = f"🌐 Внешний кошелек: `{other}`"
            elif direction == "fkwallet": target_wallet = f"👛 FkWallet: `{fk}`"
            
            final_text += (
                f"✅ **КРИПТА ЗАМОРОЖЕНА ГАРАНТОМ! ВАШ ШАГ!**\n\n"
                f"Пожалуйста, совершите прямой фиатный перевод со своей карты напрямую Продавцу по указанным реквизитам:\n"
                f"💳 **Банковская карта Продавца:** `{s_card}`\n\n"
                f"📋 **Куда вам будут зачислены монеты (для сверки):**\n"
                f"{target_wallet}\n\n"
                f"⚠️ **ВАЖНО:** Переводите рубли СТРОГО по указанной карте. Если контрагент просит другую карту в чате — это мошенник! После перевода нажмите кнопку ниже:"
            )
            kb_list.append([types.InlineKeyboardButton(text="🟢 Я оплатил на Карту Продавца", callback_data=f"deal_action_paid_{deal_id}")])

    # Пуленепробиваемый рендеринг без падений при любых типах объектов aiogram
    reply_markup = types.InlineKeyboardMarkup(inline_keyboard=kb_list)
    if edit_message_obj:
        try:
            if isinstance(edit_message_obj, types.CallbackQuery):
                await edit_message_obj.message.edit_text(final_text, reply_markup=reply_markup, parse_mode="Markdown")
            elif isinstance(edit_message_obj, types.Message) and edit_message_obj.from_user.id == bot.id:
                await edit_message_obj.edit_text(final_text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await bot.send_message(chat_id=target_id, text=final_text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            await bot.send_message(chat_id=target_id, text=final_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await bot.send_message(chat_id=target_id, text=final_text, reply_markup=reply_markup, parse_mode="Markdown")
@router.callback_query(F.data.startswith("deal_action_"))
async def handle_deal_actions(callback: types.CallbackQuery, bot: Bot):
    """Глобальный диспетчер действий покупателя и продавца внутри сделки"""
    await callback.answer()
    
    # Разбираем callback_data формата: deal_action_[action]_[deal_id]
    parts = callback.data.split("_")
    action = parts[2]     # 'deposited', 'paid', 'completed', 'dispute'
    deal_id = int(parts[3]) # ID сделки всегда лежит в конце
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        query = "SELECT buyer_id, seller_id, status, guarantor_id, offer_id FROM deals WHERE id = ?"
        async with db.execute(query, (deal_id,)) as cursor:
            deal = await cursor.fetchone()
            
    if not deal:
        return
        
    buyer_id, seller_id, status, guarantor_id, offer_id = deal

    # --- ДЕЙСТВИЕ 1: Продавец нажал "Я депонировал крипту" ---
    if action == "deposited" and user_id == seller_id and status == "waiting_deposit":
        async with aiosqlite.connect(DB_NAME) as db:
            query_offer = "SELECT direction, amount FROM offers WHERE id = ?"
            async with db.execute(query_offer, (offer_id,)) as o_cur:
                o_res = await o_cur.fetchone()
                
        from constants import DIRECTION_TITLES
        raw_dir = o_res[0] if o_res else "Неизвестно"
        dir_text_title = DIRECTION_TITLES.get(raw_dir, raw_dir)
        amount_val = o_res[1] if o_res else "Неизвестно"
        
        # Информируем Продавца о запуске проверки
        await callback.message.edit_text(
            f"📥 **Заявка на верификацию депозита отправлена!**\n\n"
            f"Сделка #{deal_id} ожидает проверки Гарантом.\n"
            f"Пожалуйста, приготовьте хэш транзакции или скриншот отправки крипты. Как только Гарант подтвердит баланс, сделка автоматически перейдет на этап оплаты.",
            parse_mode="Markdown"
        )
        
        # Уведомляем Покупателя, что Продавец подал заявку на депозит
        try:
            await bot.send_message(
                chat_id=buyer_id,
                text=f"📥 **Продавец заявил о переводе депозита по сделке #{deal_id}!**\n\n"
                     f"Ожидаем, пока официальный Гарант проверит и подтвердит поступление монет на безопасный кошелек платформы."
            )
        except Exception:
            pass
        
        # Кнопка для команды Гарантов
        kb_admin = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="⚡ Взять сделку как Гарант", callback_data=f"admin_claim_deal_{deal_id}")]
        ])
        
        # Собираем красивую информационную карточку с ЧЕТКИМ направлением для Гаранта
        alert_g_text = (
            f"📥 **[ЗАЯВКА НА ДЕПОЗИТ] Сделка #{deal_id}**\n\n"
            f"🧭 **Четкое направление:** `{dir_text_title}`\n"
            f"💰 **Объем / Сумма:** `{amount_val}`\n"
            f"👤 **Продавец крипты:** [Трейдер](tg://user?id={seller_id}) (ID: `{seller_id}`)\n"
            f"👥 **Покупатель фиата:** [Трейдер](tg://user?id={buyer_id}) (ID: `{buyer_id}`)\n\n"
            f"Нажмите кнопку ниже, чтобы зайти в анонимный чат, выдать реквизиты кошелька системы и подтвердить поступление активов."
        )
        
        # Отправляем алерт в общий чат администраторов
        if ADMIN_CHAT_ID != 0:
            try: await bot.send_message(chat_id=ADMIN_CHAT_ID, text=alert_g_text, reply_markup=kb_admin, parse_mode="Markdown")
            except: pass
        else:
            # Если общий чат не настроен, спамим всем админам в ЛС
            all_guarantor_ids = list(ADMIN_IDS)
            try:
                async with aiosqlite.connect(DB_NAME) as db:
                    async with db.execute("SELECT tg_id FROM users WHERE user_status IN ('guarantor_member', 'guarantor')") as g_cursor:
                        rows = await g_cursor.fetchall()
                        for row in rows:
                            if row[0] not in all_guarantor_ids:
                                all_guarantor_ids.append(row[0])
            except: pass
            
            for receiver_id in all_guarantor_ids:
                try: await bot.send_message(chat_id=receiver_id, text=alert_g_text, reply_markup=kb_admin, parse_mode="Markdown")
                except: continue
        return
    # --- ДЕЙСТВИЕ 2: Покупатель отметил сделку как "ОПЛАЧЕННУЮ" на карту ---
    elif action == "paid" and user_id == buyer_id and status == "waiting_payment":
        current_time = str(int(time.time()))
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE deals SET status = 'waiting_delivery', timer_start = ? WHERE id = ?", (current_time, deal_id))
            await db.commit()
            
        await callback.message.edit_text(
            "💸 **Вы подтвердили отправку фиатных средств Продавцу!**\n\n"
            "Таймер ожидания оплаты успешно остановлен. Теперь Продавец проверяет свой банковский счет.\n"
            "💬 Анонимный чат активен. Вы можете отправить чек/скриншот перевода для ускорения проверки контрагентом.",
            parse_mode="Markdown"
        )
        
        # Генерируем пульт управления для Продавца
        kb_seller = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="✅ Рубли на карте (Выпустить крипту)", callback_data=f"deal_action_completed_{deal_id}")],
            [types.InlineKeyboardButton(text="⚠️ Я не получил деньги (Спор / Диспут)", callback_data=f"deal_action_dispute_{deal_id}")]
        ])
        
        await bot.send_message(
            chat_id=seller_id,
            text=f"💰 **Покупатель отметил сделку #{deal_id} как ОПЛАЧЕННУЮ!**\n\n"
                 f"Пожалуйста, зайдите в свой мобильный банк и проверьте поступление средств.\n"
                 f"⚠️ **ВНИМАНИЕ:** Нажимайте верхнюю кнопку только тогда, когда ЛИЧНО увидите баланс на карте! Не верьте скриншотам в чате без проверки банка.",
            reply_markup=kb_seller,
            parse_mode="Markdown"
        )
        return

    # --- ДЕЙСТВИЕ 3: Успешное закрытие сделки Продавцом (Выпуск крипты) ---
    elif action == "completed" and user_id == seller_id and status == "waiting_delivery":
        async with aiosqlite.connect(DB_NAME) as db:
            # Защита от Double-Spend (повторного клика в условиях сетевых задержек)
            async with db.execute("SELECT status FROM deals WHERE id = ?", (deal_id,)) as check_cur:
                res_status = await check_cur.fetchone()
                if res_status and res_status[0] == "completed":
                    return
                    
            await db.execute("UPDATE deals SET status = 'completed' WHERE id = ?", (deal_id,))
            await db.execute("UPDATE users SET deals_count = deals_count + 1 WHERE tg_id = ?", (buyer_id,))
            await db.execute("UPDATE users SET deals_count = deals_count + 1 WHERE tg_id = ?", (seller_id,))
            await db.commit()
            
        import rating
        # Высылаем клавиатуры геймификации и рейтинга из rating.py обоим участникам
        kb_rate_buyer = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=f"⭐ {i}", callback_data=f"rate_user_{buyer_id}_{i}") for i in range(1, 6)],
            [types.InlineKeyboardButton(text="🏠 В главное меню", callback_data="open_main_menu")]
        ])
        kb_rate_seller = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=f"⭐ {i}", callback_data=f"rate_user_{seller_id}_{i}") for i in range(1, 6)],
            [types.InlineKeyboardButton(text="🏠 В главное меню", callback_data="open_main_menu")]
        ])
        
        await callback.message.edit_text(
            f"🎉 **Сделка #{deal_id} успешно завершена!**\n"
            f"Вы подтвердили получение фиата, криптовалютный депозит отправлен Покупателю.\n"
            f"Анонимный чат закрыт. Пожалуйста, оцените Покупателя:",
            reply_markup=kb_rate_buyer,
            parse_mode="Markdown"
        )
        
        await bot.send_message(
            chat_id=buyer_id,
            text=f"🎉 **Сделка #{deal_id} успешно завершена!**\n"
                 f"Продавец подтвердил получение рублей и выпустил криптовалюту на ваши реквизиты.\n"
                 f"Анонимный чат закрыт. Пожалуйста, оцените Продавца:",
            reply_markup=kb_rate_seller,
            parse_mode="Markdown"
        )
        return

    # --- ДЕЙСТВИЕ 4: Открытие Диспута (Арбитраж Гаранта) ---
    elif action == "dispute" and status == "waiting_delivery":
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE deals SET status = 'dispute' WHERE id = ?", (deal_id,))
            await db.commit()
            
        dispute_msg = (
            "⚠️ **ОТКРЫТ ОФИЦИАЛЬНЫЙ СПОР ПО СДЕЛКЕ!**\n\n"
            "Все таймеры автоотмены заморожены. В анонимный чат вызывается Администратор-Гарант для проведения арбитража.\n"
            "Пожалуйста, ожидайте. Покупатель должен отправить чек, а Продавец — выписку по карте прямо сюда, в анонимный чат."
        )
        
        await callback.message.edit_text(dispute_msg, parse_mode="Markdown")
        await bot.send_message(chat_id=buyer_id, text=dispute_msg, parse_mode="Markdown")
        
        # Формируем экстренный алерт для Гарантов с четким направлением
        from constants import DIRECTION_TITLES
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT direction, amount FROM offers WHERE id = ?", (offer_id,)) as o_cur:
                o_res = await o_cur.fetchone()
                
        raw_dir = o_res[0] if o_res else "Неизвестно"
        dir_text_title = DIRECTION_TITLES.get(raw_dir, raw_dir)
        amount_val = o_res[1] if o_res else "Неизвестно"
        
        alert_d_text = (
            f"🚨 **[КРИТИЧЕСКИЙ ДИСПУТ] Сделка #{deal_id}**\n\n"
            f"🧭 **Направление сделки:** `{dir_text_title}`\n"
            f"💰 **Объем / Сумма:** `{amount_val}`\n"
            f"⚠️ Требуется немедленное вмешательство Арбитра для проверки выписок и чеков перевода!"
        )
        
        kb_admin = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="⚖️ Войти в спор как Арбитр", callback_data=f"admin_claim_deal_{deal_id}")]
        ])
        
        if ADMIN_CHAT_ID != 0:
            try: await bot.send_message(chat_id=ADMIN_CHAT_ID, text=alert_d_text, reply_markup=kb_admin, parse_mode="Markdown")
            except: pass
        else:
            all_guarantor_ids = list(ADMIN_IDS)
            for g_id in all_guarantor_ids:
                try: await bot.send_message(chat_id=g_id, text=alert_d_text, reply_markup=kb_admin, parse_mode="Markdown")
                except: continue
        return
