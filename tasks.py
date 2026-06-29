import asyncio
import time
import aiosqlite
from aiogram import Bot
from database import DB_NAME

async def auto_cancel_expired_deals(bot: Bot):
    """
    Фоновая задача, которая проверяет просроченные сделки каждую минуту.
    Если с момента timer_start прошло более 600 секунд (10 минут),
    сделка автоматически отменяется, а объявление возвращается в стакан.
    """
    while True:
        try:
            current_time = int(time.time())
            # 10 минут в секундах
            timeout = 600 

            async with aiosqlite.connect(DB_NAME) as db:
                # Ищем активные незавершенные сделки, подлежащие контролю таймаутов
                # Статусы: ожидание продавца, ожидание оплаты, ожидание выдачи
                query = """
                    SELECT id, offer_id, buyer_id, seller_id, status 
                    FROM deals 
                    WHERE status IN ('waiting_seller', 'waiting_payment', 'waiting_delivery')
                """
                async with db.execute(query) as cursor:
                    active_deals = await cursor.fetchall()

                for deal_id, offer_id, buyer_id, seller_id, status in active_deals:
                    # Получаем время старта текущего таймера
                    async with db.execute("SELECT timer_start FROM deals WHERE id = ?", (deal_id,)) as t_cursor:
                        res = await t_cursor.fetchone()
                        if not res or not res[0]:
                            continue
                        timer_start = int(res[0])

                    # Если время истекло
                    if current_time - timer_start > timeout:
                        # 1. Переводим сделку в статус 'cancelled'
                        await db.execute("UPDATE deals SET status = 'cancelled' WHERE id = ?", (deal_id,))
                        
                        # 2. Возвращаем объявление обратно в стакан (активируем его)
                        await db.execute("UPDATE offers SET status = 'active' WHERE id = ?", (offer_id,))
                        await db.commit()

                        # 3. Формируем текст уведомления в зависимости от того, на каком этапе упал таймаут
                        if status == 'waiting_seller':
                            reason = "Продавец не подтвердил сделку вовремя."
                        elif status == 'waiting_payment':
                            reason = "Покупатель не отметил сделку как оплаченную в течение 10 минут."
                        elif status == 'waiting_delivery':
                            reason = "Продавец не подтвердил получение средств вовремя. Объявление возвращено в стакан, для защиты средств рекомендуется вызвать Гаранта, если оплата была совершена."

                        cancel_text = f"⏳ **Сделка #{deal_id} автоматически отменена!**\nПричина: {reason}"

                        # Отправляем уведомления участникам
                        for user_id in [buyer_id, seller_id]:
                            try:
                                await bot.send_message(chat_id=user_id, text=cancel_text)
                            except Exception:
                                continue
                                
        except Exception as e:
            print(f"Ошибка в фоновой задаче таймаутов: {e}")
            
        # Проверяем базу данных ровно раз в минуту
        await asyncio.sleep(60)
