import telebot
import os
from dotenv import load_dotenv

load_dotenv()  # Загружает .env файл

# Создаем экземпляр бота
bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))

# Целевой пользователь, которому будут пересылаться сообщения
TARGET_USERNAME = "UsernameFLX"  # Замени на нужный username

# Функция, обрабатывающая команду /start
@bot.message_handler(commands=["start"])
def start(m, res=False):
    bot.send_message(m.chat.id, 
                     f'Привет! Я бот-пересыльщик.\n'
                     f'Все ваши сообщения будут пересылаться пользователю @{TARGET_USERNAME}.\n'
                     f'Просто напишите что-нибудь...')

# Получение текстовых сообщений от юзера
@bot.message_handler(content_types=["text"])
def handle_text(message):
    try:
        # Отправляем сообщение пользователю (с указанием от кого)
        forward_text = f"📨 Новое сообщение от @{message.from_user.username} (ID: {message.from_user.id}):\n\n{message.text}"
        
        # Пытаемся найти пользователя по username
        bot.send_message(TARGET_USERNAME, forward_text)
        
        # Подтверждаем отправку пользователю
        bot.reply_to(message, f"✅ Сообщение переслано @{TARGET_USERNAME}")
        
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка при пересылке: {str(e)}")

# Получение других типов сообщений (фото, видео, документы и т.д.)
@bot.message_handler(content_types=["photo", "video", "document", "audio", "voice"])
def handle_media(message):
    try:
        caption = f"📎 Медиа от @{message.from_user.username} (ID: {message.from_user.id})"
        if message.caption:
            caption += f"\n\nПодпись: {message.caption}"
        
        # Пересылаем медиафайл
        bot.forward_message(TARGET_USERNAME, message.chat.id, message.message_id)
        
        # Отправляем дополнительную информацию
        bot.send_message(TARGET_USERNAME, caption)
        
        # Подтверждаем отправку пользователю
        bot.reply_to(message, f"✅ Медиа переслано @{TARGET_USERNAME}")
        
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка при пересылке медиа: {str(e)}")

# Запускаем бота
if __name__ == "__main__":
    print("Бот запущен...")
    bot.polling(none_stop=True, interval=0)
