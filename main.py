import telebot
import os
import json
import re
from datetime import datetime
from telebot import types

bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))
ADMIN_ID = 6337781618

# Хранилище данных
class Storage:
    def __init__(self):
        self.questions = {}
        self.active_chats = {}
        self.banned_users = set()
        self.user_profiles = {}
        self.question_counter = 1
        self.load_data()
    
    def load_data(self):
        try:
            if os.path.exists('storage.json'):
                with open('storage.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.questions = {int(k): v for k, v in data.get('questions', {}).items()}
                    self.banned_users = set(data.get('banned_users', []))
                    self.user_profiles = data.get('user_profiles', {})
                    self.question_counter = data.get('counter', 1)
        except:
            pass
    
    def save_data(self):
        data = {
            'questions': self.questions,
            'banned_users': list(self.banned_users),
            'user_profiles': self.user_profiles,
            'counter': self.question_counter
        }
        with open('storage.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

storage = Storage()

# ===== ПРОВЕРКИ =====
def is_admin(user_id):
    return user_id == ADMIN_ID

def is_user_in_chat(user_id):
    return user_id in storage.active_chats

# ===== ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =====
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    
    if user_id in storage.banned_users:
        bot.send_message(user_id, "🚫 Вы заблокированы администратором.")
        return
    
    if is_admin(user_id):
        admin_panel(message)
        return
    
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    if user_id not in storage.user_profiles:
        storage.user_profiles[user_id] = {
            'username': username,
            'first_name': message.from_user.first_name,
            'joined': datetime.now().isoformat(),
            'questions_sent': 0,
            'warnings': 0
        }
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📨 Задать вопрос'),
        types.KeyboardButton('💬 Прямая переписка'),
        types.KeyboardButton('ℹ️ Помощь')
    )
    
    bot.send_message(
        user_id,
        f"👋 Привет, {message.from_user.first_name}!\n\nВыберите действие:",
        reply_markup=markup
    )

@bot.message_handler(func=lambda m: m.text in ['📨 Задать вопрос', '💬 Прямая переписка', 'ℹ️ Помощь'])
def handle_user_menu(message):
    user_id = message.from_user.id
    
    if user_id in storage.banned_users:
        return
    
    if is_admin(user_id):
        bot.send_message(user_id, "❌ Администраторы не могут использовать эти функции.")
        return
    
    # Проверка на команды во время диалога
    if is_user_in_chat(user_id):
        end_chat(user_id, "user_used_command")
        bot.send_message(user_id, "❌ Диалог завершен, так как вы использовали команду.")
        return
    
    if message.text == '📨 Задать вопрос':
        msg = bot.send_message(
            user_id,
            "📝 *Напишите ваш вопрос:*\n\nМаксимум 400 символов.",
            parse_mode='Markdown',
            reply_markup=types.ReplyKeyboardRemove()
        )
        bot.register_next_step_handler(msg, ask_question_step2)
    elif message.text == '💬 Прямая переписка':
        request_chat(message)
    elif message.text == 'ℹ️ Помощь':
        show_user_help(message)

def ask_question_step2(message):
    user_id = message.from_user.id
    
    # Проверка длины сообщения
    if message.text and len(message.text.strip()) > 400:
        bot.send_message(user_id, "❌ Сообщение слишком длинное (макс. 400 символов). Попробуйте снова.")
        ask_question_step1(user_id)
        return
    
    if not message.text or len(message.text.strip()) < 5:
        bot.send_message(user_id, "❌ Вопрос слишком короткий.")
        ask_question_step1(user_id)
        return
    
    # Сохраняем вопрос
    question_id = storage.question_counter
    username = storage.user_profiles[user_id]['username']
    
    storage.questions[question_id] = {
        'id': question_id,
        'user_id': user_id,
        'username': username,
        'text': message.text[:400],  # Обрезаем до 400 символов
        'time': datetime.now().strftime("%H:%M"),
        'date': datetime.now().strftime("%d.%m.%Y"),
        'status': 'pending',
        'admin_response': None
    }
    
    storage.user_profiles[user_id]['questions_sent'] += 1
    storage.question_counter += 1
    
    # Уведомляем админа
    notify_admin_about_question(question_id, storage.questions[question_id])
    
    bot.send_message(
        user_id,
        f"✅ *Вопрос #{question_id} отправлен!*\n\nАдминистратор ответит в ближайшее время.",
        parse_mode='Markdown'
    )
    
    show_user_menu(user_id)
    storage.save_data()

def ask_question_step1(user_id):
    msg = bot.send_message(
        user_id,
        "📝 *Напишите ваш вопрос:*\n\nМаксимум 400 символов.",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, ask_question_step2)

def request_chat(message):
    user_id = message.from_user.id
    username = storage.user_profiles[user_id]['username']
    
    chat_request_id = storage.question_counter
    
    storage.questions[chat_request_id] = {
        'id': chat_request_id,
        'user_id': user_id,
        'username': username,
        'text': "[ЗАПРОС ПЕРЕПИСКИ]",
        'time': datetime.now().strftime("%H:%M"),
        'date': datetime.now().strftime("%d.%m.%Y"),
        'type': 'chat_request',
        'status': 'pending'
    }
    
    storage.question_counter += 1
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton('✅ Принять чат', callback_data=f'accept_chat_{chat_request_id}'),
        types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_user_{user_id}')
    )
    
    bot.send_message(
        ADMIN_ID,
        f"💬 *Запрос на переписку #{chat_request_id}*\n"
        f"От: {username}\n"
        f"ID: `{user_id}`",
        parse_mode='Markdown',
        reply_markup=markup
    )
    
    bot.send_message(user_id, "✅ Запрос на переписку отправлен администратору!")
    show_user_menu(user_id)
    storage.save_data()

def show_user_help(message):
    help_text = (
        "ℹ️ *Помощь*\n\n"
        "*📨 Задать вопрос:*\n"
        "• Максимум 400 символов\n"
        "• Ответ в течение 24 часов\n\n"
        "*💬 Прямая переписка:*\n"
        "• Запрос живого диалога\n"
        "• Админ может принять или отклонить\n\n"
        "*⚠️ Важно:*\n"
        "• Не используйте команды во время диалога\n"
        "• За спам - блокировка\n"
        "• Уважайте администратора"
    )
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

def show_user_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📨 Задать вопрос'),
        types.KeyboardButton('💬 Прямая переписка'),
        types.KeyboardButton('ℹ️ Помощь')
    )
    bot.send_message(user_id, "Главное меню:", reply_markup=markup)

# ===== УВЕДОМЛЕНИЕ АДМИНА =====
def notify_admin_about_question(question_id, question_data):
    text_preview = question_data['text'][:100] + "..." if len(question_data['text']) > 100 else question_data['text']
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('✏️ Ответить', callback_data=f'answer_{question_id}'),
        types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_{question_id}')
    )
    
    notification = (
        f"📨 *Вопрос #{question_id}*\n"
        f"👤 {question_data['username']} (`{question_data['user_id']}`)\n"
        f"⏰ {question_data['time']}\n\n"
        f"💬 {text_preview}"
    )
    
    bot.send_message(ADMIN_ID, notification, parse_mode='Markdown', reply_markup=markup)

# ===== АДМИН-ПАНЕЛЬ (УПРОЩЕННАЯ) =====
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if not is_admin(message.from_user.id):
        return
    
    pending_count = len([q for q in storage.questions.values() if q.get('status') == 'pending'])
    
    text = (
        f"👑 *Панель администратора*\n\n"
        f"📊 Статистика:\n"
        f"• Вопросов: {pending_count}\n"
        f"• Чатов: {len(storage.active_chats)}\n"
        f"• Пользователей: {len(storage.user_profiles)}\n"
        f"• Забанено: {len(storage.banned_users)}\n\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}"
    )
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📋 Задачи (/Tasks)'),
        types.KeyboardButton('💬 Активные чаты'),
        types.KeyboardButton('🚫 Бан-лист'),
        types.KeyboardButton('🔄 Обновить')
    )
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == '📋 Задачи (/Tasks)' and is_admin(m.from_user.id))
def show_tasks(message):
    pending_questions = [q for q in storage.questions.values() if q.get('status') == 'pending']
    
    if not pending_questions:
        bot.send_message(ADMIN_ID, "✅ *Все вопросы обработаны!*", parse_mode='Markdown')
        return
    
    bot.send_message(ADMIN_ID, f"📋 *Задачи: {len(pending_questions)}*", parse_mode='Markdown')
    
    for question in pending_questions:
        text_preview = question['text'][:80] + "..." if len(question['text']) > 80 else question['text']
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(f'Ответить #{question["id"]}', callback_data=f'answer_{question["id"]}'),
            types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_{question["id"]}')
        )
        
        question_text = (
            f"🔔 #{question['id']}\n"
            f"👤 {question['username']} (`{question['user_id']}`)\n"
            f"⏰ {question['time']}\n\n"
            f"{text_preview}"
        )
        
        bot.send_message(ADMIN_ID, question_text, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['Tasks'])
def tasks_command(message):
    if is_admin(message.from_user.id):
        show_tasks(message)

@bot.message_handler(func=lambda m: m.text == '💬 Активные чаты' and is_admin(m.from_user.id))
def show_active_chats(message):
    if not storage.active_chats:
        bot.send_message(ADMIN_ID, "💭 Нет активных чатов")
        return
    
    text = "💬 *Активные чаты:*\n\n"
    for user_id, chat_data in storage.active_chats.items():
        if chat_data['admin_id'] == ADMIN_ID:
            text += f"👤 {chat_data['user_name']}\n"
            text += f"ID: `{user_id}`\n"
            text += f"Имя админа: {chat_data['admin_name']}\n\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == '🚫 Бан-лист' and is_admin(m.from_user.id))
def show_bans(message):
    if not storage.banned_users:
        bot.send_message(ADMIN_ID, "✅ Нет забаненных")
        return
    
    text = "🚫 *Бан-лист:*\n\n"
    for user_id in storage.banned_users:
        username = storage.user_profiles.get(user_id, {}).get('username', f'ID: {user_id}')
        text += f"• {username} (`{user_id}`)\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == '🔄 Обновить' and is_admin(m.from_user.id))
def refresh_admin(message):
    admin_panel(message)

# ===== КОМАНДА /MESSAGE =====
@bot.message_handler(commands=['Message'])
def message_command(message):
    """Отправка сообщения пользователю"""
    if not is_admin(message.from_user.id):
        return
    
    if len(message.text.split()) < 2:
        bot.send_message(ADMIN_ID, "Используйте: /Message [ID] текст\nили /Message [ID, Имя] текст")
        return
    
    # Парсим команду
    match = re.search(r'\[([^\]]+)\]\s*(.+)', message.text)
    if not match:
        bot.send_message(ADMIN_ID, "❌ Неверный формат. Пример:\n`/Message [123456789] Текст`")
        return
    
    params = match.group(1).strip()
    message_text = match.group(2).strip()
    
    # Парсим параметры
    if ',' in params:
        parts = [p.strip() for p in params.split(',', 1)]
        user_id_str = parts[0]
        admin_name = parts[1] if len(parts) > 1 else "Модератор"
    else:
        user_id_str = params
        admin_name = "Модератор"
    
    if not user_id_str.isdigit():
        bot.send_message(ADMIN_ID, "❌ ID должен быть числом")
        return
    
    user_id = int(user_id_str)
    
    # Проверяем существование пользователя
    if user_id not in storage.user_profiles:
        bot.send_message(ADMIN_ID, f"❌ Пользователь с ID {user_id} не найден")
        return
    
    if user_id in storage.banned_users:
        bot.send_message(ADMIN_ID, f"⚠️ Пользователь {user_id} забанен")
        return
    
    # Отправляем сообщение
    try:
        formatted_message = (
            f"📨 *Сообщение от {admin_name}:*\n\n"
            f"╔═✦ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ✦═╗\n"
            f"   {message_text}\n"
            f"╚═✦ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ✦═╝\n\n"
            f"_Это автоматическое уведомление_"
        )
        
        bot.send_message(user_id, formatted_message, parse_mode='Markdown')
        bot.send_message(ADMIN_ID, f"✅ Сообщение отправлено пользователю `{user_id}`")
        
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Ошибка: {str(e)}")

# ===== ОБРАБОТКА CALLBACK =====
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    if call.data.startswith('accept_chat_'):
        question_id = int(call.data.replace('accept_chat_', ''))
        
        if question_id not in storage.questions:
            bot.answer_callback_query(call.id, "❌ Запрос устарел")
            return
        
        question = storage.questions[question_id]
        user_id = question['user_id']
        
        storage.questions[question_id]['status'] = 'accepted'
        
        msg = bot.send_message(
            ADMIN_ID,
            f"💬 *Принят запрос на переписку*\n\n"
            f"Пользователь: {question['username']}\n\n"
            f"📝 *Как вас звать в этой переписке?*",
            parse_mode='Markdown'
        )
        
        bot.register_next_step_handler(msg, process_admin_name, user_id, question_id)
        bot.answer_callback_query(call.id, "✅ Запрос принят")
    
    elif call.data.startswith('ban_') or call.data.startswith('ban_user_'):
        if call.data.startswith('ban_'):
            question_id = int(call.data.replace('ban_', ''))
            if question_id not in storage.questions:
                bot.answer_callback_query(call.id, "❌ Вопрос не найден")
                return
            user_id = storage.questions[question_id]['user_id']
        else:
            user_id = int(call.data.replace('ban_user_', ''))
        
        storage.banned_users.add(user_id)
        
        if user_id in storage.active_chats:
            del storage.active_chats[user_id]
        
        username = storage.user_profiles.get(user_id, {}).get('username', f'ID: {user_id}')
        bot.send_message(ADMIN_ID, f"🚫 Пользователь {username} забанен.")
        
        try:
            bot.send_message(user_id, "🚫 Вы были заблокированы администратором.")
        except:
            pass
        
        bot.answer_callback_query(call.id, "✅ Пользователь забанен")
        storage.save_data()
    
    elif call.data.startswith('answer_'):
        question_id = int(call.data.replace('answer_', ''))
        
        if question_id not in storage.questions:
            bot.answer_callback_query(call.id, "❌ Вопрос не найден")
            return
        
        question = storage.questions[question_id]
        
        msg = bot.send_message(
            ADMIN_ID,
            f"✏️ *Ответ на вопрос #{question_id}*\n\n"
            f"От: {question['username']}\n"
            f"Вопрос: {question['text'][:200]}...\n\n"
            f"*Введите ответ:*",
            parse_mode='Markdown'
        )
        
        bot.register_next_step_handler(msg, process_admin_answer, question_id)
        bot.answer_callback_query(call.id, "✏️ Введите ответ...")

def process_admin_name(message, user_id, question_id):
    admin_name = message.text.strip()[:20]  # Ограничиваем длину
    
    if not admin_name:
        bot.send_message(ADMIN_ID, "❌ Имя не может быть пустым.")
        return
    
    # Создаем чат
    storage.active_chats[user_id] = {
        'admin_id': ADMIN_ID,
        'user_name': storage.questions[question_id]['username'],
        'admin_name': admin_name,
        'start_time': datetime.now().isoformat(),
        'question_id': question_id
    }
    
    bot.send_message(
        user_id,
        f"💬 *Переписка начата!*\n\n"
        f"✅ Администратор принял ваш запрос.\n\n"
        f"👨‍💼 *{admin_name} (Администратор)*\n"
        f"Теперь вы можете общаться напрямую.",
        parse_mode='Markdown'
    )
    
    bot.send_message(
        ADMIN_ID,
        f"💬 *Чат начат!*\n\n"
        f"С пользователем: {storage.active_chats[user_id]['user_name']}\n"
        f"Ваше имя в чате: *{admin_name}*\n\n"
        f"Пишите сообщения - они будут пересылаться.\n"
        f"Используйте /stop для завершения.",
        parse_mode='Markdown'
    )
    
    storage.save_data()

def process_admin_answer(message, question_id):
    if question_id not in storage.questions:
        bot.send_message(ADMIN_ID, "❌ Вопрос не найден")
        return
    
    question = storage.questions[question_id]
    answer_text = message.text
    
    try:
        bot.send_message(
            question['user_id'],
            f"📩 *Ответ на ваш вопрос #{question_id}:*\n\n{answer_text}",
            parse_mode='Markdown'
        )
        
        storage.questions[question_id]['status'] = 'answered'
        storage.questions[question_id]['admin_response'] = answer_text
        storage.questions[question_id]['answer_time'] = datetime.now().strftime("%H:%M")
        
        bot.send_message(ADMIN_ID, f"✅ Ответ #{question_id} отправлен {question['username']}")
        
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Ошибка: {str(e)}")
    
    storage.save_data()

# ===== ПЕРЕСЫЛКА СООБЩЕНИЙ В ЧАТЕ =====
@bot.message_handler(func=lambda m: m.from_user.id in storage.active_chats)
def handle_user_chat_message(message):
    """Сообщение от пользователя в активном чате"""
    user_id = message.from_user.id
    chat_data = storage.active_chats.get(user_id)
    
    if not chat_data:
        return
    
    # Проверяем, не команда ли это
    if message.text and message.text.startswith('/'):
        end_chat(user_id, "user_used_command")
        bot.send_message(user_id, "❌ Диалог завершен, так как вы использовали команду.")
        return
    
    sender = chat_data['user_name']
    
    if message.content_type == 'text':
        bot.send_message(
            ADMIN_ID,
            f"👤 *{sender}:*\n{message.text}",
            parse_mode='Markdown'
        )

@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.chat.id == ADMIN_ID)
def handle_admin_message(message):
    """Сообщение от админа (пересылается в активный чат)"""
    # Находим активный чат
    active_user_id = None
    for user_id, chat_data in storage.active_chats.items():
        if chat_data['admin_id'] == ADMIN_ID:
            active_user_id = user_id
            break
    
    if not active_user_id:
        # Проверяем команды
        if message.text and message.text.startswith('/'):
            return
        return
    
    chat_data = storage.active_chats[active_user_id]
    
    # Проверяем команды
    if message.text and message.text.startswith('/stop'):
        end_chat(active_user_id)
        return
    
    # Пересылаем сообщение
    try:
        if message.content_type == 'text':
            bot.send_message(
                active_user_id,
                f"👨‍💼 *{chat_data['admin_name']} (Администратор):*\n{message.text}",
                parse_mode='Markdown'
            )
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Не удалось отправить: {str(e)}")

# ===== ЗАВЕРШЕНИЕ ЧАТА =====
def end_chat(user_id, reason="normal"):
    if user_id in storage.active_chats:
        chat_data = storage.active_chats[user_id]
        
        if reason == "user_used_command":
            bot.send_message(ADMIN_ID, f"⏹ Чат с {chat_data['user_name']} завершен (пользователь использовал команду)")
        else:
            bot.send_message(ADMIN_ID, f"⏹ Чат с {chat_data['user_name']} завершен")
            bot.send_message(user_id, "⏹ Переписка завершена администратором.")
        
        del storage.active_chats[user_id]
        storage.save_data()

@bot.message_handler(commands=['stop'])
def stop_chat_command(message):
    if not is_admin(message.from_user.id):
        return
    
    active_user_id = None
    for user_id, chat_data in storage.active_chats.items():
        if chat_data['admin_id'] == ADMIN_ID:
            active_user_id = user_id
            break
    
    if active_user_id:
        end_chat(active_user_id)
    else:
        bot.send_message(ADMIN_ID, "❌ Нет активных чатов")

# ===== КОМАНДЫ БАНОВ =====
@bot.message_handler(commands=['ban'])
def ban_command(message):
    if not is_admin(message.from_user.id):
        return
    
    if len(message.text.split()) < 2:
        bot.send_message(ADMIN_ID, "Используйте: /ban @username или /ban ID")
        return
    
    target = message.text.split(maxsplit=1)[1]
    
    user_id = None
    if target.startswith('@'):
        username = target[1:]
        for uid, profile in storage.user_profiles.items():
            if profile['username'].lower() == username.lower():
                user_id = uid
                break
    elif target.isdigit():
        user_id = int(target)
    
    if not user_id:
        bot.send_message(ADMIN_ID, f"❌ Пользователь не найден")
        return
    
    if user_id == ADMIN_ID:
        bot.send_message(ADMIN_ID, "❌ Нельзя забанить себя")
        return
    
    storage.banned_users.add(user_id)
    
    if user_id in storage.active_chats:
        end_chat(user_id)
    
    bot.send_message(ADMIN_ID, f"✅ Пользователь {target} забанен.")
    storage.save_data()

@bot.message_handler(commands=['unban'])
def unban_command(message):
    if not is_admin(message.from_user.id):
        return
    
    if len(message.text.split()) < 2:
        bot.send_message(ADMIN_ID, "Используйте: /unban @username или /unban ID")
        return
    
    target = message.text.split(maxsplit=1)[1]
    
    user_id = None
    if target.startswith('@'):
        username = target[1:]
        for uid in storage.banned_users:
            profile = storage.user_profiles.get(uid, {})
            if profile.get('username', '').lower() == username.lower():
                user_id = uid
                break
    elif target.isdigit():
        user_id = int(target)
    
    if user_id and user_id in storage.banned_users:
        storage.banned_users.remove(user_id)
        bot.send_message(ADMIN_ID, f"✅ Пользователь {target} разбанен.")
        storage.save_data()
    else:
        bot.send_message(ADMIN_ID, f"❌ Пользователь не найден")

# ===== ЗАПУСК =====
if __name__ == '__main__':
    print("=" * 50)
    print(f"🤖 Бот запущен | Админ: {ADMIN_ID}")
    print(f"👥 Пользователей: {len(storage.user_profiles)}")
    print(f"📨 Вопросов: {len(storage.questions)}")
    print(f"🚫 Забанено: {len(storage.banned_users)}")
    print("=" * 50)
    
    bot.polling(none_stop=True)
