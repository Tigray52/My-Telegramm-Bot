import telebot
import os
import json
import time
from datetime import datetime
from telebot import types

bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))
ADMIN_ID = 6337781618

# Хранилище данных
class Storage:
    def __init__(self):
        self.questions = {}  # Все вопросы {id: data}
        self.active_chats = {}  # Активные переписки {user_id: data}
        self.banned_users = set()  # Забаненные ID
        self.user_profiles = {}  # Профили пользователей
        self.question_counter = 1
        self.load_data()
    
    def load_data(self):
        try:
            if os.path.exists('storage.json'):
                with open('storage.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.questions = data.get('questions', {})
                    self.banned_users = set(data.get('banned_users', []))
                    self.user_profiles = data.get('user_profiles', {})
                    self.question_counter = data.get('counter', 1)
                    # Преобразуем ключи в int
                    self.questions = {int(k): v for k, v in self.questions.items()}
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

# ===== ПРОВЕРКА ПРАВ =====
def is_admin(user_id):
    return user_id == ADMIN_ID

# ===== ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =====
@bot.message_handler(commands=['start'])
def start(message):
    """Начало работы для пользователя"""
    user_id = message.from_user.id
    
    # Проверка бана
    if user_id in storage.banned_users:
        bot.send_message(user_id, "🚫 Вы заблокированы администратором.")
        return
    
    # Если это админ - отправляем в админ-панель
    if is_admin(user_id):
        bot.send_message(user_id, "👑 Вы администратор. Используйте /admin")
        return
    
    # Сохраняем профиль
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    if user_id not in storage.user_profiles:
        storage.user_profiles[user_id] = {
            'username': username,
            'first_name': message.from_user.first_name,
            'joined': datetime.now().isoformat(),
            'questions_sent': 0,
            'chats_started': 0
        }
    
    # Показываем меню
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
    """Обработка меню пользователя"""
    user_id = message.from_user.id
    
    # Проверка бана
    if user_id in storage.banned_users:
        return
    
    # Блокировка для админа
    if is_admin(user_id):
        bot.send_message(user_id, "❌ Администраторы не могут использовать эти функции.")
        return
    
    if message.text == '📨 Задать вопрос':
        ask_question_step1(message)
    elif message.text == '💬 Прямая переписка':
        request_chat(message)
    elif message.text == 'ℹ️ Помощь':
        show_user_help(message)

def ask_question_step1(message):
    """Первый шаг - просим ввести вопрос"""
    user_id = message.from_user.id
    msg = bot.send_message(
        user_id,
        "📝 *Напишите ваш вопрос:*\n\nАдминистратор ответит в течение 24 часов.",
        parse_mode='Markdown',
        reply_markup=types.ReplyKeyboardRemove()
    )
    bot.register_next_step_handler(msg, ask_question_step2)

def ask_question_step2(message):
    """Второй шаг - сохраняем вопрос"""
    user_id = message.from_user.id
    
    # Проверяем содержание сообщения
    if message.text and len(message.text.strip()) < 2:
        bot.send_message(user_id, "❌ Вопрос слишком короткий. Попробуйте снова.")
        ask_question_step1(message)
        return
    
    # Сохраняем вопрос
    question_id = storage.question_counter
    username = storage.user_profiles[user_id]['username']
    
    storage.questions[question_id] = {
        'id': question_id,
        'user_id': user_id,
        'username': username,
        'text': message.text,
        'time': datetime.now().strftime("%H:%M"),
        'date': datetime.now().strftime("%d.%m.%Y"),
        'status': 'pending',  # pending, answered, deleted
        'admin_response': None
    }
    
    storage.user_profiles[user_id]['questions_sent'] += 1
    storage.question_counter += 1
    
    # Уведомляем админа
    notify_admin_about_question(question_id, storage.questions[question_id])
    
    # Подтверждение пользователю
    bot.send_message(
        user_id,
        f"✅ *Вопрос #{question_id} отправлен!*\n\nАдминистратор ответит в ближайшее время.",
        parse_mode='Markdown'
    )
    
    # Возвращаем меню
    show_user_menu(user_id)
    storage.save_data()

def request_chat(message):
    """Запрос прямой переписки"""
    user_id = message.from_user.id
    username = storage.user_profiles[user_id]['username']
    
    # Создаем запрос на переписку
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
    
    # Уведомляем админа с кнопками
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton('✅ Принять чат', callback_data=f'accept_chat_{chat_request_id}'),
        types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_user_{user_id}')
    )
    
    bot.send_message(
        ADMIN_ID,
        f"💬 *Запрос на переписку #{chat_request_id}*\n"
        f"От: {username}\n"
        f"ID: `{user_id}`\n"
        f"Время: {datetime.now().strftime('%H:%M')}",
        parse_mode='Markdown',
        reply_markup=markup
    )
    
    bot.send_message(user_id, "✅ Запрос на переписку отправлен администратору!")
    show_user_menu(user_id)
    storage.save_data()

def show_user_help(message):
    """Помощь для пользователя"""
    help_text = (
        "ℹ️ *Помощь*\n\n"
        "*📨 Задать вопрос:*\n"
        "1. Нажмите кнопку 'Задать вопрос'\n"
        "2. Напишите ваш вопрос\n"
        "3. Администратор ответит в течение 24 часов\n\n"
        
        "*💬 Прямая переписка:*\n"
        "1. Нажмите кнопку 'Прямая переписка'\n"
        "2. Администратор примет ваш запрос\n"
        "3. Вы сможете общаться в реальном времени\n\n"
        
        "*Правила:*\n"
        "• Уважайте администратора\n"
        "• Не спамьте\n"
        "• Ожидайте ответа\n\n"
        
        "*Важно:*\n"
        "Администратор вправе заблокировать вас за нарушение правил."
    )
    
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

def show_user_menu(user_id):
    """Показывает меню пользователя"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📨 Задать вопрос'),
        types.KeyboardButton('💬 Прямая переписка'),
        types.KeyboardButton('ℹ️ Помощь')
    )
    bot.send_message(user_id, "Главное меню:", reply_markup=markup)

# ===== УВЕДОМЛЕНИЕ АДМИНА =====
def notify_admin_about_question(question_id, question_data):
    """Отправляет уведомление админу о новом вопросе"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('✏️ Ответить', callback_data=f'answer_{question_id}'),
        types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_{question_id}')
    )
    
    text_preview = question_data['text'][:100] + "..." if len(question_data['text']) > 100 else question_data['text']
    
    notification = (
        f"📨 *Новый вопрос #{question_id}*\n\n"
        f"👤 От: {question_data['username']}\n"
        f"🆔 ID: `{question_data['user_id']}`\n"
        f"⏰ Время: {question_data['time']}\n\n"
        f"💬 Текст: {text_preview}"
    )
    
    bot.send_message(ADMIN_ID, notification, parse_mode='Markdown', reply_markup=markup)

# ===== АДМИН-ПАНЕЛЬ =====
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    """Панель администратора"""
    if not is_admin(message.from_user.id):
        return
    
    # Статистика
    pending_count = len([q for q in storage.questions.values() if q.get('status') == 'pending'])
    
    text = (
        f"👑 *Панель администратора*\n\n"
        f"📊 *Статистика:*\n"
        f"• Вопросов в ожидании: {pending_count}\n"
        f"• Активных чатов: {len(storage.active_chats)}\n"
        f"• Всего пользователей: {len(storage.user_profiles)}\n"
        f"• Забанено: {len(storage.banned_users)}\n\n"
        f"🕐 Серверное время: {datetime.now().strftime('%H:%M:%S')}"
    )
    
    # Основные кнопки
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📋 Задачи (/Tasks)'),
        types.KeyboardButton('💬 Активные чаты'),
        types.KeyboardButton('🚫 Управление банами'),
        types.KeyboardButton('📊 Статистика'),
        types.KeyboardButton('🔄 Обновить'),
        types.KeyboardButton('❓ Помощь')
    )
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == '📋 Задачи (/Tasks)' and is_admin(m.from_user.id))
def show_tasks(message):
    """Показывает все задачи (вопросы без ответов)"""
    pending_questions = [q for q in storage.questions.values() if q.get('status') == 'pending']
    
    if not pending_questions:
        bot.send_message(ADMIN_ID, "✅ *Все вопросы обработаны!*\n\nНет задач в ожидании.", parse_mode='Markdown')
        return
    
    # Отправляем сводку
    bot.send_message(
        ADMIN_ID,
        f"📋 *Задачи на рассмотрение*\n\n"
        f"Всего неотвеченных вопросов: *{len(pending_questions)}*",
        parse_mode='Markdown'
    )
    
    # Отправляем каждый вопрос с кнопками
    for question in pending_questions:
        text_preview = question['text'][:80] + "..." if len(question['text']) > 80 else question['text']
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(f'Ответить #{question["id"]}', callback_data=f'answer_{question["id"]}'),
            types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_{question["id"]}')
        )
        
        question_text = (
            f"🔔 *Задача #{question['id']}*\n"
            f"👤 {question['username']} (`{question['user_id']}`)\n"
            f"⏰ {question['time']} | {question['date']}\n\n"
            f"💬 {text_preview}"
        )
        
        bot.send_message(ADMIN_ID, question_text, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['Tasks'])
def tasks_command(message):
    """Команда /Tasks"""
    if is_admin(message.from_user.id):
        show_tasks(message)

@bot.message_handler(func=lambda m: m.text == '🚫 Управление банами' and is_admin(m.from_user.id))
def manage_bans(message):
    """Управление банами"""
    if not storage.banned_users:
        bot.send_message(ADMIN_ID, "✅ Нет забаненных пользователей.")
        return
    
    text = "🚫 *Забаненные пользователи:*\n\n"
    for user_id in storage.banned_users:
        username = storage.user_profiles.get(user_id, {}).get('username', f'ID: {user_id}')
        text += f"• {username} (`{user_id}`)\n"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('🔄 Обновить список', callback_data='refresh_bans'))
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == '📊 Статистика' and is_admin(m.from_user.id))
def show_admin_stats(message):
    """Детальная статистика"""
    pending_count = len([q for q in storage.questions.values() if q.get('status') == 'pending'])
    answered_count = len([q for q in storage.questions.values() if q.get('status') == 'answered'])
    chat_requests = len([q for q in storage.questions.values() if q.get('type') == 'chat_request'])
    
    text = (
        f"📊 *Детальная статистика*\n\n"
        f"📨 *Вопросы:*\n"
        f"• Всего: {len(storage.questions)}\n"
        f"• В ожидании: {pending_count}\n"
        f"• Отвечено: {answered_count}\n"
        f"• Запросов чата: {chat_requests}\n\n"
        
        f"👥 *Пользователи:*\n"
        f"• Зарегистрировано: {len(storage.user_profiles)}\n"
        f"• Забанено: {len(storage.banned_users)}\n\n"
        
        f"💬 *Чаты:*\n"
        f"• Активные: {len(storage.active_chats)}\n\n"
        
        f"🕐 *Время сервера:* {datetime.now().strftime('%H:%M:%S')}"
    )
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == '❓ Помощь' and is_admin(m.from_user.id))
def show_admin_help(message):
    """Помощь для админа"""
    help_text = (
        "👑 *Помощь для администратора*\n\n"
        
        "*Основные команды:*\n"
        "• /admin - Открыть панель\n"
        "• /Tasks - Показать все задачи\n"
        "• /ban @username - Забанить\n"
        "• /unban @username - Разбанить\n\n"
        
        "*Кнопки панели:*\n"
        "• 📋 Задачи - Все вопросы без ответов\n"
        "• 💬 Активные чаты - Текущие переписки\n"
        "• 🚫 Управление банами - Список забаненных\n"
        "• 📊 Статистика - Подробная аналитика\n"
        "• 🔄 Обновить - Обновить панель\n\n"
        
        "*Работа с вопросами:*\n"
        "1. Нажмите '📋 Задачи'\n"
        "2. Выберите вопрос\n"
        "3. Нажмите 'Ответить' или 'Забанить'\n"
        "4. Для ответа напишите: `номер. текст ответа`\n\n"
        
        "*Пример:*\n"
        "`1. Здравствуйте! Ответ на ваш вопрос...`"
    )
    
    bot.send_message(ADMIN_ID, help_text, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == '🔄 Обновить' and is_admin(m.from_user.id))
def refresh_admin(message):
    """Обновление админ-панели"""
    admin_panel(message)

# ===== ОБРАБОТКА CALLBACK =====
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    """Обработка всех callback-кнопок"""
    
    # Принятие чата
    if call.data.startswith('accept_chat_'):
        question_id = int(call.data.replace('accept_chat_', ''))
        
        if question_id not in storage.questions:
            bot.answer_callback_query(call.id, "❌ Запрос устарел")
            return
        
        question = storage.questions[question_id]
        user_id = question['user_id']
        
        # Помечаем как принятый
        storage.questions[question_id]['status'] = 'accepted'
        
        # Спрашиваем имя админа
        msg = bot.send_message(
            ADMIN_ID,
            f"💬 *Принят запрос на переписку*\n\n"
            f"Пользователь: {question['username']}\n\n"
            f"📝 *Как вас звать в этой переписке?*\n"
            f"Напишите имя (например: Антон, Поддержка):",
            parse_mode='Markdown'
        )
        
        bot.register_next_step_handler(msg, process_admin_name, user_id, question_id)
        bot.answer_callback_query(call.id, "✅ Запрос принят")
    
    # Бан пользователя
    elif call.data.startswith('ban_') or call.data.startswith('ban_user_'):
        if call.data.startswith('ban_'):
            question_id = int(call.data.replace('ban_', ''))
            if question_id not in storage.questions:
                bot.answer_callback_query(call.id, "❌ Вопрос не найден")
                return
            user_id = storage.questions[question_id]['user_id']
        else:
            user_id = int(call.data.replace('ban_user_', ''))
        
        # Баним пользователя
        storage.banned_users.add(user_id)
        
        # Завершаем активный чат, если есть
        if user_id in storage.active_chats:
            del storage.active_chats[user_id]
        
        # Уведомляем админа
        username = storage.user_profiles.get(user_id, {}).get('username', f'ID: {user_id}')
        bot.send_message(ADMIN_ID, f"🚫 Пользователь {username} забанен.")
        
        # Уведомляем пользователя
        try:
            bot.send_message(user_id, "🚫 Вы были заблокированы администратором.")
        except:
            pass
        
        bot.answer_callback_query(call.id, "✅ Пользователь забанен")
        storage.save_data()
    
    # Ответ на вопрос
    elif call.data.startswith('answer_'):
        question_id = int(call.data.replace('answer_', ''))
        
        if question_id not in storage.questions:
            bot.answer_callback_query(call.id, "❌ Вопрос не найден")
            return
        
        question = storage.questions[question_id]
        
        # Просим админа ввести ответ
        msg = bot.send_message(
            ADMIN_ID,
            f"✏️ *Ответ на вопрос #{question_id}*\n\n"
            f"От: {question['username']}\n"
            f"Вопрос: {question['text']}\n\n"
            f"*Введите ваш ответ:*\n"
            f"`{question_id}. ваш текст ответа`",
            parse_mode='Markdown'
        )
        
        bot.register_next_step_handler(msg, process_admin_answer, question_id)
        bot.answer_callback_query(call.id, "✏️ Введите ответ...")

def process_admin_name(message, user_id, question_id):
    """Обработка имени админа для чата"""
    admin_name = message.text.strip()
    
    if not admin_name or len(admin_name) < 2:
        bot.send_message(ADMIN_ID, "❌ Имя слишком короткое.")
        return
    
    # Создаем активный чат
    storage.active_chats[user_id] = {
        'admin_id': ADMIN_ID,
        'user_name': storage.questions[question_id]['username'],
        'admin_name': admin_name,
        'start_time': datetime.now().isoformat(),
        'question_id': question_id
    }
    
    # Уведомляем пользователя
    bot.send_message(
        user_id,
        f"💬 *Переписка начата!*\n\n"
        f"✅ Администратор принял ваш запрос.\n\n"
        f"👨‍💼 *{admin_name} (Администратор)*\n"
        f"Теперь вы можете общаться напрямую.\n\n"
        f"Просто напишите сообщение — оно будет доставлено.",
        parse_mode='Markdown'
    )
    
    # Уведомляем админа
    bot.send_message(
        ADMIN_ID,
        f"💬 *Чат начат!*\n\n"
        f"С пользователем: {storage.active_chats[user_id]['user_name']}\n"
        f"Ваше имя в чате: *{admin_name}*\n\n"
        f"Теперь все ваши сообщения будут пересылаться пользователю.\n"
        f"Используйте /stop для завершения чата.",
        parse_mode='Markdown'
    )
    
    storage.save_data()

def process_admin_answer(message, question_id):
    """Обработка ответа админа на вопрос"""
    if question_id not in storage.questions:
        bot.send_message(ADMIN_ID, "❌ Вопрос не найден")
        return
    
    question = storage.questions[question_id]
    answer_text = message.text
    
    # Проверяем формат: "1. ответ"
    if '.' in answer_text:
        parts = answer_text.split('.', 1)
        if len(parts) == 2 and parts[0].strip().isdigit():
            answer = parts[1].strip()
        else:
            answer = answer_text
    else:
        answer = answer_text
    
    # Отправляем ответ пользователю
    try:
        bot.send_message(
            question['user_id'],
            f"📩 *Ответ на ваш вопрос #{question_id}:*\n\n{answer}",
            parse_mode='Markdown'
        )
        
        # Обновляем статус вопроса
        storage.questions[question_id]['status'] = 'answered'
        storage.questions[question_id]['admin_response'] = answer
        storage.questions[question_id]['answer_time'] = datetime.now().strftime("%H:%M")
        
        # Уведомляем админа
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
    
    # Формируем сообщение для админа
    sender = chat_data['user_name']
    
    if message.content_type == 'text':
        bot.send_message(
            ADMIN_ID,
            f"👤 *{sender}:*\n{message.text}",
            parse_mode='Markdown'
        )
    elif message.content_type == 'photo':
        bot.send_photo(
            ADMIN_ID,
            message.photo[-1].file_id,
            caption=f"👤 {sender}: [Фото]"
        )
    elif message.content_type == 'document':
        bot.send_document(
            ADMIN_ID,
            message.document.file_id,
            caption=f"👤 {sender}: {message.document.file_name}"
        )
    elif message.content_type == 'voice':
        bot.send_voice(
            ADMIN_ID,
            message.voice.file_id,
            caption=f"👤 {sender}: [Голосовое]"
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
            return  # Команды обрабатываются отдельно
        # Нет активного чата - просто игнорируем
        return
    
    chat_data = storage.active_chats[active_user_id]
    
    # Проверяем команды
    if message.text and message.text.startswith('/stop'):
        end_chat(active_user_id)
        return
    elif message.text and message.text.startswith('/clear'):
        clear_chat(active_user_id)
        return
    
    # Пересылаем сообщение пользователю
    try:
        if message.content_type == 'text':
            bot.send_message(
                active_user_id,
                f"👨‍💼 *{chat_data['admin_name']} (Администратор):*\n{message.text}",
                parse_mode='Markdown'
            )
        elif message.content_type == 'photo':
            bot.send_photo(
                active_user_id,
                message.photo[-1].file_id,
                caption=f"👨‍💼 {chat_data['admin_name']} (Администратор): [Фото]"
            )
        elif message.content_type == 'document':
            bot.send_document(
                active_user_id,
                message.document.file_id,
                caption=f"👨‍💼 {chat_data['admin_name']} (Администратор): {message.document.file_name}"
            )
        elif message.content_type == 'voice':
            bot.send_voice(
                active_user_id,
                message.voice.file_id,
                caption=f"👨‍💼 {chat_data['admin_name']} (Администратор): [Голосовое]"
            )
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Не удалось отправить сообщение: {str(e)}")

# ===== КОМАНДЫ УПРАВЛЕНИЯ =====
@bot.message_handler(commands=['stop'])
def stop_chat_command(message):
    """Завершение чата"""
    if not is_admin(message.from_user.id):
        return
    
    # Находим активный чат
    active_user_id = None
    for user_id, chat_data in storage.active_chats.items():
        if chat_data['admin_id'] == ADMIN_ID:
            active_user_id = user_id
            break
    
    if active_user_id:
        end_chat(active_user_id)
    else:
        bot.send_message(ADMIN_ID, "❌ Нет активных чатов")

def end_chat(user_id):
    """Завершает чат"""
    if user_id in storage.active_chats:
        chat_data = storage.active_chats[user_id]
        
        # Уведомляем пользователя
        bot.send_message(user_id, "⏹ Переписка завершена администратором.")
        
        # Уведомляем админа
        bot.send_message(
            ADMIN_ID,
            f"⏹ Чат с {chat_data['user_name']} завершен."
        )
        
        # Удаляем чат
        del storage.active_chats[user_id]
        storage.save_data()

@bot.message_handler(commands=['clear'])
def clear_chat_command(message):
    """Очистка чата"""
    if not is_admin(message.from_user.id):
        return
    
    # Находим активный чат
    active_user_id = None
    for user_id, chat_data in storage.active_chats.items():
        if chat_data['admin_id'] == ADMIN_ID:
            active_user_id = user_id
            break
    
    if active_user_id:
        clear_chat(active_user_id)
    else:
        bot.send_message(ADMIN_ID, "❌ Нет активных чатов")

def clear_chat(user_id):
    """Очищает текущий чат"""
    if user_id in storage.active_chats:
        # Просто уведомляем о начале "чистого" чата
        chat_data = storage.active_chats[user_id]
        
        bot.send_message(
            user_id,
            "🧹 *История текущей переписки очищена.*\n\n"
            "Чат продолжается с чистого листа.",
            parse_mode='Markdown'
        )
        
        bot.send_message(
            ADMIN_ID,
            f"🧹 Чат с {chat_data['user_name']} очищен."
        )

@bot.message_handler(commands=['ban'])
def ban_command(message):
    """Бан пользователя"""
    if not is_admin(message.from_user.id):
        return
    
    if len(message.text.split()) < 2:
        bot.send_message(ADMIN_ID, "Используйте: /ban @username или /ban ID")
        return
    
    target = message.text.split(maxsplit=1)[1]
    
    # Ищем пользователя
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
        bot.send_message(ADMIN_ID, f"❌ Пользователь не найден: {target}")
        return
    
    if user_id == ADMIN_ID:
        bot.send_message(ADMIN_ID, "❌ Нельзя забанить себя")
        return
    
    # Баним
    storage.banned_users.add(user_id)
    
    # Завершаем активный чат
    if user_id in storage.active_chats:
        end_chat(user_id)
    
    bot.send_message(ADMIN_ID, f"✅ Пользователь {target} забанен.")
    storage.save_data()

@bot.message_handler(commands=['unban'])
def unban_command(message):
    """Разбан пользователя"""
    if not is_admin(message.from_user.id):
        return
    
    if len(message.text.split()) < 2:
        bot.send_message(ADMIN_ID, "Используйте: /unban @username или /unban ID")
        return
    
    target = message.text.split(maxsplit=1)[1]
    
    # Ищем пользователя
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
        bot.send_message(ADMIN_ID, f"❌ Пользователь не найден или не забанен.")

# ===== ЗАПУСК =====
if __name__ == '__main__':
    print("=" * 50)
    print(f"🤖 Бот запущен")
    print(f"👑 Администратор: {ADMIN_ID}")
    print(f"📊 Пользователей: {len(storage.user_profiles)}")
    print(f"📨 Вопросов: {len(storage.questions)}")
    print(f"🚫 Забанено: {len(storage.banned_users)}")
    print("=" * 50)
    
    bot.polling(none_stop=True)
