import telebot
import os

BOT_TOKEN = os.getenv('BOT_TOKEN')
bot = telebot.TeleBot(BOT_TOKEN)
TARGET = "UsernameFLX"

@bot.message_handler(func=lambda message: True)
def send_all(message):
    try:
        # Если это текст
        if message.text:
            text_to_send = f"{message.from_user.first_name}: {message.text}"
            bot.send_message(TARGET, text_to_send)
        
        # Если это медиа - пересылаем как forward
        else:
            bot.forward_message(TARGET, message.chat.id, message.message_id)
        
        bot.reply_to(message, "✅ Отправлено")
        
    except Exception as e:
        print(f"Ошибка: {e}")

if __name__ == "__main__":
    print("Бот запущен...")
    bot.polling(none_stop=True)
