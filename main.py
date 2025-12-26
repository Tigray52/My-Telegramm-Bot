import telebot
import os
import threading
import time
from datetime import datetime, timedelta
from telebot import types

bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))
ADMIN_ID = 6337781618

# Хранилище
questions = {}
active_chats = {}  # {user_id: admin_id} - активные переписки
question_counter = 1
banned_users = set()  # ID заблокированных пользователей

# ===== ТАЙМЕР ДЛЯ ПЕРЕПИСКИ =====
def chat_timeout_checker():
    """Проверяет неактивные переписки каждую минуту"""
    while True:
        try:
            to_remove = []
            for user_id, chat_data in list(active_chats.items()):
                if datetime.now() - chat_data['last_activity'] > timedelta(minutes=5):
                    # Уведомляем обоих
                    bot.send_message(user_id, "⏰ Переписка завершена (неактивность 5 минут)")
                    bot.send_message(chat_data['admin_id'], f"⏰ Переписка с {chat_data['username']} завершена")
                    to_remove.append(user_id)
            
            for user_id in to_remove:
                del active_chats[user_id]
                
        except:
            pass
        time.sleep(60)  # Проверка раз в минуту

# Запускаем таймер в отдельном потоке
timer_thread = threading.Thread(target=chat_timeout_checker, daemon=True)
timer_thread.start()

# ===== ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =====
@bot.message_handler(commands=['start'])
def start(message):
    if message.from_user.id in banned_users:
        bot.send_message(message.chat.id, "🚫 Вы заблокированы")
        return
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📨 Задать вопрос'),
        types.KeyboardButton('💬 Прямая переписка')
    )
    bot.send_message(message.chat.id, "Выберите:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text in ['📨 Задать вопрос', '💬 Прямая переписка'] and m.from_user.id not in banned_users)
def handle_user_buttons(message):
    if message.text == '📨 Задать вопрос':
        msg = bot.send_message(message.chat.id, "Напишите вопрос:", reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, save_question)
    elif message.text == '💬 Прямая переписка':
        request_direct_chat(message)

def request_direct_chat(message):
    global question_counter
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    
    questions[question_counter] = {
        'user_id': message.chat.id,
        'username': username,
        'type': 'chat'
    }
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('✅ Принять', callback_data=f'accept_{question_counter}'))
    
    bot.send_message(
        ADMIN_ID,
        f"💬 *Запрос на переписку #{question_counter}*\nОт: {username} (`{message.chat.id}`)",
        parse_mode='Markdown',
        reply_markup=markup
    )
    
    bot.send_message(message.chat.id, "✅ Запрос отправлен!")
    question_counter += 1

def save_question(message):
    global question_counter
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    
    questions[question_counter] = {
        'user_id': message.chat.id,
        'username': username,
        'text': message.text,
        'type': 'question'
    }
    
    bot.send_message(
        ADMIN_ID,
        f"📨 *Вопрос #{question_counter}*\nОт: {username} (`{message.chat.id}`)\nТекст: {message.text}",
        parse_mode='Markdown'
    )
    
    bot.send_message(message.chat.id, f"✅ Вопрос #{question_counter} отправлен!")
    question_counter += 1

# ===== АДМИН-МЕНЮ =====
@bot.message_handler(commands=['admin'])
def admin_menu(message):
    if message.chat.id != ADMIN_ID:
        return
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📋 Вопросы'),
        types.KeyboardButton('💬 Активные чаты'),
        types.KeyboardButton('📊 Забанены')
    )
    bot.send_message(ADMIN_ID, "🛠 Админ-панель:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.text in ['📋 Вопросы', '💬 Активные чаты', '📊 Забанены'])
def handle_admin_menu(message):
    if message.text == '📋 Вопросы':
        show_questions(message)
    elif message.text == '💬 Активные чаты':
        show_active_chats(message)
    elif message.text == '📊 Забанены':
        show_banned(message)

def show_questions(message):
    text = "📋 *Вопросы:*\n\n"
    for num, q in sorted(questions.items()):
        if q['type'] == 'question':
            text += f"*{num}.* {q['username']}: {q['text'][:50]}...\n"
            text += f"Ответить: `{num}. текст`\n\n"
    
    if text == "📋 *Вопросы:*\n\n":
        text = "📭 Вопросов нет"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

def show_active_chats(message):
    if not active_chats:
        bot.send_message(ADMIN_ID, "💭 Нет активных переписок")
        return
    
    text = "💬 *Активные чаты:*\n\n"
    for user_id, data in active_chats.items():
        text += f"👤 {data['username']} (`{user_id}`)\n"
        text += f"Написать: `msg_{user_id} текст`\n"
        text += f"Завершить: `/stop {user_id}`\n\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

def show_banned(message):
    if not banned_users:
        bot.send_message(ADMIN_ID, "✅ Нет заблокированных")
        return
    
    text = "📊 *Забанены:*\n\n"
    for user_id in banned_users:
        text += f"`{user_id}`\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

# ===== ОБРАБОТКА ЗАПРОСОВ ПЕРЕПИСКИ =====
@bot.callback_query_handler(func=lambda call: call.data.startswith('accept_'))
def accept_chat(call):
    num = int(call.data.split('_')[1])
    
    if num not in questions:
        bot.answer_callback_query(call.id, "Запрос устарел")
        return
    
    q = questions[num]
    del questions[num]
    
    # Запускаем переписку
    active_chats[q['user_id']] = {
        'admin_id': ADMIN_ID,
        'username': q['username'],
        'last_activity': datetime.now()
    }
    
    bot.edit_message_text(
        f"✅ Вы в переписке с {q['username']}\n\nНапишите что-нибудь...",
        call.message.chat.id,
        call.message.message_id
    )
    
    bot.send_message(
        q['user_id'],
        "✅ Администратор принял ваш запрос! Можете общаться напрямую."
    )

# ===== ПЕРЕСЫЛКА СООБЩЕНИЙ =====
@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.text.startswith('msg_'))
def admin_to_user(message):
    """Админ пишет: msg_123456789 текст"""
    parts = message.text.split(' ', 1)
    if len(parts) < 2:
        return
    
    user_id_str = parts[0].replace('msg_', '')
    if not user_id_str.isdigit():
        return
    
    user_id = int(user_id_str)
    text = parts[1]
    
    if user_id in active_chats:
        try:
            bot.send_message(user_id, f"👨‍💼 *Админ:* {text}", parse_mode='Markdown')
            active_chats[user_id]['last_activity'] = datetime.now()
            bot.reply_to(message, f"→ {text}")
        except:
            bot.reply_to(message, "❌ Не удалось отправить")
    else:
        bot.reply_to(message, "❌ Чат не активен")

@bot.message_handler(func=lambda m: m.from_user.id in active_chats and m.chat.id != ADMIN_ID)
def user_to_admin(message):
    """Пользователь в активной переписке"""
    user_id = message.from_user.id
    chat_data = active_chats.get(user_id)
    
    if chat_data:
        username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
        bot.send_message(
            ADMIN_ID,
            f"👤 *{username}:* {message.text}",
            parse_mode='Markdown'
        )
        active_chats[user_id]['last_activity'] = datetime.now()

# ===== КОМАНДЫ АДМИНА =====
@bot.message_handler(commands=['ban', 'unban', 'stop'])
def admin_commands(message):
    if message.chat.id != ADMIN_ID:
        return
    
    if not message.text or len(message.text.split()) < 2:
        bot.send_message(ADMIN_ID, "Используйте: `/ban 123456789`", parse_mode='Markdown')
        return
    
    cmd = message.text.split()[0]
    target = message.text.split()[1]
    
    try:
        # Пробуем извлечь ID из текста вида "123456789" или "@username"
        if target.startswith('@'):
            # Для бана по нику нужен другой подход (здесь упрощенно)
            bot.send_message(ADMIN_ID, "❌ Укажите ID пользователя")
            return
        
        target_id = int(target)
        
        if target_id == ADMIN_ID:
            bot.send_message(ADMIN_ID, "❌ Нельзя забанить себя")
            return
        
        if cmd == '/ban':
            banned_users.add(target_id)
            bot.send_message(ADMIN_ID, f"✅ Забанен `{target_id}`")
        elif cmd == '/unban':
            banned_users.discard(target_id)
            bot.send_message(ADMIN_ID, f"✅ Разбанен `{target_id}`")
        elif cmd == '/stop':
            if target_id in active_chats:
                username = active_chats[target_id]['username']
                del active_chats[target_id]
                bot.send_message(ADMIN_ID, f"⏹ Чат с {username} завершен")
                bot.send_message(target_id, "⏹ Переписка завершена администратором")
            else:
                bot.send_message(ADMIN_ID, "❌ Чат не активен")
                
    except ValueError:
        bot.send_message(ADMIN_ID, "❌ Неверный формат")

# ===== ОТВЕТЫ НА ВОПРОСЫ =====
@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.text and m.text[0].isdigit() and '.' in m.text)
def answer_question(message):
    parts = message.text.split('.', 1)
    if len(parts) != 2:
        return
    
    try:
        num = int(parts[0].strip())
        answer = parts[1].strip()
        
        if num in questions and questions[num]['type'] == 'question':
            q = questions[num]
            
            try:
                bot.send_message(q['user_id'], f"📩 *Ответ:* {answer}", parse_mode='Markdown')
                bot.reply_to(message, f"✅ Отправлено {q['username']}")
                del questions[num]
            except:
                bot.reply_to(message, f"❌ Не удалось отправить")
        else:
            bot.reply_to(message, f"❌ Вопрос не найден")
            
    except:
        pass

# ===== ЗАПУСК =====
if __name__ == '__main__':
    print(f"🤖 Бот запущен. Админ: {ADMIN_ID}")
    bot.polling(none_stop=True)
