import telebot
import os
from dotenv import load_dotenv

load_dotenv()
bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))

# Укажите username администратора (без @)
ADMIN_USERNAME = "UsernameFLX"

# Словарь для хранения состояний пользователей
user_states = {}

@bot.message_handler(commands=["start"])
def start(message):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = telebot.types.KeyboardButton("Написать в поддержку")
    btn2 = telebot.types.KeyboardButton("Написать администратору")
    markup.add(btn1, btn2)
    
    bot.send_message(
        message.chat.id,
        "Здравствуйте, чем я могу вам помочь?",
        reply_markup=markup
    )

@bot.message_handler(func=lambda message: message.text in ["Написать в поддержку", "Написать администратору"])
def handle_button(message):
    user_states[message.chat.id] = {
        "type": "поддержка" if message.text == "Написать в поддержку" else "администратору"
    }
    bot.send_message(
        message.chat.id,
        f"Введите ваше сообщение для {user_states[message.chat.id]['type']}:",
        reply_markup=telebot.types.ReplyKeyboardRemove()
    )

@bot.message_handler(content_types=["text"])
def handle_text(message):
    chat_id = message.chat.id
    
    if chat_id in user_states:
        # Формируем сообщение для администратора
        admin_message = (
            f"📨 Новое сообщение!\n"
            f"От: @{message.from_user.username if message.from_user.username else 'нет username'}\n"
            f"ID: {chat_id}\n"
            f"Тип: {user_states[chat_id]['type']}\n"
            f"Сообщение: {message.text}"
        )
        
        try:
            # Пытаемся отправить администратору
            bot.send_message(f"@{ADMIN_USERNAME}", admin_message)
            bot.send_message(chat_id, "✅ Сообщение отправлено!")
        except Exception as e:
            bot.send_message(chat_id, "❌ Не удалось отправить сообщение. Администратор не найден.")
        
        # Удаляем состояние пользователя
        del user_states[chat_id]
        
        # Возвращаем меню
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
        btn1 = telebot.types.KeyboardButton("Написать в поддержку")
        btn2 = telebot.types.KeyboardButton("Написать администратору")
        markup.add(btn1, btn2)
        bot.send_message(chat_id, "Выберите действие:", reply_markup=markup)
    else:
        # Если нет активного состояния, показываем меню
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
        btn1 = telebot.types.KeyboardButton("Написать в поддержку")
        btn2 = telebot.types.KeyboardButton("Написать администратору")
        markup.add(btn1, btn2)
        bot.send_message(chat_id, "Выберите действие:", reply_markup=markup)

bot.polling(none_stop=True, interval=0)
