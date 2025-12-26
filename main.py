import telebot

# Создаем экземпляр бота с вашим токеном
bot = telebot.TeleBot('8507012598:AAGtKK4DLjj45AEyJu-p08UUQkstTlDlxO0')

# Функция, обрабатывающая команду /start
@bot.message_handler(commands=["start"])
def start(m, res=False):
    bot.send_message(m.chat.id, 'Я на связи. Напиши мне что-нибудь )')

# Получение сообщений от юзера
@bot.message_handler(content_types=["text"])
def handle_text(message):
    bot.send_message(message.chat.id, 'Вы написали: ' + message.text)

# Запускаем бота
bot.polling(none_stop=True, interval=0)
