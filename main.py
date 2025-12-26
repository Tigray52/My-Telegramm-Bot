import telebot
from telebot import types
import os
from dotenv import load_dotenv

load_dotenv()
bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))

@bot.message_handler(commands=["start"])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("✉️ Написать в поддержку")
    bot.send_message(
        message.chat.id,
        "Здравствуйте! Я могу вам помочь?",
        reply_markup=markup
    )

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    if message.text == "✉️ Написать в поддержку":
        bot.send_message(message.chat.id, "✅ Кнопка работает! Функция в разработке.")
    else:
        bot.send_message(message.chat.id, "Пожалуйста, используйте кнопки меню")
        bot.delete_message(message.chat.id, message.message_id)

bot.polling(none_stop=True)
