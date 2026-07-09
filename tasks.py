import asyncio
import time
import aiosqlite
from aiogram import Bot
from database import DB_NAME

async def auto_cancel_expired_deals(bot: Bot):
    """
    Фоновая задача, которая проверяет просроченные сделки каждую минуту.
    Контролирует только безопасные этапы (депозит и ожидание оплаты).
    """
    while True:
        try:
            current_time = int(time.time())
            # 10 минут в секундах для проведения операции
            timeout = 600 
            
            async with aiosqlite.connect(DB_NAME) as db:
                # Ищем активные сделки на начальных этапах. 
                # Статус 'waiting_delivery' убран отсюда для защиты фиата Покупателя!
                query = """
                    SELECT id, offer_id, buyer_id, seller_id, status 
                    FROM deals 
                    WHERE status IN ('waiting_deposit', 'waiting_payment')
                """
                async with db.execute(query) as cursor:
                    active_deals = await cursor.fetchall()
                    
                for deal_id, offer_id, buyer_id, seller_id, status in active_deals:
                    # Получаем время старта текущего таймера шага
                    async with db.execute("SELECT timer_start FROM deals WHERE id = ?", (deal_id,)) as t_cursor:
                        res = await t_cursor.fetchone()
                        
                    if not res or not res[0]:
                        continue
                    timer_start = int(res[0])
                    
                    # Если лимит времени (10 минут) превышен
                    if current_time - timer_start > timeout:
                        # 1. Переводим сделку в статус 'cancelled'
                        await db.execute("UPDATE deals SET status = 'cancelled' WHERE id = ?", (deal_id,))
                        
                        # 2. Возвращаем исходное объявление обратно в стакан (активируем его)
                        await db.execute("UPDATE offers SET status = 'active' WHERE id = ?", (offer_id,))
                        await db.commit()
                        
                        # 3. Формируем текст уведомления в зависимости от шага
                        if status == 'waiting_deposit':
                            reason = "Продавец не внес криптовалютный депозит Гаранту вовремя."
                        elif status == 'waiting_payment':
                            reason = "Покупатель не отметил сделку как оплаченную в течение 10 минут."
                            
                        cancel_text = f"⏳ **Сделка #{deal_id} автоматически отменена!**\n\nПричина: {reason}\nОрдер возвращен в торговый стакан платформы."
                        
                        # Отправляем анонимные уведомления участникам
                        for user_id in [buyer_id, seller_id]:
                            try:
                                await bot.send_message(chat_id=user_id, text=cancel_text)
                            except Exception:
                                continue
                                
        except Exception as e:
            print(f"[ОШИБКА В ФОНОВОЙ ЗАДАЧЕ ТАЙМАУТОВ TASKS.PY]: {e}")
            
        # Строгая проверка базы данных ровно раз в минуту
        await asyncio.sleep(60)
