import telebot

bot = telebot.TeleBot("8507012598:AAGtKK4DLjj45AEyJu-p08UUQkstTlDlxO0")

@bot.message_handler(commands=["start"])
def say_hello(message):
    bot.send_message(message.chat.id, "Привет!")

@bot.message_handler(content_types=["text"])
def repeat_message(message):
    bot.send_message(message.chat.id, message.text)

if __name__ == "__main__":
    bot.infinity_polling()
