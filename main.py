import telebot
import os
from telebot import types

bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))
ADMIN_ID = 6337781618

# Словарь для хранения связи: ID админского сообщения -> ID пользователя
pending_replies = {}

# Словарь для хранения состояния админа: "ожидает ответ для какого пользователя"
admin_state = {}

# --- 1. Красивый интерфейс при старте ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_help = types.InlineKeyboardButton('🆘 Помощь', callback_data='help')
    btn_contact = types.InlineKeyboardButton('📨 Написать админу', callback_data='contact')
    markup.add(btn_help, btn_contact)

    welcome_text = f"Привет, {message.from_user.first_name}!\nЯ — бот-помощник. Выбери действие:"
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

# --- 2. Обработка кнопок ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    if call.data == 'help':
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Просто нажми 'Написать админу' и отправь свой вопрос.",
            reply_markup=None
        )
    elif call.data == 'contact':
        msg = bot.send_message(call.message.chat.id, "Напишите ваш вопрос для администратора:")
        bot.register_next_step_handler(msg, forward_to_admin)
    
    # Убираем "часики" на кнопке
    bot.answer_callback_query(call.id)

# --- 3. Пересылка сообщения админу ---
def forward_to_admin(message):
    user = message.from_user
    sender_name = f"@{user.username}" if user.username else user.first_name

    # Создаем уникальный callback_data с ID сообщения пользователя
    callback_data = f"reply_{message.chat.id}_{message.message_id}"
    
    markup_admin = types.InlineKeyboardMarkup()
    btn_reply = types.InlineKeyboardButton('💬 Ответить', callback_data=callback_data)
    markup_admin.add(btn_reply)

    # Сохраняем связь
    pending_replies[message.message_id] = message.chat.id

    admin_msg = f"📨 *Новое сообщение*\nОт: {sender_name} (`{message.chat.id}`)\n\n{message.text}"
    bot.send_message(ADMIN_ID, admin_msg, parse_mode='Markdown', reply_markup=markup_admin)
    
    bot.send_message(message.chat.id, "✅ Ваше сообщение отправлено.")

# --- 4. Обработка кнопки "Ответить" ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
def handle_reply_button(call):
    # Парсим данные из callback_data: reply_<user_chat_id>_<user_message_id>
    parts = call.data.split('_')
    if len(parts) >= 2:
        user_chat_id = int(parts[1])
        
        # Устанавливаем состояние админа: теперь он ожидает текст ответа
        admin_state[call.from_user.id] = user_chat_id
        
        # Отправляем админу сообщение с просьбой ввести ответ
        bot.send_message(ADMIN_ID, f"Введите ответ для пользователя ({user_chat_id}):")
        
        # Убираем "часики" и показываем уведомление
        bot.answer_callback_query(call.id, "Теперь введите текст ответа...", show_alert=False)
    else:
        bot.answer_callback_query(call.id, "Ошибка: неверный формат данных", show_alert=True)

# --- 5. Обработка ЛЮБОГО текста от админа как ответ ---
@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.text and not m.text.startswith('/'))
def handle_admin_message(message):
    # Проверяем, находится ли админ в режиме ответа
    if message.from_user.id in admin_state:
        user_chat_id = admin_state[message.from_user.id]
        
        try:
            # Отправляем ответ пользователю
            bot.send_message(user_chat_id, f"📩 *Ответ от администратора:*\n\n{message.text}", parse_mode='Markdown')
            
            # Подтверждение админу
            bot.send_message(ADMIN_ID, f"✅ Ответ отправлен пользователю (`{user_chat_id}`).")
            
            # Удаляем состояние
            del admin_state[message.from_user.id]
            
        except Exception as e:
            bot.send_message(ADMIN_ID, f"❌ Ошибка: {e}")
            del admin_state[message.from_user.id]
    
    # Если админ не в режиме ответа, игнорируем сообщение (или можно добавить другую логику)

# --- 6. Запуск бота ---
if __name__ == '__main__':
    print("Бот запущен и готов к работе...")
    bot.polling(none_stop=True)
