import os
import sys

# Токен бота будет считываться из безопасных переменных окружения сервера
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ID администраторов считываются через запятую, например: 123456,789012
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "")

if not BOT_TOKEN:
    print("КРИТИЧЕСКАЯ ОШИБКА: Переменная окружения BOT_TOKEN не задана!")
    sys.exit(1)

# Превращаем строку с ID админов в чистый список чисел Python
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

if not ADMIN_IDS:
    print("ВНИМАНИЕ: Список ADMIN_IDS пуст. Функции гаранта и верификации будут недоступны!")
