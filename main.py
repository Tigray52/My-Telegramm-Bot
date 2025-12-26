import telebot
import os
import json
import re
import time
from datetime import datetime, timedelta
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
        self.user_cooldowns = {}  # {user_id: {'question': timestamp, 'chat_request': timestamp}}
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
                    self.user_cooldowns = data.get('cooldowns', {})
        except:
            pass
    
    def save_data(self):
        data = {
            'questions': self.questions,
            'banned_users': list(self.banned_users),
            'user_profiles': self.user_profiles,
            'counter': self.question_counter,
            'cooldowns': self.user_cooldowns
        }
        with open('storage.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

storage = Storage()

# Константы
CHAT_MESSAGE_LIMIT = 100
QUESTION_LIMIT = 400
QUESTION_COOLDOWN = 30  # секунд
CHAT_REQUEST_COOLDOWN = 60  # секунд

# Список типов контента
CONTENT_TYPES = {
    1: "Сообщения",
    2: "Голосовые", 
    3: "Фото",
    4: "GIF",
    5: "Файлы",
    6: "Кружочки"
}

# ===== ПРОВЕРКИ =====
def is_admin(user_id):
    return user_id == ADMIN_ID

def is_user_in_chat(user_id):
    return user_id in storage.active_chats

def check_cooldown(user_id, action_type):
    """Проверяет cooldown для действий"""
    now = time.time()
    
    if user_id not in storage.user_cooldowns:
        storage.user_cooldowns[user_id] = {}
        return True
    
    last_action = storage.user_cooldowns[user_id].get(action_type, 0)
    
    if action_type == 'question':
        cooldown_time = QUESTION_COOLDOWN
    elif action_type == 'chat_request':
        cooldown_time = CHAT_REQUEST_COOLDOWN
    else:
        return True
    
    if now - last_action < cooldown_time:
        remaining = int(cooldown_time - (now - last_action))
        return False, remaining
    
    return True, 0

def set_cooldown(user_id, action_type):
    """Устанавливает cooldown"""
    if user_id not in storage.user_cooldowns:
        storage.user_cooldowns[user_id] = {}
    
    storage.user_cooldowns[user_id][action_type] = time.time()
    storage.save_data()

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
            'warnings': 0,
            'last_question_time': 0,
            'last_chat_request_time': 0
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
        # Проверяем cooldown
        cooldown_check, remaining = check_cooldown(user_id, 'question')
        if not cooldown_check:
            bot.send_message(user_id, f"⏳ Следующий вопрос можно задать через {remaining} секунд.")
            return
        
        msg = bot.send_message(
            user_id,
            "📝 *Напишите ваш вопрос:*\n\n"
            f"Максимум {QUESTION_LIMIT} символов.\n"
            "Можно прикрепить фото (не GIF) или голосовое сообщение.\n\n"
            "⚠️ *Что бы отменить запрос напишите /cancel*",
            parse_mode='Markdown',
            reply_markup=types.ReplyKeyboardRemove()
        )
        bot.register_next_step_handler(msg, process_question)
        
    elif message.text == '💬 Прямая переписка':
        # Проверяем cooldown
        cooldown_check, remaining = check_cooldown(user_id, 'chat_request')
        if not cooldown_check:
            bot.send_message(user_id, f"⏳ Следующий запрос переписки можно отправить через {remaining} секунд.")
            return
        
        request_chat(message)
    elif message.text == 'ℹ️ Помощь':
        show_user_help(message)

def process_question(message):
    user_id = message.from_user.id
    
    # Проверяем отмену
    if message.text and message.text.strip() == '/cancel':
        bot.send_message(user_id, "❌ Отправка вопроса отменена.")
        show_user_menu(user_id)
        return
    
    # Устанавливаем cooldown
    set_cooldown(user_id, 'question')
    
    # Проверяем тип контента
    has_media = False
    media_type = None
    media_info = ""
    question_text = ""
    
    if message.content_type == 'text':
        # Проверка длины текста
        if len(message.text.strip()) > QUESTION_LIMIT:
            bot.send_message(user_id, f"❌ Вопрос слишком длинный (макс. {QUESTION_LIMIT} символов).")
            show_user_menu(user_id)
            return
        
        question_text = message.text.strip()
        if not question_text or len(question_text) < 5:
            bot.send_message(user_id, "❌ Вопрос слишком короткий.")
            show_user_menu(user_id)
            return
            
    elif message.content_type == 'photo':
        has_media = True
        media_type = 'photo'
        media_info = "[Фото]"
        
        # Проверяем, не GIF (у фото есть несколько размеров)
        if message.text:
            question_text = message.text.strip()
        elif message.caption:
            question_text = message.caption.strip()
        
        # Проверяем длину подписи
        if question_text and len(question_text) > QUESTION_LIMIT:
            bot.send_message(user_id, f"❌ Подпись к фото слишком длинная (макс. {QUESTION_LIMIT} символов).")
            show_user_menu(user_id)
            return
            
    elif message.content_type == 'voice':
        has_media = True
        media_type = 'voice'
        media_info = "[Голосовое сообщение]"
        
        if message.caption:
            question_text = message.caption.strip()
            if len(question_text) > QUESTION_LIMIT:
                bot.send_message(user_id, f"❌ Подпись к голосовому слишком длинная (макс. {QUESTION_LIMIT} символов).")
                show_user_menu(user_id)
                return
    else:
        bot.send_message(user_id, "❌ Поддерживаются только текст, фото (не GIF) и голосовые сообщения.")
        show_user_menu(user_id)
        return
    
    # Сохраняем вопрос
    question_id = storage.question_counter
    username = storage.user_profiles[user_id]['username']
    
    question_data = {
        'id': question_id,
        'user_id': user_id,
        'username': username,
        'text': question_text,
        'time': datetime.now().strftime("%H:%M"),
        'date': datetime.now().strftime("%d.%m.%Y"),
        'status': 'pending',
        'admin_response': None,
        'has_media': has_media,
        'media_type': media_type,
        'media_info': media_info
    }
    
    if has_media and message.content_type == 'photo':
        question_data['photo_file_id'] = message.photo[-1].file_id
    elif has_media and message.content_type == 'voice':
        question_data['voice_file_id'] = message.voice.file_id
    
    storage.questions[question_id] = question_data
    storage.user_profiles[user_id]['questions_sent'] += 1
    storage.question_counter += 1
    
    # Уведомляем админа
    notify_admin_about_question(question_id, question_data)
    
    # Подтверждение пользователю
    confirm_text = f"✅ *Вопрос #{question_id} отправлен!*\n\n"
    if has_media:
        confirm_text += f"{media_info}\n"
    confirm_text += "Администратор ответит в ближайшее время."
    
    bot.send_message(user_id, confirm_text, parse_mode='Markdown')
    
    show_user_menu(user_id)
    storage.save_data()

def request_chat(message):
    user_id = message.from_user.id
    username = storage.user_profiles[user_id]['username']
    
    # Устанавливаем cooldown
    set_cooldown(user_id, 'chat_request')
    
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
        f"ID: `{user_id}`\n"
        f"Время: {datetime.now().strftime('%H:%M:%S')}",
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
        f"• Максимум {QUESTION_LIMIT} символов\n"
        "• Можно прикрепить фото или голосовое\n"
        "• Cooldown: 30 секунд\n"
        "• /cancel - отмена\n\n"
        "*💬 Прямая переписка:*\n"
        "• Cooldown: 60 секунд\n"
        "• Админ может принять или отклонить\n\n"
        "*💬 В чате:*\n"
        f"• Максимум {CHAT_MESSAGE_LIMIT} символов\n"
        "• Не используйте команды\n"
        "• За спам - блокировка"
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
        f"⏰ {question_data['time']}"
    )
    
    if question_data['has_media']:
        notification += f"\n📎 {question_data['media_info']}"
    
    notification += f"\n\n💬 {text_preview}"
    
    # Отправляем медиа, если есть
    if question_data['has_media']:
        if question_data['media_type'] == 'photo' and 'photo_file_id' in question_data:
            bot.send_photo(ADMIN_ID, question_data['photo_file_id'], 
                         caption=notification, parse_mode='Markdown', reply_markup=markup)
            return
        elif question_data['media_type'] == 'voice' and 'voice_file_id' in question_data:
            bot.send_voice(ADMIN_ID, question_data['voice_file_id'], 
                         caption=notification, parse_mode='Markdown', reply_markup=markup)
            return
    
    bot.send_message(ADMIN_ID, notification, parse_mode='Markdown', reply_markup=markup)

# ===== АДМИН-ПАНЕЛЬ =====
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

# ===== КОМАНДА /MESSAGE С ОПЦИЯМИ =====
@bot.message_handler(commands=['Message'])
def message_command(message):
    """Отправка сообщения пользователю с опциями"""
    if not is_admin(message.from_user.id):
        return
    
    if len(message.text.split()) < 2:
        help_text = (
            "*Использование /Message:*\n\n"
            "`/Message [ID] текст`\n"
            "`/Message [ID, Имя] текст`\n"
            "`/Message [ID] {true} текст` - с рамками\n"
            "`/Message [ID] {false} текст` - без рамок\n\n"
            "*Примеры:*\n"
            "`/Message [123456789] Привет!`\n"
            "`/Message [123456789, Михаил] {false} Правила...`"
        )
        bot.send_message(ADMIN_ID, help_text, parse_mode='Markdown')
        return
    
    # Парсим команду
    full_text = message.text[8:].strip()  # Убираем "/Message "
    
    # Ищем параметры в []
    match = re.search(r'\[([^\]]+)\]\s*(.+)', full_text)
    if not match:
        bot.send_message(ADMIN_ID, "❌ Неверный формат.")
        return
    
    params = match.group(1).strip()
    rest_text = match.group(2).strip()
    
    # Проверяем наличие {true/false}
    frames_option = True  # По умолчанию с рамками
    if '{' in rest_text and '}' in rest_text:
        frames_match = re.search(r'\{([^}]+)\}\s*(.+)', rest_text)
        if frames_match:
            option = frames_match.group(1).strip().lower()
            message_text = frames_match.group(2).strip()
            
            if option == 'false':
                frames_option = False
        else:
            message_text = rest_text
    else:
        message_text = rest_text
    
    if not message_text:
        bot.send_message(ADMIN_ID, "❌ Введите текст сообщения.")
        return
    
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
    
    # Проверяем пользователя
    if user_id not in storage.user_profiles:
        bot.send_message(ADMIN_ID, f"❌ Пользователь с ID {user_id} не найден")
        return
    
    if user_id in storage.banned_users:
        bot.send_message(ADMIN_ID, f"⚠️ Пользователь {user_id} забанен")
        return
    
    # Форматируем сообщение
    if frames_option:
        formatted_message = (
            f"📨 *Сообщение от {admin_name}:*\n\n"
            f"╔═✦ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ✦═╗\n"
            f"   {message_text}\n"
            f"╚═✦ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ∙∙ ✦═╝\n\n"
            f"_Это автоматическое уведомление_"
        )
    else:
        formatted_message = (
            f"📨 *Сообщение от {admin_name}:*\n\n"
            f"{message_text}\n\n"
            f"_Это автоматическое уведомление_"
        )
    
    # Отправляем
    try:
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
        
        # Спрашиваем имя админа
        msg = bot.send_message(
            ADMIN_ID,
            f"💬 *Принят запрос на переписку*\n\n"
            f"Пользователь: {question['username']}\n\n"
            f"📝 *Как вас звать в этой переписке?*",
            parse_mode='Markdown'
        )
        
        bot.register_next_step_handler(msg, ask_admin_name_step2, user_id, question_id)
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

def ask_admin_name_step2(message, user_id, question_id):
    """Второй шаг - после имени спрашиваем о разрешенных типах контента"""
    admin_name = message.text.strip()[:20]
    
    if not admin_name:
        bot.send_message(ADMIN_ID, "❌ Имя не может быть пустым.")
        return
    
    # Сохраняем имя временно
    temp_data = {
        'admin_name': admin_name,
        'user_id': user_id,
        'question_id': question_id,
        'username': storage.questions[question_id]['username']
    }
    
    # Спрашиваем о разрешенных типах контента
    types_list = "\n".join([f"{num}. {name}" for num, name in CONTENT_TYPES.items()])
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    buttons = []
    for i in range(1, 7):
        buttons.append(types.KeyboardButton(str(i)))
    
    # Добавляем кнопки в несколько рядов
    for i in range(0, len(buttons), 3):
        markup.row(*buttons[i:i+3])
    
    msg = bot.send_message(
        ADMIN_ID,
        f"✅ Имя сохранено: *{admin_name}*\n\n"
        f"📋 *Что можно отправлять в чат?*\n"
        f"{types_list}\n\n"
        f"Выпишите номера через запятую (минимум 1):\n"
        f"*Пример:* 1,3,5",
        parse_mode='Markdown',
        reply_markup=markup
    )
    
    bot.register_next_step_handler(msg, ask_content_types_step3, temp_data)

def ask_content_types_step3(message, temp_data):
    """Третий шаг - обработка выбранных типов контента"""
    selected_nums = message.text.strip()
    
    # Очищаем клавиатуру
    bot.send_message(ADMIN_ID, "Обработка...", reply_markup=types.ReplyKeyboardRemove())
    
    # Парсим выбранные номера
    allowed_types = []
    try:
        nums = [int(n.strip()) for n in selected_nums.split(',')]
        for num in nums:
            if 1 <= num <= 6:
                allowed_types.append(num)
    except:
        bot.send_message(ADMIN_ID, "❌ Неверный формат. Используйте номера через запятую.")
        return
    
    if not allowed_types:
        bot.send_message(ADMIN_ID, "❌ Нужно выбрать минимум 1 тип контента.")
        return
    
    # Сортируем и убираем дубликаты
    allowed_types = sorted(set(allowed_types))
    
    # Получаем названия выбранных типов
    selected_names = [CONTENT_TYPES[num] for num in allowed_types]
    selected_text = ", ".join(selected_names)
    
    # Создаем чат
    storage.active_chats[temp_data['user_id']] = {
        'admin_id': ADMIN_ID,
        'user_name': temp_data['username'],
        'admin_name': temp_data['admin_name'],
        'start_time': datetime.now().isoformat(),
        'question_id': temp_data['question_id'],
        'allowed_types': allowed_types,
        'selected_text': selected_text
    }
    
    # Уведомляем пользователя
    bot.send_message(
        temp_data['user_id'],
        f"💬 *Переписка начата!*\n\n"
        f"✅ Администратор принял ваш запрос.\n\n"
        f"👨‍💼 *{temp_data['admin_name']} (Администратор)*\n"
        f"📋 *Что можно отправлять:* {selected_text}\n\n"
        f"Теперь вы можете общаться напрямую.\n"
        f"⚠️ *Ограничение:* {CHAT_MESSAGE_LIMIT} символов на сообщение",
        parse_mode='Markdown'
    )
    
    # Уведомляем админа
    bot.send_message(
        ADMIN_ID,
        f"💬 *Чат начат!*\n\n"
        f"С пользователем: {temp_data['username']}\n"
        f"Ваше имя в чате: *{temp_data['admin_name']}*\n"
        f"Разрешено отправлять: *{selected_text}*\n\n"
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
    user_id = message.from_user.id
    chat_data = storage.active_chats.get(user_id)
    
    if not chat_data:
        return
    
    # Проверяем команды
    if message.text and message.text.startswith('/'):
        end_chat(user_id, "user_used_command")
        bot.send_message(user_id, "❌ Диалог завершен, так как вы использовали команду.")
        return
    
    # Проверяем разрешенные типы контента
    allowed_types = chat_data.get('allowed_types', [1])  # По умолчанию только текст
    
    # Проверяем тип контента
    content_type_map = {
        'text': 1,
        'voice': 2,
        'photo': 3,
        'animation': 4,  # GIF
        'document': 5,   # Файлы
        'video_note': 6  # Кружочки
    }
    
    current_type = content_type_map.get(message.content_type, 1)
    
    if current_type not in allowed_types:
        type_name = CONTENT_TYPES.get(current_type, "этот тип контента")
        bot.send_message(user_id, f"❌ Администратор запретил отправку {type_name}.")
        return
    
    # Проверяем длину для текстовых сообщений
    if message.content_type == 'text' and len(message.text.strip()) > CHAT_MESSAGE_LIMIT:
        # В диалоге просто уведомляем, не отменяем
        bot.send_message(user_id, f"⚠️ Сообщение слишком длинное ({len(message.text)}/{CHAT_MESSAGE_LIMIT} символов)")
        # Но все равно пересылаем
        pass
    
    sender = chat_data['user_name']
    
    if message.content_type == 'text':
        text_to_send = message.text[:500]  # Обрезаем для безопасности
        bot.send_message(
            ADMIN_ID,
            f"👤 *{sender}:*\n{text_to_send}",
            parse_mode='Markdown'
        )
    elif message.content_type == 'voice':
        bot.send_voice(
            ADMIN_ID,
            message.voice.file_id,
            caption=f"👤 {sender}: [Голосовое]"
        )
    elif message.content_type == 'photo':
        caption = f"👤 {sender}: [Фото]"
        if message.caption:
            caption += f"\n{message.caption[:100]}"
        bot.send_photo(
            ADMIN_ID,
            message.photo[-1].file_id,
            caption=caption
        )
    elif message.content_type == 'animation':  # GIF
        bot.send_animation(
            ADMIN_ID,
            message.animation.file_id,
            caption=f"👤 {sender}: [GIF]"
        )
    elif message.content_type == 'document':
        bot.send_document(
            ADMIN_ID,
            message.document.file_id,
            caption=f"👤 {sender}: {message.document.file_name}"
        )
    elif message.content_type == 'video_note':
        bot.send_video_note(
            ADMIN_ID,
            message.video_note.file_id
        )
        bot.send_message(ADMIN_ID, f"👤 {sender}: [Кружочек]")

@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.chat.id == ADMIN_ID)
def handle_admin_message(message):
    active_user_id = None
    for user_id, chat_data in storage.active_chats.items():
        if chat_data['admin_id'] == ADMIN_ID:
            active_user_id = user_id
            break
    
    if not active_user_id:
        if message.text and message.text.startswith('/'):
            return
        return
    
    chat_data = storage.active_chats[active_user_id]
    
    if message.text and message.text.startswith('/stop'):
        end_chat(active_user_id)
        return
    
    try:
        if message.content_type == 'text':
            # Проверяем длину сообщения от админа
            if len(message.text.strip()) > CHAT_MESSAGE_LIMIT:
                bot.send_message(ADMIN_ID, f"⚠️ Сообщение слишком длинное ({len(message.text)}/{CHAT_MESSAGE_LIMIT} символов)")
            
            bot.send_message(
                active_user_id,
                f"👨‍💼 *{chat_data['admin_name']} (Администратор):*\n{message.text}",
                parse_mode='Markdown'
            )
        elif message.content_type == 'voice':
            bot.send_voice(
                active_user_id,
                message.voice.file_id,
                caption=f"👨‍💼 {chat_data['admin_name']} (Администратор): [Голосовое]"
            )
        elif message.content_type == 'photo':
            caption = f"👨‍💼 {chat_data['admin_name']} (Администратор): [Фото]"
            if message.caption:
                caption += f"\n{message.caption}"
            bot.send_photo(
                active_user_id,
                message.photo[-1].file_id,
                caption=caption
            )
        elif message.content_type == 'animation':
            bot.send_animation(
                active_user_id,
                message.animation.file_id,
                caption=f"👨‍💼 {chat_data['admin_name']} (Администратор): [GIF]"
            )
        elif message.content_type == 'document':
            bot.send_document(
                active_user_id,
                message.document.file_id,
                caption=f"👨‍💼 {chat_data['admin_name']} (Администратор): {message.document.file_name}"
            )
        elif message.content_type == 'video_note':
            bot.send_video_note(
                active_user_id,
                message.video_note.file_id
            )
            bot.send_message(active_user_id, f"👨‍💼 {chat_data['admin_name']} (Администратор): [Кружочек]")
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

# ===== ЗАПУСК =====
if __name__ == '__main__':
    print("=" * 50)
    print(f"🤖 Бот запущен | Админ: {ADMIN_ID}")
    print(f"👥 Пользователей: {len(storage.user_profiles)}")
    print(f"📨 Вопросов: {len(storage.questions)}")
    print(f"🚫 Забанено: {len(storage.banned_users)}")
    print(f"💬 Лимит чата: {CHAT_MESSAGE_LIMIT} символов")
    print(f"📝 Лимит вопроса: {QUESTION_LIMIT} символов")
    print("=" * 50)
    
    bot.polling(none_stop=True)
