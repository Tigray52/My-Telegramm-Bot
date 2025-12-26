import telebot
import os

# Получаем токен из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Проверяем, есть ли токен
if not BOT_TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не найден в переменных окружения!")
    print("Убедитесь, что вы установили BOT_TOKEN в настройках вашего хостинга")
    exit(1)

# Создаем экземпляр бота
bot = telebot.TeleBot(BOT_TOKEN)

# Целевой пользователь, которому будут пересылаться сообщения
TARGET_USERNAME = "UsernameFLX"  # Замени на нужный username

# Функция, обрабатывающая команду /start
@bot.message_handler(commands=["start"])
def start(m, res=False):
    bot.send_message(m.chat.id, 
                     f'👋 Привет! Я бот-пересыльщик.\n'
                     f'📤 Все ваши сообщения будут пересылаться пользователю @{TARGET_USERNAME}.\n\n'
                     f'Просто напишите что-нибудь...\n\n'
                     f'🆔 /id - узнать свой ID\n'
                     f'ℹ /info - информация о боте')

# Команда для получения информации о боте
@bot.message_handler(commands=["info"])
def info(message):
    bot.reply_to(message, 
                 f'🤖 Бот-пересыльщик\n'
                 f'👤 Целевой получатель: @{TARGET_USERNAME}\n'
                 f'📨 Все сообщения пересылаются автоматически')

# Команда для получения ID
@bot.message_handler(commands=["id"])
def get_id(message):
    user_info = f"👤 Ваш ID: `{message.from_user.id}`\n"
    user_info += f"📛 Username: @{message.from_user.username if message.from_user.username else 'не указан'}\n"
    user_info += f"👁 Имя: {message.from_user.first_name}"
    if message.from_user.last_name:
        user_info += f" {message.from_user.last_name}"
    bot.reply_to(message, user_info, parse_mode='Markdown')

# Получение текстовых сообщений от юзера
@bot.message_handler(content_types=["text"])
def handle_text(message):
    try:
        # Пропускаем команды
        if message.text.startswith('/'):
            return
            
        # Формируем информацию об отправителе
        sender_name = message.from_user.first_name
        if message.from_user.last_name:
            sender_name += f" {message.from_user.last_name}"
        
        sender_username = f"@{message.from_user.username}" if message.from_user.username else "Нет username"
        
        forward_text = f"📨 *Новое сообщение*\n"
        forward_text += f"👤 *От:* {sender_name}\n"
        forward_text += f"🆔 *Username:* {sender_username}\n"
        forward_text += f"🔢 *ID:* `{message.from_user.id}`\n"
        forward_text += f"💬 *Текст:*\n`{message.text}`"
        
        # Отправляем сообщение
        bot.send_message(TARGET_USERNAME, forward_text, parse_mode='Markdown')
        
        # Подтверждаем пользователю
        bot.reply_to(message, f"✅ Сообщение переслано @{TARGET_USERNAME}")
        
    except Exception as e:
        error_msg = f"❌ Ошибка при пересылке: {str(e)}"
        if "user not found" in str(e).lower():
            error_msg += "\n\n⚠ Пользователь @{TARGET_USERNAME} не найден или не начинал диалог с ботом"
        bot.reply_to(message, error_msg)

# Получение других типов сообщений
@bot.message_handler(content_types=["photo", "video", "document", "audio", "voice", "sticker", "animation"])
def handle_media(message):
    try:
        # Информация об отправителе
        sender_info = f"📎 *Медиа от:* {message.from_user.first_name}"
        if message.from_user.username:
            sender_info += f" (@{message.from_user.username})"
        sender_info += f"\n🆔 *ID:* `{message.from_user.id}`"
        
        # Определяем тип медиа
        media_types = {
            "photo": "📷 Фото",
            "video": "🎥 Видео", 
            "document": "📄 Документ",
            "audio": "🎵 Аудио",
            "voice": "🎤 Голосовое",
            "sticker": "🏷 Стикер",
            "animation": "🎞 GIF"
        }
        
        media_type = media_types.get(message.content_type, "📎 Файл")
        
        # Пересылаем медиафайл
        bot.forward_message(TARGET_USERNAME, message.chat.id, message.message_id)
        
        # Отправляем информацию об отправителе
        if message.caption:
            bot.send_message(TARGET_USERNAME, 
                           f"{media_type}\n{sender_info}\n📝 *Подпись:*\n`{message.caption}`", 
                           parse_mode='Markdown')
        else:
            bot.send_message(TARGET_USERNAME, 
                           f"{media_type}\n{sender_info}", 
                           parse_mode='Markdown')
        
        # Подтверждаем пользователю
        bot.reply_to(message, f"✅ {media_type} переслано @{TARGET_USERNAME}")
        
    except Exception as e:
        error_msg = f"❌ Ошибка при пересылке медиа: {str(e)}"
        if "user not found" in str(e).lower():
            error_msg += f"\n\n⚠ Пользователь @{TARGET_USERNAME} не найден"
        bot.reply_to(message, error_msg)

# Запускаем бота
if __name__ == "__main__":
    print("=" * 50)
    print("🤖 Бот-пересыльщик запущен!")
    print(f"🔑 Токен: {BOT_TOKEN[:15]}...")  # Показываем только часть токена для безопасности
    print(f"👤 Целевой получатель: @{TARGET_USERNAME}")
    print("=" * 50)
    
    try:
        bot.polling(none_stop=True, interval=0, timeout=60)
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        print("Перезапуск через 5 секунд...")
        import time
        time.sleep(5)
