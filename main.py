import telebot
import os
import threading
import time
from datetime import datetime, timedelta
from telebot import types
from collections import defaultdict

bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))
ADMIN_ID = 6337781618

# Хранилище
questions = {}
active_chats = {}  # {user_id: {admin_id, username, last_activity}}
question_counter = 1
banned_users = set()
user_cache = {}  # Для поиска по нику: {user_id: username}
stats = {  # Статистика
    'questions_today': 0,
    'answered_today': 0,
    'active_chats_count': 0,
    'banned_count': 0
}

# ===== ТАЙМЕР =====
def chat_timeout_checker():
    while True:
        try:
            to_remove = []
            for user_id, chat_data in list(active_chats.items()):
                if datetime.now() - chat_data['last_activity'] > timedelta(minutes=5):
                    bot.send_message(user_id, "⏰ Переписка завершена (5 минут неактивности)")
                    bot.send_message(ADMIN_ID, f"⏰ Чат с {chat_data['username']} завершен")
                    to_remove.append(user_id)
            
            for user_id in to_remove:
                del active_chats[user_id]
                update_stats()
                
        except:
            pass
        time.sleep(60)

timer_thread = threading.Thread(target=chat_timeout_checker, daemon=True)
timer_thread.start()

# ===== ОБНОВЛЕНИЕ СТАТИСТИКИ =====
def update_stats():
    stats['active_chats_count'] = len(active_chats)
    stats['banned_count'] = len(banned_users)

# ===== ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =====
@bot.message_handler(commands=['start'])
def start(message):
    if message.from_user.id in banned_users:
        bot.send_message(message.chat.id, "🚫 Вы заблокированы")
        return
    
    user = message.from_user
    user_cache[user.id] = user.username or user.first_name
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📨 Задать вопрос'),
        types.KeyboardButton('💬 Прямая переписка')
    )
    bot.send_message(message.chat.id, "Выберите действие:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text in ['📨 Задать вопрос', '💬 Прямая переписка'] and m.from_user.id not in banned_users)
def handle_user_buttons(message):
    if message.text == '📨 Задать вопрос':
        msg = bot.send_message(message.chat.id, "Напишите ваш вопрос:", reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, save_question)
    else:
        request_direct_chat(message)

def request_direct_chat(message):
    global question_counter
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    user_cache[user.id] = username
    
    questions[question_counter] = {
        'user_id': user.id,
        'username': username,
        'type': 'chat_request',
        'time': datetime.now().strftime("%H:%M")
    }
    
    # Кнопки для админа
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('✅ Принять', callback_data=f'accept_{question_counter}'),
        types.InlineKeyboardButton('❌ Отказаться', callback_data=f'decline_{question_counter}')
    )
    
    bot.send_message(
        ADMIN_ID,
        f"💬 *Запрос на переписку #{question_counter}*\n"
        f"От: {username}\n"
        f"ID: `{user.id}`\n"
        f"Время: {questions[question_counter]['time']}",
        parse_mode='Markdown',
        reply_markup=markup
    )
    
    bot.send_message(message.chat.id, "✅ Запрос отправлен! Ожидайте ответа.")
    question_counter += 1
    stats['questions_today'] += 1

def save_question(message):
    global question_counter
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    user_cache[user.id] = username
    
    questions[question_counter] = {
        'user_id': user.id,
        'username': username,
        'text': message.text,
        'type': 'question',
        'time': datetime.now().strftime("%H:%M")
    }
    
    # Кнопки под вопросом
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('💬 Ответить', callback_data=f'reply_{question_counter}'),
        types.InlineKeyboardButton('🚫 Забанить', callback_data=f'banq_{question_counter}')
    )
    
    bot.send_message(
        ADMIN_ID,
        f"📨 *Вопрос #{question_counter}*\n"
        f"От: {username}\n"
        f"ID: `{user.id}`\n"
        f"Время: {questions[question_counter]['time']}\n\n"
        f"Текст: {message.text}",
        parse_mode='Markdown',
        reply_markup=markup
    )
    
    bot.send_message(message.chat.id, f"✅ Вопрос #{question_counter} отправлен!")
    question_counter += 1
    stats['questions_today'] += 1

# ===== АДМИН-МЕНЮ =====
@bot.message_handler(commands=['admin'])
def admin_menu(message):
    if message.chat.id != ADMIN_ID:
        return
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📋 Вопросы'),
        types.KeyboardButton('💬 Активные чаты'),
        types.KeyboardButton('📊 Статистика'),
        types.KeyboardButton('🚫 Забанены'),
        types.KeyboardButton('⏹ Завершить чат'),
        types.KeyboardButton('🔄 Обновить')
    )
    bot.send_message(ADMIN_ID, "🛠 *Панель администратора*", parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.text in [
    '📋 Вопросы', '💬 Активные чаты', '📊 Статистика', 
    '🚫 Забанены', '⏹ Завершить чат', '🔄 Обновить'
])
def handle_admin_menu(message):
    if message.text == '📋 Вопросы':
        show_questions(message)
    elif message.text == '💬 Активные чаты':
        show_active_chats(message)
    elif message.text == '📊 Статистика':
        show_stats(message)
    elif message.text == '🚫 Забанены':
        show_banned(message)
    elif message.text == '⏹ Завершить чат':
        end_chat_menu(message)
    elif message.text == '🔄 Обновить':
        admin_menu(message)

def show_questions(message):
    if not questions:
        bot.send_message(ADMIN_ID, "📭 Вопросов нет")
        return
    
    text = "📋 *Все вопросы:*\n\n"
    for num, q in sorted(questions.items()):
        if q['type'] == 'question':
            text += f"*#{num}* • {q['username']}\n"
            text += f"ID: `{q['user_id']}` • {q['time']}\n"
            text += f"Текст: {q['text'][:60]}...\n\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')
    
    # Отправляем кнопки управления под каждым вопросом
    for num, q in questions.items():
        if q['type'] == 'question':
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton(f'Ответить #{num}', callback_data=f'reply_{num}'),
                types.InlineKeyboardButton(f'Забанить {q["username"]}', callback_data=f'banq_{num}')
            )
            short_text = q['text'][:100] + "..." if len(q['text']) > 100 else q['text']
            bot.send_message(
                ADMIN_ID,
                f"#{num} • {q['username']} (`{q['user_id']}`)\n{short_text}",
                reply_markup=markup
            )

def show_active_chats(message):
    if not active_chats:
        bot.send_message(ADMIN_ID, "💭 Нет активных переписок")
        return
    
    text = "💬 *Активные чаты:*\n\n"
    for user_id, data in active_chats.items():
        text += f"👤 {data['username']}\n"
        text += f"ID: `{user_id}`\n"
        text += f"Активность: {data['last_activity'].strftime('%H:%M')}\n\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')
    
    # Кнопки завершения для каждого чата
    for user_id, data in active_chats.items():
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(f'⏹ Завершить чат с {data["username"]}', callback_data=f'endchat_{user_id}'))
        bot.send_message(ADMIN_ID, f"Чат с {data['username']} (`{user_id}`)", reply_markup=markup)

def end_chat_menu(message):
    if not active_chats:
        bot.send_message(ADMIN_ID, "💭 Нет активных переписок для завершения")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for user_id, data in active_chats.items():
        markup.add(types.InlineKeyboardButton(f'Завершить с {data["username"]}', callback_data=f'endchat_{user_id}'))
    
    bot.send_message(ADMIN_ID, "Выберите чат для завершения:", reply_markup=markup)

def show_stats(message):
    update_stats()
    text = (
        "📊 *Статистика*\n\n"
        f"• Вопросов сегодня: {stats['questions_today']}\n"
        f"• Отвечено сегодня: {stats['answered_today']}\n"
        f"• Активных чатов: {stats['active_chats_count']}\n"
        f"• Забаненных: {stats['banned_count']}\n"
        f"• Ожидают ответа: {len([q for q in questions.values() if q['type'] == 'question'])}\n"
        f"• Запросов чата: {len([q for q in questions.values() if q['type'] == 'chat_request'])}"
    )
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

def show_banned(message):
    if not banned_users:
        bot.send_message(ADMIN_ID, "✅ Нет забаненных пользователей")
        return
    
    text = "🚫 *Забаненные пользователи:*\n\n"
    for user_id in banned_users:
        username = user_cache.get(user_id, f"ID: {user_id}")
        text += f"• {username} (`{user_id}`)\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

# ===== ОБРАБОТКА CALLBACK =====
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    data = call.data
    
    if data.startswith('accept_'):
        num = int(data.split('_')[1])
        if num in questions and questions[num]['type'] == 'chat_request':
            q = questions[num]
            del questions[num]
            
            active_chats[q['user_id']] = {
                'admin_id': ADMIN_ID,
                'username': q['username'],
                'last_activity': datetime.now()
            }
            
            bot.edit_message_text(
                f"✅ Вы в переписке с {q['username']} (`{q['user_id']}`)\n\nПросто пишите сообщения — они будут пересылаться.",
                call.message.chat.id,
                call.message.message_id
            )
            
            bot.send_message(q['user_id'], "✅ Администратор принял запрос! Теперь вы можете общаться напрямую.")
            update_stats()
    
    elif data.startswith('decline_'):
        num = int(data.split('_')[1])
        if num in questions and questions[num]['type'] == 'chat_request':
            q = questions[num]
            del questions[num]
            
            bot.edit_message_text(
                f"❌ Отказано в переписке с {q['username']}",
                call.message.chat.id,
                call.message.message_id
            )
            
            bot.send_message(q['user_id'], "❌ Администратор отклонил запрос на переписку.")
    
    elif data.startswith('reply_'):
        num = int(data.split('_')[1])
        if num in questions and questions[num]['type'] == 'question':
            q = questions[num]
            msg = bot.send_message(ADMIN_ID, f"Введите ответ для {q['username']} (вопрос #{num}):")
            bot.register_next_step_handler(msg, send_answer, num)
    
    elif data.startswith('banq_'):
        num = int(data.split('_')[1])
        if num in questions:
            q = questions[num]
            banned_users.add(q['user_id'])
            bot.answer_callback_query(call.id, f"Пользователь {q['username']} забанен")
            bot.edit_message_text(
                f"🚫 {call.message.text}\n\n[ПОЛЬЗОВАТЕЛЬ ЗАБАНЕН]",
                call.message.chat.id,
                call.message.message_id
            )
            update_stats()
    
    elif data.startswith('endchat_'):
        user_id = int(data.split('_')[1])
        if user_id in active_chats:
            username = active_chats[user_id]['username']
            del active_chats[user_id]
            bot.send_message(ADMIN_ID, f"⏹ Чат с {username} завершен")
            bot.send_message(user_id, "⏹ Переписка завершена администратором")
            update_stats()
            bot.answer_callback_query(call.id, "Чат завершен")

# ===== ОТПРАВКА ОТВЕТОВ =====
def send_answer(message, question_num):
    if question_num in questions:
        q = questions[question_num]
        try:
            bot.send_message(q['user_id'], f"📩 *Ответ администратора:*\n\n{message.text}", parse_mode='Markdown')
            bot.send_message(ADMIN_ID, f"✅ Ответ #{question_num} отправлен {q['username']}")
            del questions[question_num]
            stats['answered_today'] += 1
        except:
            bot.send_message(ADMIN_ID, f"❌ Не удалось отправить ответ {q['username']}")

# ===== ПЕРЕСЫЛКА СООБЩЕНИЙ В ЧАТАХ =====
@bot.message_handler(func=lambda m: m.from_user.id in active_chats)
def user_to_admin(message):
    """Сообщение от пользователя в активном чате"""
    user_id = message.from_user.id
    chat_data = active_chats.get(user_id)
    
    if chat_data:
        # Обновляем время активности
        active_chats[user_id]['last_activity'] = datetime.now()
        
        # Отправляем админу
        bot.send_message(
            ADMIN_ID,
            f"👤 *{chat_data['username']}* (в чате):\n{message.text}",
            parse_mode='Markdown'
        )

@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.from_user.id == ADMIN_ID)
def admin_to_user(message):
    """Сообщение от админа (пересылается в активный чат)"""
    # Ищем, с кем сейчас активный чат
    for user_id, chat_data in active_chats.items():
        if chat_data['admin_id'] == ADMIN_ID:
            try:
                bot.send_message(user_id, f"👨‍💼 *Администратор:*\n{message.text}", parse_mode='Markdown')
                active_chats[user_id]['last_activity'] = datetime.now()
            except:
                bot.send_message(ADMIN_ID, "❌ Не удалось отправить сообщение")

# ===== КОМАНДЫ =====
@bot.message_handler(commands=['helper'])
def helper_command(message):
    if message.chat.id != ADMIN_ID:
        return
    
    text = (
        "📚 *Помощь по командам:*\n\n"
        "• `/admin` - открыть панель администратора\n"
        "• `/ban @username` - забанить по нику\n"
        "• `/unban @username` - разбанить по нику\n"
        "• `/stats` - статистика\n"
        "• `/helper` - это меню\n\n"
        "*Кнопки в панели:*\n"
        "📋 Вопросы - все вопросы с кнопками управления\n"
        "💬 Активные чаты - текущие переписки\n"
        "📊 Статистика - цифры и метрики\n"
        "🚫 Забанены - список забаненных\n"
        "⏹ Завершить чат - завершить выбранный чат\n"
        "🔄 Обновить - обновить меню"
    )
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

@bot.message_handler(commands=['stats'])
def stats_command(message):
    if message.chat.id != ADMIN_ID:
        return
    show_stats(message)

@bot.message_handler(commands=['ban', 'unban'])
def ban_commands(message):
    if message.chat.id != ADMIN_ID:
        return
    
    if len(message.text.split()) < 2:
        bot.send_message(ADMIN_ID, "Используйте: `/ban @username`", parse_mode='Markdown')
        return
    
    cmd = message.text.split()[0]
    username = message.text.split()[1].strip('@')
    
    # Ищем user_id по username в кэше
    user_id_to_ban = None
    for uid, uname in user_cache.items():
        if username.lower() in uname.lower():
            user_id_to_ban = uid
            break
    
    if not user_id_to_ban:
        bot.send_message(ADMIN_ID, f"❌ Пользователь @{username} не найден")
        return
    
    if user_id_to_ban == ADMIN_ID:
        bot.send_message(ADMIN_ID, "❌ Нельзя забанить себя")
        return
    
    if cmd == '/ban':
        banned_users.add(user_id_to_ban)
        bot.send_message(ADMIN_ID, f"✅ Забанен @{username} (`{user_id_to_ban}`)")
        # Если есть активный чат - завершаем
        if user_id_to_ban in active_chats:
            del active_chats[user_id_to_ban]
    elif cmd == '/unban':
        banned_users.discard(user_id_to_ban)
        bot.send_message(ADMIN_ID, f"✅ Разбанен @{username} (`{user_id_to_ban}`)")
    
    update_stats()

# ===== ЗАПУСК =====
if __name__ == '__main__':
    print(f"🤖 Бот запущен. Админ: {ADMIN_ID}")
    update_stats()
    bot.polling(none_stop=True)
