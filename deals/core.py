import aiosqlite
import time
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext

from config import ADMIN_IDS
from database import DB_NAME, has_active_deal, has_required_requisites
from constants import DIRECTION_TITLES

router = Router()

@router.callback_query(F.data.startswith("deal_open_init_"))
async def process_deal_opening(callback: types.CallbackQuery, bot: Bot):
    """Инициализация асинхронной сделки из торгового стакана"""
    buyer_id = callback.from_user.id
    
    # Администраторам строго запрещено торговать во избежание конфликта интересов
    if buyer_id in ADMIN_IDS:
        await callback.answer("⚠️ Администраторам запрещено принимать P2P-сделки.", show_alert=True)
        return
        
    parts = callback.data.split("_")
    offer_id = int(parts[-1]) # Забираем ID лота
    
    async with aiosqlite.connect(DB_NAME) as db:
        query = "SELECT creator_id, direction, offer_type, amount, rate FROM offers WHERE id = ?"
        async with db.execute(query, (offer_id,)) as cursor:
            offer = await cursor.fetchone()
            
    if not offer:
        await callback.answer("❌ Объявление не найдено или уже удалено.", show_alert=True)
        return
        
    creator_id, direction, offer_type, amount, rate = offer
    
    # Определяем роли в будущей сделке
    # Если лот в стакане типа 'sell' (создатель продает крипту), то Покупатель — это тот, кто кликнул (buyer_id)
    if offer_type == "sell":
        seller_id = creator_id
        buyer_id_final = buyer_id
    else:
        # Если лот типа 'buy' (создатель хочет купить крипту), то Покупатель — это создатель,
        # а Продавец крипты — тот, кто кликнул по кнопке
        seller_id = buyer_id
        buyer_id_final = creator_id
        
    # Проверяем, заполнил ли ПОКУПАТЕЛЬ реквизиты для получения крипты,
    # а ПРОДАВЕЦ — реквизиты Карты для получения фиата
    if not await has_required_requisites(creator_id, direction, offer_type) or \
       not await has_required_requisites(buyer_id, direction, offer_type):
        await callback.answer("⚠️ Сделка не может быть открыта. У одного из участников не заполнены обязательные реквизиты для этого направления в ЛК!", show_alert=True)
        return
        
    # Защита от параллельных сделок-флуда (Race Condition)
    if await has_active_deal(buyer_id_final) or await has_active_deal(seller_id):
        await callback.answer("⚠️ Вы или ваш контрагент уже находитесь в активной сделке! Завершите её перед открытием новой.", show_alert=True)
        return
        
    current_time = str(int(time.time()))
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Сразу закрываем лот в стакане, чтобы его никто не перехватил одновременно
        await db.execute("UPDATE offers SET status = 'closed' WHERE id = ?", (offer_id,))
        
        # Создаем сделку СРАЗУ в статусе 'waiting_deposit'
        cursor = await db.execute(
            "INSERT INTO deals (offer_id, buyer_id, seller_id, status, use_guarantor, timer_start) VALUES (?, ?, ?, 'waiting_deposit', 1, ?)",
            (offer_id, buyer_id_final, seller_id, current_time)
        )
        deal_id = cursor.lastrowid
        await db.commit()
        
    dir_title = DIRECTION_TITLES.get(direction, direction)
    
    # Импортируем функцию рендеринга интерфейсов, которую мы пропишем в actions.py
    from actions import send_deal_interface_to_user
    
    # Отправляем интерфейсы шага депонирования обоим участникам
    await send_deal_interface_to_user(bot, seller_id, deal_id, "waiting_deposit", buyer_id_final, seller_id, None)
    await send_deal_interface_to_user(bot, buyer_id_final, deal_id, "waiting_deposit", buyer_id_final, seller_id, None)
    
    # Стираем стакан у того, кто нажал кнопку, чтобы обновить экран
    try: await callback.message.delete()
    except: pass
# --- ПУЛЕНЕПРОБИВАЕМЫЙ АНОНИМНЫЙ ЧАТ (ЗАЩИТА ОТ ИНЪЕКЦИЙ И DOS БЛОКИРОВОК) ---
@router.message((F.text | F.photo) & ~F.text.startswith("/"))
async def anonymous_chat_relay(message: types.Message, bot: Bot, state: FSMContext = None):
    sender_id = message.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Ищем сделку, к которой привязан пользователь в любой роли
        query = """
        SELECT id, buyer_id, seller_id, guarantor_id, status FROM deals 
        WHERE (buyer_id = ? OR seller_id = ? OR guarantor_id = ?) 
        AND status IN ('waiting_deposit', 'waiting_payment', 'waiting_delivery', 'dispute')
        """
        async with db.execute(query, (sender_id, sender_id, sender_id)) as cursor:
            active_deal = await cursor.fetchone()
            
    if not active_deal:
        return
        
    deal_id, buyer_id, seller_id, guarantor_id, status = active_deal

    # ЗАЩИТА: Если сделка на этапе депозита, общение в чате полностью ЗАПРЕЩЕНО
    if status == "waiting_deposit":
        # Если пишет Гарант/Админ, ему можно. Обычным пользователям — нет.
        if sender_id != guarantor_id and sender_id not in ADMIN_IDS:
            await message.answer("🔒 **Чат заблокирован.**\nВы сможете общаться с контрагентом только после того, как Продавец внесет криптовалютный депозит и Гарант подтвердит его получение.")
            return

    # ЗАЩИТА ОТ FSM DoS: Сбрасываем стейты ЛК, чтобы чат никогда не замораживался из-за открытых меню
    if state is not None:
        await state.clear()
        
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT tg_id, nickname FROM users WHERE tg_id IN (?, ?)", (buyer_id, seller_id)) as cursor:
            users_nicks = await cursor.fetchall()
            
    nicks_dict = {uid: name for uid, name in users_nicks}
    
    # Формируем анонимные префиксы для сообщений
    if sender_id == guarantor_id:
        prefix = f"⚠️ <b>[ГАРАНТ (Admin)]</b>" if sender_id in ADMIN_IDS else f"🔷 <b>[ГАРАНТ (Community)]</b>"
    elif sender_id == buyer_id:
        prefix = f"👤 <b>[{nicks_dict.get(buyer_id, 'Покупатель')}]</b>"
    elif sender_id == seller_id:
        prefix = f"👤 <b>[{nicks_dict.get(seller_id, 'Продавец')}]</b>"
    else:
        return
        
    # Собираем список получателей (все участники сделки, кроме самого отправителя)
    targets = [buyer_id, seller_id]
    if guarantor_id:
        targets.append(guarantor_id)
        
    for target_id in targets:
        if target_id and target_id != sender_id:
            try:
                if message.photo:
                    photo_id = message.photo[-1].file_id
                    # Защита caption от HTML инъекций
                    user_caption = f"\n{message.caption.replace('<', '&lt;').replace('>', '&gt;')}" if message.caption else ""
                    await bot.send_photo(chat_id=target_id, photo=photo_id, caption=f"{prefix} отправил фото:{user_caption}", parse_mode="HTML")
                elif message.text:
                    # ЗАЩИТА ОТ HTML-ИНЪЕКЦИЙ: Экранируем теги, которые шлет юзер текстом
                    clean_text = message.text.replace("<", "&lt;").replace(">", "&gt;")
                    await bot.send_message(chat_id=target_id, text=f"{prefix}: {clean_text}", parse_mode="HTML")
            except Exception:
                continue
