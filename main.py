import telebot
import os

# 1. Токен берется из переменных окружения сервера
bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))

# 2. Ваш ID полученный от @userinfobot
ADMIN_ID = 6337781618  # ID UsernameFLX

@bot.message_handler(func=lambda m: True)
def forward_all(message):
    # Формируем текст сообщения
    user_info = message.from_user
    sender = f"@{user_info.username}" if user_info.username else user_info.first_name
    
    # Отправляем вам сообщение
    bot.send_message(ADMIN_ID, f'📩 От {sender} (ID: {user_info.id}):\n{message.text}')

bot.polling()
