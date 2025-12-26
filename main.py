import telebot
import os
from telebot import types

bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))

# ID администратора (ваш ID)
ADMIN_ID = 6337781618

# Словарь для хранения связи: ID администратора -> (ID отправителя, имя отправителя)
# Ключ - это ID сообщения, отправленного админу. Значение - это кортеж с данными пользователя.
awaiting_reply = {}

# --- 1. Красивый интерфейс при старте ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    # Создаем встроенную клавиатуру (Inline Keyboard)
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_help = types.InlineKeyboardButton('🆘 Помощь', callback_data='help')
    btn_contact = types.InlineKeyboardButton('📨 Написать админу', callback_data='contact')
    markup.add(btn_help, btn_contact)

    welcome_text = (
        f"Привет, {message.from_user.first_name}!\n"
        "Я — бот-помощник. Выбери действие ниже:"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

# --- 2. Обработка нажатий на кнопки интерфейса ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id

    if call.data == 'help':
        # Редактируем текущее сообщение, чтобы показать справку
        help_text = "Просто нажми кнопку 'Написать админу' и отправь свой вопрос."
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=help_text,
            reply_markup=None
        )
    elif call.data == 'contact':
        # Просим пользователя написать сообщение
        msg = bot.send_message(chat_id, "Напишите ваш вопрос или сообщение для администратора:")
        bot.register_next_step_handler(msg, forward_to_admin)  # Ждем текст

# --- 3. Пересылка сообщения от пользователя админу ---
def forward_to_admin(message):
    user_info = message.from_user
    sender_name = f"@{user_info.username}" if user_info.username else user_info.first_name

    # Формируем клавиатуру с кнопкой "Ответить" для админа
    markup_admin = types.InlineKeyboardMarkup()
    btn_reply = types.InlineKeyboardButton('💬 Ответить', callback_data=f'reply_{message.chat.id}')
    markup_admin.add(btn_reply)

    # Сообщение для админа
    admin_msg_text = f"📨 *Новое сообщение*\nОт: {sender_name} (`{message.chat.id}`)\n\n{message.text}"
    # Сохраняем связь. Временно запомним chat_id пользователя.
    # Более надежное сохранение реализуем при нажатии кнопки "Ответить".
    msg_to_admin = bot.send_message(ADMIN_ID, admin_msg_text, parse_mode='Markdown', reply_markup=markup_admin)

    # Сохраняем в словарь: ID сообщения у админа -> (ID пользователя, его имя)
    awaiting_reply[msg_to_admin.message_id] = (message.chat.id, sender_name)

    # Подтверждение пользователю
    bot.send_message(message.chat.id, "✅ Ваше сообщение отправлено администратору.")

# --- 4. Обработка команды "Ответить" от админа ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
def handle_admin_reply_callback(call):
    # Из callback_data извлекаем ID пользователя (после префикса 'reply_')
    user_chat_id = int(call.data.split('_')[1])

    # Просим админа ввести текст ответа
    msg = bot.send_message(ADMIN_ID, "Введите ваш ответ для этого пользователя:")
    # Регистрируем следующий шаг: функция send_reply_to_user получит текст ответа
    bot.register_next_step_handler(msg, send_reply_to_user, user_chat_id)

    # Подтверждаем нажатие кнопки (убирает часики)
    bot.answer_callback_query(call.id, "Введите ответ...")

# --- 5. Отправка ответа от админа пользователю ---
def send_reply_to_user(message, user_chat_id):
    # message - это сообщение с текстом от админа
    try:
        # Пытаемся отправить ответ пользователю
        bot.send_message(user_chat_id, f"📩 *Ответ от администратора:*\n\n{message.text}", parse_mode='Markdown')
        # Подтверждаем админу
        bot.send_message(ADMIN_ID, f"✅ Ответ отправлен пользователю (`{user_chat_id}`).")
    except Exception as e:
        # Если не удалось (например, пользователь заблокировал бота)
        bot.send_message(ADMIN_ID, f"❌ Не удалось отправить ответ. Возможно, пользователь заблокировал бота.")

# --- 6. Запуск бота ---
if __name__ == '__main__':
    print("Бот запущен...")
    bot.polling(none_stop=True)
