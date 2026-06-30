import aiosqlite
import time
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from config import ADMIN_IDS
from database import DB_NAME, has_active_deal, has_required_requisites

router = Router()

# --- ИНИЦИАЦИЯ СДЕЛКИ ИЗ СТАКАНА (ТАЙМЕР 1) ---
@router.callback_query(F.data.startswith("deal_open_"))
async def process_deal_opening(callback: types.CallbackQuery, bot: Bot):
    buyer_id = callback.from_user.id
    
    # Администраторам строго запрещено торговать во избежание конфликта интересов
    if buyer_id in ADMIN_IDS:
        await callback.answer("⚠️ Администраторам запрещено принимать p2p-сделки.", show_alert=True)
        return

    parts = callback.data.split("_")
    mode = parts[2]     # 'direct' или 'guarantor'
    offer_id = int(parts[3])
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT direction, amount, rate, creator_id FROM offers WHERE id = ?", (offer_id,)) as cursor:
            offer = await cursor.fetchone()
            
    if not offer:
        await callback.answer("❌ Объявление не найдено или уже удалено.", show_alert=True)
        return
        
    seller_id, direction, amount, rate = offer[3], offer[0], offer[1], offer[2]

    # Проверяем, заполнил ли покупатель реквизиты под это направление
    if not await has_required_requisites(buyer_id, direction):
        await callback.answer("⚠️ Вы не можете принять сделку, пока сами не заполните свои реквизиты для этого направления в ЛК.", show_alert=True)
        return

    # Защита от параллельных сделок-флуда
    if await has_active_deal(buyer_id):
        await callback.answer("⚠️ У вас уже есть активная сделка! Завершите её перед открытием новой.", show_alert=True)
        return
        
    current_time = str(int(time.time()))
    use_guarantor = 1 if mode == "guarantor" else 0
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE offers SET status = 'closed' WHERE id = ?", (offer_id,))
        cursor = await db.execute(
            "INSERT INTO deals (offer_id, buyer_id, seller_id, status, use_guarantor, timer_start) VALUES (?, ?, ?, 'waiting_seller', ?, ?)",
            (offer_id, buyer_id, seller_id, use_guarantor, current_time)
        )
        deal_id = cursor.lastrowid
        await db.commit()
        
    await callback.message.edit_text(f"🤝 Вы отправили запрос на открытие сделки #{deal_id}. Ожидаем подтверждения продавца.")
    
    kb_seller = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="👍 Принять сделку", callback_data=f"deal_action_accept_{deal_id}"),
            types.InlineKeyboardButton(text="👎 Отклонить", callback_data=f"deal_action_reject_{deal_id}")
        ]
    ])
    
    guarantor_marker = "🛡️ С ГАРАНТОМ" if use_guarantor else "🟩 ПРЯМАЯ"
    
    await bot.send_message(
        chat_id=seller_id,
        text=f"🔔 **Новый запрос на P2P-обмен (#{deal_id})!**\n\n"
             f"📊 Тип сделки: **{guarantor_marker}**\n"
             f"🔄 Направление: `{direction}`\n"
             f"💰 Объем: `{amount}`\n"
             f"📈 Курс/Условия: `{rate}`\n\n"
             f"⏳ У вас есть **10 минут (Таймер 1)**, чтобы принять или отклонить запрос:",
        reply_markup=kb_seller
    )
    
    fee_text = "\n\n⚠️ **Обратите внимание:** Вы выбрали безопасную сделку. Комиссия Гаранта составит **10%** от суммы обмена." if use_guarantor else ""
    
    await callback.message.edit_text(
        f"⏳ **Сделка #{deal_id} инициирована!**\n"
        f"Запущен **Таймер 1 (10 минут)**. Ожидаем, пока Продавец примет или отклонит ваш запрос...{fee_text}",
        parse_mode="Markdown"
    )



# --- ПУЛЕНЕПРОБИВАЕМЫЙ АНОНИМНЫЙ ЧАТ (ЗАЩИТА ОТ ИНЪЕКЦИЙ И DOS БЛОКИРОВОК) ---
@router.message((F.text | F.photo) & ~F.text.startswith("/"))
async def anonymous_chat_relay(message: types.Message, bot: Bot, state: FSMContext = None):
    sender_id = message.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        query = """
            SELECT id, buyer_id, seller_id, guarantor_id, status FROM deals 
            WHERE (buyer_id = ? OR seller_id = ? OR guarantor_id = ?) 
            AND status IN ('waiting_payment', 'waiting_delivery', 'dispute')
        """
        async with db.execute(query, (sender_id, sender_id, sender_id)) as cursor:
            active_deal = await cursor.fetchone()
            
    if not active_deal:
        return

    # 🛡️ ЗАЩИТА ОТ FSM DoS: Если пользователь находится внутри сделки и пишет текст —
    # мы принудительно сбрасываем его стейты ЛК, чтобы чат никогда не замораживался
    if state is not None:
        await state.clear()

    deal_id, buyer_id, seller_id, guarantor_id, status = active_deal
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT tg_id, nickname FROM users WHERE tg_id IN (?, ?)", (buyer_id, seller_id)) as cursor:
            users_nicks = await cursor.fetchall()
            
    nicks_dict = {uid: name for uid, name in users_nicks}
    
    if sender_id == guarantor_id:
        prefix = f"⚡ **[ГАРАНТ (Admin)]**" if sender_id in ADMIN_IDS else f"🛡️ **[ГАРАНТ (Community)]**"
    elif sender_id == buyer_id:
        prefix = f"👤 **[{nicks_dict.get(buyer_id, 'Покупатель')}]**"
    elif sender_id == seller_id:
        prefix = f"👤 **[{nicks_dict.get(seller_id, 'Продавец')}]**"
    else:
        return

    targets = [buyer_id, seller_id]
    if guarantor_id:
        targets.append(guarantor_id)
        
    for target_id in targets:
        if target_id and target_id != sender_id:
            try:
                if message.photo:
                    photo_id = message.photo[-1].file_id
                    # Экран caption от HTML инъекций
                    user_caption = f"\n{message.caption.replace('<', '&lt;').replace('>', '&gt;')}" if message.caption else ""
                    await bot.send_photo(chat_id=target_id, photo=photo_id, caption=f"{prefix} отправил фото:{user_caption}", parse_mode="HTML")
                elif message.text:
                    # 🛡️ ЗАЩИТА ОТ HTML-ИНЪЕКЦИЙ: Экранируем теги, которые шлет юзер текстом
                    clean_text = message.text.replace("<", "&lt;").replace(">", "&gt;")
                    await bot.send_message(chat_id=target_id, text=f"{prefix}: {clean_text}", parse_mode="HTML")
            except Exception:
                continue
