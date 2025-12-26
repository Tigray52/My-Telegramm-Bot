import telebot
import os
import json
import re
import time
import urllib.parse
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
        self.user_cooldowns = {}
        self.admin_pending_answers = {}
        self.chat_settings = {}  # {user_id: {'allow_links': True/False, 'max_message_length': 400, 'max_messages': 15}}
        self.answer_counts = {}  # {question_id: count}
        self.chat_message_counts = {}  # {user_id: count} - счетчик сообщений в чате
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
                    self.chat_settings = data.get('chat_settings', {})
                    self.answer_counts = data.get('answer_counts', {})
                    self.chat_message_counts = data.get('chat_message_counts', {})
        except Exception as e:
            print(f"Ошибка загрузки данных: {e}")
    
    def save_data(self):
        data = {
            'questions': self.questions,
            'banned_users': list(self.banned_users),
            'user_profiles': self.user_profiles,
            'counter': self.question_counter,
            'cooldowns': self.user_cooldowns,
            'chat_settings': self.chat_settings,
            'answer_counts': self.answer_counts,
            'chat_message_counts': self.chat_message_counts
        }
        try:
            with open('storage.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения данных: {e}")
    
    def get_answer_count(self, question_id):
        """Возвращает количество ответов на вопрос"""
        return self.answer_counts.get(question_id, 0)
    
    def increment_answer_count(self, question_id):
        """Увеличивает счетчик ответов"""
        current = self.get_answer_count(question_id)
        self.answer_counts[question_id] = current + 1
        self.save_data()
    
    def increment_chat_message_count(self, user_id):
        """Увеличивает счетчик сообщений в чате"""
        if user_id not in self.chat_message_counts:
            self.chat_message_counts[user_id] = 0
        self.chat_message_counts[user_id] += 1
        self.save_data()
    
    def reset_chat_message_count(self, user_id):
        """Сбрасывает счетчик сообщений в чате"""
        if user_id in self.chat_message_counts:
            self.chat_message_counts[user_id] = 0
        self.save_data()
    
    def get_chat_message_count(self, user_id):
        """Получает текущее количество сообщений в чате"""
        return self.chat_message_counts.get(user_id, 0)

storage = Storage()

# Константы
QUESTION_LIMIT = 400
QUESTION_COOLDOWN = 30
CHAT_REQUEST_COOLDOWN = 60
MAX_ANSWERS_PER_QUESTION = 2
ANSWER_TIME_LIMIT_HOURS = 24

# Настройки по умолчанию для чата
DEFAULT_MAX_MESSAGE_LENGTH = 400
DEFAULT_MAX_MESSAGES = 15
MIN_MESSAGE_LENGTH = 30
MAX_MESSAGE_LENGTH = 500
MIN_MESSAGES = 5
MAX_MESSAGES = 150

# ===== ФУНКЦИИ ДЛЯ ОБРАБОТКИ ССЫЛОК =====
def mask_url(url):
    """Маскирует URL, оставляя первую букву домена и точку"""
    try:
        # Разделяем протокол и домен
        if '://' in url:
            protocol, rest = url.split('://', 1)
            # Сохраняем оригинальный регистр протокола
            original_protocol = url[:len(protocol)+3]
            rest_part = url[len(protocol)+3:]
        else:
            original_protocol = ''
            rest_part = url
        
        # Обрабатываем домен
        if '/' in rest_part:
            domain, path = rest_part.split('/', 1)
            path = '/' + path
        else:
            domain = rest_part
            path = ''
        
        # Маскируем домен
        if '.' in domain:
            parts = domain.split('.')
            if len(parts) >= 2:
                # Маскируем первую часть до точки
                first_part = parts[0]
                if len(first_part) > 1:
                    masked_first = first_part[0] + '•' * (len(first_part) - 1)
                else:
                    masked_first = first_part
                
                # Оставляем остальные части (домен) как есть
                masked_domain = masked_first + '.' + '.'.join(parts[1:])
            else:
                masked_domain = domain
        else:
            masked_domain = domain
        
        # Собираем обратно
        result = original_protocol + masked_domain + path
        return result
        
    except Exception as e:
        print(f"Ошибка маскировки URL {url}: {e}")
        return url

def find_and_mask_urls(text):
    """Находит и маскирует все URL в тексте (регистронезависимо)"""
    # Улучшенное регулярное выражение для поиска URL
    url_pattern = r'(?i)(https?://[^\s<>"]+|www\.[^\s<>"]+\.[^\s<>"]+)'
    urls = re.findall(url_pattern, text)
    
    if not urls:
        return text, 0
    
    masked_text = text
    for url in urls:
        # Нормализуем URL для обработки
        normalized_url = url
        if not url.lower().startswith(('http://', 'https://', 'www.')):
            normalized_url = 'http://' + url
        
        masked_url = mask_url(normalized_url)
        
        # Если исходный URL не начинался с http, убираем его из результата
        if not url.lower().startswith(('http://', 'https://')):
            if masked_url.startswith('http://'):
                masked_url = masked_url[7:]
            elif masked_url.startswith('https://'):
                masked_url = masked_url[8:]
        
        masked_text = masked_text.replace(url, masked_url)
    
    return masked_text, len(urls)

# ===== ПРОВЕРКИ =====
def is_admin(user_id):
    return user_id == ADMIN_ID

def is_user_in_chat(user_id):
    return user_id in storage.active_chats

def check_cooldown(user_id, action_type):
    now = time.time()
    
    if user_id not in storage.user_cooldowns:
        storage.user_cooldowns[user_id] = {}
        return True, 0
    
    last_action = storage.user_cooldowns[user_id].get(action_type, 0)
    
    if action_type == 'question':
        cooldown_time = QUESTION_COOLDOWN
    elif action_type == 'chat_request':
        cooldown_time = CHAT_REQUEST_COOLDOWN
    else:
        return True, 0
    
    if now - last_action < cooldown_time:
        remaining = int(cooldown_time - (now - last_action))
        return False, remaining
    
    return True, 0

def set_cooldown(user_id, action_type):
    if user_id not in storage.user_cooldowns:
        storage.user_cooldowns[user_id] = {}
    
    storage.user_cooldowns[user_id][action_type] = time.time()
    storage.save_data()

def can_answer_question(question_id):
    """Проверяет, можно ли отвечать на вопрос"""
    if question_id not in storage.questions:
        return False, "❌ Вопрос не найден"
    
    question = storage.questions[question_id]
    
    # Проверка времени (24 часа)
    try:
        question_date = datetime.strptime(question['date'], '%d.%m.%Y')
        question_time = datetime.strptime(question['time'], '%H:%M')
        question_datetime = datetime.combine(question_date.date(), question_time.time())
        
        if datetime.now() - question_datetime > timedelta(hours=ANSWER_TIME_LIMIT_HOURS):
            return False, f"⏰ Нельзя отвечать на вопросы старше {ANSWER_TIME_LIMIT_HOURS} часов"
    except:
        pass
    
    # Проверка количества ответов
    answer_count = storage.get_answer_count(question_id)
    if answer_count >= MAX_ANSWERS_PER_QUESTION:
        return False, f"❌ На этот вопрос уже отправлено {MAX_ANSWERS_PER_QUESTION} ответа"
    
    return True, ""

def check_chat_message_limit(user_id, message_length):
    """Проверяет лимит сообщений в чате"""
    if user_id not in storage.active_chats:
        return False, "❌ Чат не активен"
    
    chat_settings = storage.chat_settings.get(user_id, {})
    
    # Проверяем длину сообщения
    max_length = chat_settings.get('max_message_length', DEFAULT_MAX_MESSAGE_LENGTH)
    if message_length > max_length:
        return False, f"⚠️ Сообщение слишком длинное ({message_length}/{max_length} символов)"
    
    # Проверяем лимит сообщений
    max_messages = chat_settings.get('max_messages', DEFAULT_MAX_MESSAGES)
    current_messages = storage.get_chat_message_count(user_id)
    
    if current_messages >= max_messages:
        # Достигнут лимит - завершаем чат
        end_chat(user_id, "message_limit_reached")
        
        # Уведомляем пользователя
        bot.send_message(
            user_id,
            f"⏹ Переписка завершена автоматически.\n"
            f"Причина: достигнут лимит в {max_messages} сообщений."
        )
        
        # Уведомляем администратора
        bot.send_message(
            ADMIN_ID,
            f"⏹ Чат с {storage.active_chats[user_id]['user_name']} завершен.\n"
            f"Причина: достигнут лимит в {max_messages} сообщений."
        )
        
        return False, "message_limit_reached"
    
    return True, ""

# ===== КОМАНДЫ =====
@bot.message_handler(commands=['start'])
def start_command(message):
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

@bot.message_handler(commands=['help'])
def help_command(message):
    if is_admin(message.from_user.id):
        show_admin_help(message)
    else:
        show_user_help(message)

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
        "• Админ может принять или отклонить\n"
        "• Используйте /stop в чате для завершения\n\n"
        "*💬 В чате:*\n"
        "• Максимальная длина сообщения устанавливается админом\n"
        "• Максимальное количество сообщений устанавливается админом\n"
        "• /stop - завершить переписку\n"
        "• За спам - блокировка"
    )
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

def show_admin_help(message):
    help_text = (
        "👑 *Помощь для администратора*\n\n"
        "*Основные команды:*\n"
        "• /admin - Панель управления\n"
        "• /tasks - Список вопросов\n"
        "• /ban [ID] [причина] - Забанить с причиной\n"
        "• /unban [ID] - Разбанить\n"
        "• /stop - Завершить текущий чат\n"
        "• /message [ID] текст - Отправить сообщение\n"
        "• /full - Раскрыть ссылку в вопросе\n\n"
        
        "*Настройки чата:*\n"
        f"• Максимальная длина сообщения: {MIN_MESSAGE_LENGTH}-{MAX_MESSAGE_LENGTH} (по умолчанию {DEFAULT_MAX_MESSAGE_LENGTH})\n"
        f"• Максимальное количество сообщений: {MIN_MESSAGES}-{MAX_MESSAGES} (по умолчанию {DEFAULT_MAX_MESSAGES})\n\n"
        
        "*Формат /message:*\n"
        "`/message [123456789] Текст` - без рамок\n"
        "`/message [123456789, Имя] Текст` - с именем, без рамок\n"
        "`/message [123456789] {true} Текст` - с рамками\n\n"
        
        "*Формат ответа на вопрос:*\n"
        "`[Имя Фамилия] Ответ` - с именем\n"
        "`Просто ответ` - без имени\n\n"
        
        "*Бан с причиной:*\n"
        "`/ban 123456789 спам`\n"
        "`/ban 123456789 [нарушение правил]`\n\n"
        
        "*Команда /full:*\n"
        "• Можно использовать: `/full#1`, `/full #1` или `/full 1`\n"
        "• Или после нажатия кнопки 'Ответить'\n"
        "• Или кликнуть на [/full#1] в сообщении\n\n"
        
        "*Лимиты:*\n"
        f"• Максимум {MAX_ANSWERS_PER_QUESTION} ответа на вопрос\n"
        f"• Нельзя отвечать на вопросы старше {ANSWER_TIME_LIMIT_HOURS} часов"
    )
    bot.send_message(ADMIN_ID, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    user_id = message.from_user.id
    
    if is_user_in_chat(user_id):
        end_chat(user_id, "user_used_command")
        bot.send_message(user_id, "❌ Диалог завершен, так как вы использовали команду.")
        return
    
    # Отмена ожидания ответа администратора
    if user_id == ADMIN_ID and user_id in storage.admin_pending_answers:
        del storage.admin_pending_answers[user_id]
        bot.send_message(ADMIN_ID, "✅ Ответ отменен.")
    
    bot.send_message(user_id, "✅ Действие отменено.")
    start_command(message)

# ===== КОМАНДА /STOP ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =====
@bot.message_handler(commands=['stop'])
def stop_command(message):
    user_id = message.from_user.id
    
    if user_id in storage.banned_users:
        return
    
    # Если это администратор
    if is_admin(user_id):
        # Ищем активный чат админа
        active_user_id = None
        for uid, chat_data in storage.active_chats.items():
            if chat_data['admin_id'] == ADMIN_ID:
                active_user_id = uid
                break
        
        if active_user_id:
            end_chat(active_user_id, "admin_stop")
            bot.send_message(ADMIN_ID, "✅ Чат завершен")
        else:
            bot.send_message(ADMIN_ID, "❌ Нет активных чатов")
        return
    
    # Если это пользователь в чате
    if is_user_in_chat(user_id):
        end_chat(user_id, "user_stop")
        bot.send_message(user_id, "⏹ Вы завершили переписку.")
        return
    
    # Если пользователь не в чате
    bot.send_message(user_id, "❌ Вы не находитесь в активной переписке.")

@bot.message_handler(commands=['admin'])
def admin_command(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔ У вас нет доступа к этой команде")
        return
    
    admin_panel(message)

def admin_panel(message):
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
        types.KeyboardButton('📋 Задачи (/tasks)'),
        types.KeyboardButton('💬 Активные чаты'),
        types.KeyboardButton('🚫 Бан-лист'),
        types.KeyboardButton('🔄 Обновить')
    )
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['tasks'])
def tasks_command(message):
    if not is_admin(message.from_user.id):
        return
    
    show_tasks(message)

@bot.message_handler(commands=['ban'])
def ban_command(message):
    if not is_admin(message.from_user.id):
        return
    
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        bot.send_message(ADMIN_ID, "Используйте: /ban ID [причина]\nПример: `/ban 123456789 спам`", parse_mode='Markdown')
        return
    
    user_id_str = parts[1]
    reason = parts[2] if len(parts) > 2 else "Нарушение правил"
    
    if reason.startswith('[') and reason.endswith(']'):
        reason = reason[1:-1]
    
    if not user_id_str.isdigit():
        bot.send_message(ADMIN_ID, "❌ ID должен быть числом")
        return
    
    user_id = int(user_id_str)
    
    if user_id == ADMIN_ID:
        bot.send_message(ADMIN_ID, "❌ Нельзя забанить себя")
        return
    
    storage.banned_users.add(user_id)
    
    if user_id in storage.active_chats:
        end_chat(user_id, "ban")
    
    bot.send_message(ADMIN_ID, f"✅ Пользователь `{user_id}` забанен.\nПричина: {reason}")
    
    try:
        bot.send_message(user_id, f"🚫 Вы были заблокированы администратором.\nПричина: {reason}")
    except:
        pass
    
    storage.save_data()

@bot.message_handler(commands=['unban'])
def unban_command(message):
    if not is_admin(message.from_user.id):
        return
    
    if len(message.text.split()) < 2:
        bot.send_message(ADMIN_ID, "Используйте: /unban ID")
        return
    
    target = message.text.split(maxsplit=1)[1]
    
    if not target.isdigit():
        bot.send_message(ADMIN_ID, "❌ ID должен быть числом")
        return
    
    user_id = int(target)
    
    if user_id in storage.banned_users:
        storage.banned_users.remove(user_id)
        bot.send_message(ADMIN_ID, f"✅ Пользователь `{user_id}` разбанен.")
        storage.save_data()
    else:
        bot.send_message(ADMIN_ID, f"❌ Пользователь `{user_id}` не найден в бан-листе.")

# ===== КОМАНДА /MESSAGE =====
@bot.message_handler(commands=['message'])
def message_command(message):
    if not is_admin(message.from_user.id):
        return
    
    if len(message.text) <= 8:
        help_text = (
            "📨 *Использование /message:*\n\n"
            "`/message [ID] Текст` - без рамок\n"
            "`/message [ID, Имя] Текст` - с именем, без рамок\n"
            "`/message [ID] {true} Текст` - с рамками\n"
            "`/message [ID] {false} Текст` - без рамок\n\n"
            "*Примеры:*\n"
            "`/message [123456789] Привет!` - без рамок\n"
            "`/message [123456789, Михаил] Соблюдайте правила` - без рамок\n"
            "`/message [123456789] {true} Важное объявление` - с рамками"
        )
        bot.send_message(ADMIN_ID, help_text, parse_mode='Markdown')
        return
    
    full_text = message.text[8:].strip()
    
    match = re.search(r'\[([^\]]+)\]\s*(.+)', full_text)
    if not match:
        bot.send_message(ADMIN_ID, "❌ Неверный формат. Пример: `/message [123456789] Текст`", parse_mode='Markdown')
        return
    
    params = match.group(1).strip()
    rest_text = match.group(2).strip()
    
    frames_option = False
    message_text = rest_text
    
    if rest_text.startswith('{'):
        brace_end = rest_text.find('}')
        if brace_end != -1:
            option_text = rest_text[1:brace_end].strip().lower()
            message_text = rest_text[brace_end+1:].strip()
            
            if option_text == 'true':
                frames_option = True
    
    if not message_text:
        bot.send_message(ADMIN_ID, "❌ Введите текст сообщения.")
        return
    
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
    
    if user_id not in storage.user_profiles:
        bot.send_message(ADMIN_ID, f"❌ Пользователь с ID `{user_id}` не найден")
        return
    
    if user_id in storage.banned_users:
        bot.send_message(ADMIN_ID, f"⚠️ Пользователь `{user_id}` забанен")
        return
    
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
    
    try:
        bot.send_message(user_id, formatted_message, parse_mode='Markdown')
        bot.send_message(ADMIN_ID, f"✅ Сообщение отправлено пользователю `{user_id}`")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Ошибка: {str(e)}")

# ===== КОМАНДА /FULL (РАБОТАЕТ С /full#1 и /full #1) =====
@bot.message_handler(func=lambda m: m.text and m.text.startswith(('/full', '/Full')))
def full_command(message):
    if not is_admin(message.from_user.id):
        return
    
    text = message.text.strip()
    
    # Ищем ID вопроса в разных форматах:
    # 1. /full#1 (без пробела)
    # 2. /full #1 (с пробелом и решеткой)
    # 3. /full 1 (с пробелом, без решетки)
    
    question_id = None
    
    # Формат 1: /full#1
    match1 = re.search(r'^/full#(\d+)$', text, re.IGNORECASE)
    if match1:
        question_id = int(match1.group(1))
    
    # Формат 2: /full #1
    if not question_id:
        match2 = re.search(r'^/full\s+#(\d+)$', text, re.IGNORECASE)
        if match2:
            question_id = int(match2.group(1))
    
    # Формат 3: /full 1
    if not question_id:
        parts = text.split()
        if len(parts) == 2 and parts[1].isdigit():
            question_id = int(parts[1])
    
    if question_id:
        show_full_question_text(ADMIN_ID, question_id)
        return
    
    # Если администратор ожидает ответ на вопрос
    if ADMIN_ID in storage.admin_pending_answers:
        question_id = storage.admin_pending_answers[ADMIN_ID]
        show_full_question_text(ADMIN_ID, question_id)
        return
    
    # Если это ответ на сообщение
    if message.reply_to_message:
        reply_msg = message.reply_to_message
        question_id = None
        
        # Ищем ID вопроса в тексте сообщения
        match = re.search(r'#(\d+)', reply_msg.text or reply_msg.caption or '')
        if match:
            question_id = int(match.group(1))
        else:
            # Альтернативный поиск
            for qid, question in storage.questions.items():
                if question.get('masked_text', '') and reply_msg.text:
                    if question['masked_text'][:50] in reply_msg.text:
                        question_id = qid
                        break
        
        if question_id:
            show_full_question_text(ADMIN_ID, question_id)
            return
    
    bot.send_message(
        ADMIN_ID,
        "❌ Используйте команду:\n"
        "• `/full#1` (без пробела)\n"
        "• `/full #1` (с пробелом)\n"
        "• `/full 1` (с пробелом)\n"
        "• Или как ответ на вопрос\n"
        "• Или после нажатия кнопки 'Ответить'",
        parse_mode='Markdown'
    )

def show_full_question_text(admin_id, question_id):
    if question_id not in storage.questions:
        bot.send_message(admin_id, "❌ Вопрос не найден.")
        return
    
    question = storage.questions[question_id]
    
    # Отправляем полный текст с кликабельными ссылками
    full_text = f"📨 *Полный текст вопроса #{question_id}*\n\n"
    
    # Форматируем ID для копирования
    user_id_display = f"`{question['user_id']}`"
    if question['username']:
        full_text += f"👤 {question['username']} ({user_id_display})\n"
    else:
        full_text += f"👤 {user_id_display}\n"
    
    full_text += f"⏰ {question['time']} | {question['date']}\n\n"
    full_text += f"💬 {question['text']}"
    
    # Проверяем есть ли ссылки
    urls = re.findall(r'(?i)https?://[^\s<>"]+|www\.[^\s<>"]+\.[^\s<>"]+', question['text'])
    if urls:
        full_text += f"\n\n🔗 *Ссылки ({len(urls)}):*\n"
        for i, url in enumerate(urls, 1):
            full_text += f"{i}. {url}\n"
    
    # Отправляем без предпросмотра ссылок (но ссылки кликабельны)
    bot.send_message(admin_id, full_text, parse_mode='Markdown', disable_web_page_preview=True)
    
    # Продолжаем процесс ответа
    if admin_id in storage.admin_pending_answers:
        msg = bot.send_message(
            admin_id,
            f"Теперь введите ответ на вопрос #{question_id} (можно с медиа):\n"
            f"Используйте [Имя Фамилия] в начале для подписи",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_admin_answer, question_id)

# ===== ОБРАБОТКА КНОПОК МЕНЮ =====
@bot.message_handler(func=lambda m: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    
    if user_id in storage.banned_users:
        return
    
    if is_admin(user_id) and message.chat.id == ADMIN_ID:
        handle_admin_actions(message)
        return
    
    if is_user_in_chat(user_id):
        handle_user_in_chat(message)
        return
    
    if message.text in ['📨 Задать вопрос', '💬 Прямая переписка', 'ℹ️ Помощь']:
        handle_user_menu_buttons(message)

def handle_admin_actions(message):
    # Проверяем, если администратор ожидает ответ на вопрос
    if ADMIN_ID in storage.admin_pending_answers:
        # Проверяем, не является ли это командой /full
        if message.content_type == 'text' and message.text.strip().lower().startswith('/full'):
            question_id = storage.admin_pending_answers[ADMIN_ID]
            show_full_question_text(ADMIN_ID, question_id)
            return
        
        # Если не команда /full, обрабатываем как ответ
        question_id = storage.admin_pending_answers[ADMIN_ID]
        del storage.admin_pending_answers[ADMIN_ID]
        process_admin_answer(message, question_id)
        return
    
    if message.text in ['📋 Задачи (/tasks)', '💬 Активные чаты', '🚫 Бан-лист', '🔄 Обновить']:
        if message.text == '📋 Задачи (/tasks)':
            show_tasks(message)
        elif message.text == '💬 Активные чаты':
            show_active_chats(message)
        elif message.text == '🚫 Бан-лист':
            show_bans(message)
        elif message.text == '🔄 Обновить':
            admin_panel(message)
    else:
        handle_admin_to_user(message)

def handle_user_menu_buttons(message):
    user_id = message.from_user.id
    
    if message.text == '📨 Задать вопрос':
        cooldown_check, remaining = check_cooldown(user_id, 'question')
        if not cooldown_check:
            bot.send_message(user_id, f"⏳ Следующий вопрос можно задать через {remaining} секунд.")
            return
        
        ask_question_start(user_id)
        
    elif message.text == '💬 Прямая переписка':
        cooldown_check, remaining = check_cooldown(user_id, 'chat_request')
        if not cooldown_check:
            bot.send_message(user_id, f"⏳ Следующий запрос переписки можно отправить через {remaining} секунд.")
            return
        
        request_chat_flow(user_id)
        
    elif message.text == 'ℹ️ Помощь':
        show_user_help(message)

# ===== ОБРАБОТКА СООБЩЕНИЙ В ЧАТЕ =====
def handle_user_in_chat(message):
    user_id = message.from_user.id
    chat_data = storage.active_chats.get(user_id)
    
    if not chat_data:
        return
    
    # Увеличиваем счетчик сообщений
    storage.increment_chat_message_count(user_id)
    
    # Проверяем настройки чата
    allow_links = storage.chat_settings.get(user_id, {}).get('allow_links', True)
    sender = chat_data['user_name']
    
    try:
        if message.content_type == 'text':
            text = message.text.strip()
            
            # Проверяем длину сообщения
            chat_settings = storage.chat_settings.get(user_id, {})
            max_length = chat_settings.get('max_message_length', DEFAULT_MAX_MESSAGE_LENGTH)
            
            if len(text) > max_length:
                bot.send_message(user_id, f"⚠️ Сообщение слишком длинное ({len(text)}/{max_length} символов)")
                storage.chat_message_counts[user_id] -= 1  # Уменьшаем счетчик
                return
            
            # Проверяем лимит сообщений
            can_send, reason = check_chat_message_limit(user_id, len(text))
            if not can_send:
                if reason == "message_limit_reached":
                    # Чат уже завершен в функции check_chat_message_limit
                    return
                storage.chat_message_counts[user_id] -= 1  # Уменьшаем счетчик
                return
            
            # Проверяем есть ли ссылки
            urls = re.findall(r'(?i)https?://[^\s<>"]+|www\.[^\s<>"]+\.[^\s<>"]+', text)
            
            if urls and not allow_links:
                # Ссылки запрещены - маскируем и завершаем чат
                masked_text, url_count = find_and_mask_urls(text)
                
                # Форматируем ID для копирования
                user_id_display = f"`{user_id}`"
                username_display = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
                
                # Отправляем админу
                admin_message = f"👤 *{sender}* ({username_display}) {user_id_display} отправил ссылку:\n\n{masked_text}"
                
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_user_{user_id}'),
                    types.InlineKeyboardButton(f'/full#{chat_data["question_id"]}', callback_data=f'full_{chat_data["question_id"]}')
                )
                
                bot.send_message(
                    ADMIN_ID,
                    admin_message,
                    parse_mode='Markdown',
                    reply_markup=markup,
                    disable_web_page_preview=True
                )
                
                # Завершаем чат
                end_chat(user_id, "link_sent")
                bot.send_message(user_id, "⏹ Переписка завершена. Отправка ссылок запрещена.")
                
                return
            
            # Если ссылки разрешены или их нет
            bot.send_message(
                ADMIN_ID,
                f"👤 *{sender}:*\n{text[:500]}",
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            
        elif message.content_type == 'voice':
            # Проверяем лимит сообщений
            can_send, reason = check_chat_message_limit(user_id, 0)
            if not can_send:
                if reason == "message_limit_reached":
                    return
                storage.chat_message_counts[user_id] -= 1
                return
            
            caption = f"👤 {sender}: [Голосовое]"
            if message.caption:
                caption += f"\n{message.caption[:100]}"
            bot.send_voice(ADMIN_ID, message.voice.file_id, caption=caption)
            
        elif message.content_type == 'photo':
            # Проверяем лимит сообщений
            can_send, reason = check_chat_message_limit(user_id, 0)
            if not can_send:
                if reason == "message_limit_reached":
                    return
                storage.chat_message_counts[user_id] -= 1
                return
            
            caption = f"👤 {sender}: [Фото]"
            if message.caption:
                caption += f"\n{message.caption[:100]}"
            bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=caption)
            
        elif message.content_type == 'animation':
            # Проверяем лимит сообщений
            can_send, reason = check_chat_message_limit(user_id, 0)
            if not can_send:
                if reason == "message_limit_reached":
                    return
                storage.chat_message_counts[user_id] -= 1
                return
            
            caption = f"👤 {sender}: [GIF]"
            if message.caption:
                caption += f"\n{message.caption[:100]}"
            bot.send_animation(ADMIN_ID, message.animation.file_id, caption=caption)
            
        elif message.content_type == 'document':
            # Проверяем лимит сообщений
            can_send, reason = check_chat_message_limit(user_id, 0)
            if not can_send:
                if reason == "message_limit_reached":
                    return
                storage.chat_message_counts[user_id] -= 1
                return
            
            caption = f"👤 {sender}: {message.document.file_name}"
            if message.caption:
                caption += f"\n{message.caption[:100]}"
            bot.send_document(ADMIN_ID, message.document.file_id, caption=caption)
            
        elif message.content_type == 'video_note':
            # Проверяем лимит сообщений
            can_send, reason = check_chat_message_limit(user_id, 0)
            if not can_send:
                if reason == "message_limit_reached":
                    return
                storage.chat_message_counts[user_id] -= 1
                return
            
            bot.send_video_note(ADMIN_ID, message.video_note.file_id)
            bot.send_message(ADMIN_ID, f"👤 {sender}: [Кружочек]")
            
    except Exception as e:
        bot.send_message(user_id, f"❌ Ошибка отправки: {str(e)}")

def handle_admin_to_user(message):
    active_user_id = None
    for user_id, chat_data in storage.active_chats.items():
        if chat_data['admin_id'] == ADMIN_ID:
            active_user_id = user_id
            break
    
    if not active_user_id:
        return
    
    chat_data = storage.active_chats[active_user_id]
    
    try:
        if message.content_type == 'text':
            # Проверяем длину сообщения от админа
            chat_settings = storage.chat_settings.get(active_user_id, {})
            max_length = chat_settings.get('max_message_length', DEFAULT_MAX_MESSAGE_LENGTH)
            
            if len(message.text.strip()) > max_length:
                bot.send_message(ADMIN_ID, f"⚠️ Сообщение слишком длинное ({len(message.text)}/{max_length} символов)")
                return
            
            bot.send_message(
                active_user_id,
                f"👨‍💼 *{chat_data['admin_name']} (Администратор):*\n{message.text}",
                parse_mode='Markdown'
            )
        elif message.content_type == 'voice':
            caption = f"👨‍💼 {chat_data['admin_name']} (Администратор): [Голосовое]"
            if message.caption:
                caption += f"\n{message.caption}"
            bot.send_voice(active_user_id, message.voice.file_id, caption=caption)
        elif message.content_type == 'photo':
            caption = f"👨‍💼 {chat_data['admin_name']} (Администратор): [Фото]"
            if message.caption:
                caption += f"\n{message.caption}"
            bot.send_photo(active_user_id, message.photo[-1].file_id, caption=caption)
        elif message.content_type == 'animation':
            caption = f"👨‍💼 {chat_data['admin_name']} (Администратор): [GIF]"
            if message.caption:
                caption += f"\n{message.caption}"
            bot.send_animation(active_user_id, message.animation.file_id, caption=caption)
        elif message.content_type == 'document':
            caption = f"👨‍💼 {chat_data['admin_name']} (Администратор): {message.document.file_name}"
            if message.caption:
                caption += f"\n{message.caption}"
            bot.send_document(active_user_id, message.document.file_id, caption=caption)
        elif message.content_type == 'video_note':
            bot.send_video_note(active_user_id, message.video_note.file_id)
            bot.send_message(active_user_id, f"👨‍💼 {chat_data['admin_name']} (Администратор): [Кружочек]")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Не удалось отправить: {str(e)}")

# ===== ФУНКЦИИ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =====
def ask_question_start(user_id):
    msg = bot.send_message(
        user_id,
        "📝 *Напишите ваш вопрос:*\n\n"
        f"Максимум {QUESTION_LIMIT} символов.\n"
        "Можно прикрепить фото или голосовое сообщение.\n\n"
        "⚠️ *Что бы отменить запрос напишите /cancel*",
        parse_mode='Markdown',
        reply_markup=types.ReplyKeyboardRemove()
    )
    bot.register_next_step_handler(msg, process_question)

def process_question(message):
    user_id = message.from_user.id
    
    if message.text and message.text.strip() == '/cancel':
        bot.send_message(user_id, "❌ Отправка вопроса отменена.")
        start_command(message)
        return
    
    set_cooldown(user_id, 'question')
    
    has_media = False
    media_type = None
    media_info = ""
    question_text = ""
    
    if message.content_type == 'text':
        if len(message.text.strip()) > QUESTION_LIMIT:
            bot.send_message(user_id, f"❌ Вопрос слишком длинный (макс. {QUESTION_LIMIT} символов).")
            start_command(message)
            return
        
        question_text = message.text.strip()
        if not question_text or len(question_text) < 5:
            bot.send_message(user_id, "❌ Вопрос слишком короткий.")
            start_command(message)
            return
            
    elif message.content_type == 'photo':
        has_media = True
        media_type = 'photo'
        media_info = "[Фото]"
        
        if message.text:
            question_text = message.text.strip()
        elif message.caption:
            question_text = message.caption.strip()
        
        if question_text and len(question_text) > QUESTION_LIMIT:
            bot.send_message(user_id, f"❌ Подпись к фото слишком длинная (макс. {QUESTION_LIMIT} символов).")
            start_command(message)
            return
            
    elif message.content_type == 'voice':
        has_media = True
        media_type = 'voice'
        media_info = "[Голосовое сообщение]"
        
        if message.caption:
            question_text = message.caption.strip()
            if len(question_text) > QUESTION_LIMIT:
                bot.send_message(user_id, f"❌ Подпись к голосовому слишком длинная (макс. {QUESTION_LIMIT} символов).")
                start_command(message)
                return
    else:
        bot.send_message(user_id, "❌ Поддерживаются только текст, фото (не GIF) и голосовые сообщения.")
        start_command(message)
        return
    
    question_id = storage.question_counter
    username = storage.user_profiles[user_id]['username']
    
    masked_text, url_count = find_and_mask_urls(question_text)
    
    question_data = {
        'id': question_id,
        'user_id': user_id,
        'username': username,
        'text': question_text,
        'masked_text': masked_text,
        'url_count': url_count,
        'time': datetime.now().strftime("%H:%M"),
        'date': datetime.now().strftime("%d.%m.%Y"),
        'status': 'pending',
        'admin_response': None,
        'has_media': has_media,
        'media_type': media_type,
        'media_info': media_info,
        'created_at': datetime.now().isoformat()
    }
    
    if has_media and message.content_type == 'photo':
        question_data['photo_file_id'] = message.photo[-1].file_id
    elif has_media and message.content_type == 'voice':
        question_data['voice_file_id'] = message.voice.file_id
    
    storage.questions[question_id] = question_data
    storage.user_profiles[user_id]['questions_sent'] += 1
    storage.question_counter += 1
    
    notify_admin_about_question(question_id, question_data)
    
    confirm_text = f"✅ *Вопрос #{question_id} отправлен!*\n\n"
    if has_media:
        confirm_text += f"{media_info}\n"
    confirm_text += "Администратор ответит в ближайшее время."
    
    bot.send_message(user_id, confirm_text, parse_mode='Markdown')
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📨 Задать вопрос'),
        types.KeyboardButton('💬 Прямая переписка'),
        types.KeyboardButton('ℹ️ Помощь')
    )
    bot.send_message(user_id, "Главное меню:", reply_markup=markup)
    
    storage.save_data()

def request_chat_flow(user_id):
    username = storage.user_profiles[user_id]['username']
    
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
        'status': 'pending',
        'created_at': datetime.now().isoformat()
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
        reply_markup=markup,
        disable_web_page_preview=True
    )
    
    bot.send_message(user_id, "✅ Запрос на переписку отправлен администратору!")
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📨 Задать вопрос'),
        types.KeyboardButton('💬 Прямая переписка'),
        types.KeyboardButton('ℹ️ Помощь')
    )
    bot.send_message(user_id, "Главное меню:", reply_markup=markup)
    
    storage.save_data()

# ===== ФУНКЦИИ ДЛЯ АДМИНА =====
def show_tasks(message):
    pending_questions = [q for q in storage.questions.values() if q.get('status') == 'pending']
    
    if not pending_questions:
        bot.send_message(ADMIN_ID, "✅ *Все вопросы обработаны!*", parse_mode='Markdown')
        return
    
    bot.send_message(ADMIN_ID, f"📋 *Задачи: {len(pending_questions)}*", parse_mode='Markdown')
    
    for question in pending_questions:
        # Проверяем, можно ли отвечать
        can_answer, reason = can_answer_question(question['id'])
        answer_button_text = f'Ответить #{question["id"]}'
        if not can_answer:
            answer_button_text += ' ⏰'
        
        display_text = question.get('masked_text', question['text'])
        text_preview = display_text[:80] + "..." if len(display_text) > 80 else display_text
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(answer_button_text, callback_data=f'answer_{question["id"]}'),
            types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_{question["id"]}')
        )
        
        # Форматируем ID для копирования
        user_id_display = f"`{question['user_id']}`"
        
        question_text = (
            f"🔔 #{question['id']}\n"
            f"👤 {question['username']} ({user_id_display})\n"
            f"⏰ {question['time']} | {question['date']}\n"
        )
        
        # Показываем причину, если нельзя отвечать
        if not can_answer:
            question_text += f"\n⚠️ {reason}\n"
        
        question_text += f"\n{text_preview}"
        
        if question.get('has_media'):
            question_text = f"📎 {question['media_info']}\n" + question_text
        
        bot.send_message(ADMIN_ID, question_text, parse_mode='Markdown', 
                        reply_markup=markup, disable_web_page_preview=True)

def show_active_chats(message):
    if not storage.active_chats:
        bot.send_message(ADMIN_ID, "💭 Нет активных чатов")
        return
    
    text = "💬 *Активные чаты:*\n\n"
    for user_id, chat_data in storage.active_chats.items():
        if chat_data['admin_id'] == ADMIN_ID:
            settings = storage.chat_settings.get(user_id, {})
            max_length = settings.get('max_message_length', DEFAULT_MAX_MESSAGE_LENGTH)
            max_messages = settings.get('max_messages', DEFAULT_MAX_MESSAGES)
            current_messages = storage.get_chat_message_count(user_id)
            
            text += f"👤 {chat_data['user_name']}\n"
            text += f"ID: `{user_id}`\n"
            text += f"Имя админа: {chat_data['admin_name']}\n"
            text += f"Ссылки: {'✅ Разрешены' if settings.get('allow_links', True) else '❌ Запрещены'}\n"
            text += f"Макс. длина: {max_length} символов\n"
            text += f"Макс. сообщений: {max_messages} (отправлено: {current_messages})\n\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

def show_bans(message):
    if not storage.banned_users:
        bot.send_message(ADMIN_ID, "✅ Нет забаненных")
        return
    
    text = "🚫 *Бан-лист:*\n\n"
    for user_id in storage.banned_users:
        username = storage.user_profiles.get(user_id, {}).get('username', f'ID: {user_id}')
        text += f"• {username} (`{user_id}`)\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

def notify_admin_about_question(question_id, question_data):
    display_text = question_data.get('masked_text', question_data['text'])
    text_preview = display_text[:100] + "..." if len(display_text) > 100 else display_text
    
    # Создаем инлайн-кнопки
    buttons = []
    
    # Проверяем, можно ли отвечать
    can_answer, reason = can_answer_question(question_id)
    if can_answer:
        buttons.append(types.InlineKeyboardButton('✏️ Ответить', callback_data=f'answer_{question_id}'))
    else:
        buttons.append(types.InlineKeyboardButton('✏️ Ответить ⏰', callback_data=f'answer_{question_id}'))
    
    buttons.append(types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_{question_id}'))
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(*buttons)
    
    # Форматируем ID для копирования
    user_id_display = f"`{question_data['user_id']}`"
    
    notification = (
        f"📨 *Вопрос #{question_id}*\n"
        f"👤 {question_data['username']} ({user_id_display})\n"
        f"⏰ {question_data['time']} | {question_data['date']}"
    )
    
    if not can_answer:
        notification += f"\n\n⚠️ {reason}"
    
    if question_data.get('url_count', 0) > 0:
        url_word = "ссылка" if question_data['url_count'] == 1 else "ссылки"
        notification += f"\n⚠️ *Внимание:* в сообщении присутствует {question_data['url_count']} {url_word}"
    
    if question_data['has_media']:
        notification += f"\n📎 {question_data['media_info']}"
    
    notification += f"\n\n💬 {text_preview}"
    
    if question_data.get('url_count', 0) > 0:
        # Делаем /full#id кликабельным
        notification += f"\n\n🔗 *Важно:* для просмотра полного текста со ссылками используйте [/full#{question_id}](#full_{question_id})"
    
    if question_data['has_media']:
        if question_data['media_type'] == 'photo' and 'photo_file_id' in question_data:
            bot.send_photo(ADMIN_ID, question_data['photo_file_id'], 
                         caption=notification, parse_mode='Markdown', 
                         reply_markup=markup, disable_web_page_preview=True)
            return
        elif question_data['media_type'] == 'voice' and 'voice_file_id' in question_data:
            bot.send_voice(ADMIN_ID, question_data['voice_file_id'], 
                         caption=notification, parse_mode='Markdown', 
                         reply_markup=markup, disable_web_page_preview=True)
            return
    
    bot.send_message(ADMIN_ID, notification, parse_mode='Markdown', 
                     reply_markup=markup, disable_web_page_preview=True)

# ===== CALLBACK ОБРАБОТЧИК =====
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
        storage.save_data()
        
        msg = bot.send_message(
            ADMIN_ID,
            f"💬 *Принят запрос на переписку*\n\n"
            f"👤 Пользователь: {question['username']}\n"
            f"🆔 ID: `{user_id}`\n\n"
            f"📝 *Как вас звать в этой переписке?*",
            parse_mode='Markdown'
        )
        
        bot.register_next_step_handler(msg, ask_admin_name_step, user_id, question_id)
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
        
        msg = bot.send_message(
            ADMIN_ID,
            f"🚫 *Блокировка пользователя*\n\n"
            f"ID: `{user_id}`\n"
            f"Введите причину бана:\n"
            f"(или нажмите /cancel для отмены)",
            parse_mode='Markdown'
        )
        
        bot.register_next_step_handler(msg, process_ban_with_reason, user_id)
        bot.answer_callback_query(call.id, "📝 Введите причину...")
    
    elif call.data.startswith('answer_'):
        question_id = int(call.data.replace('answer_', ''))
        
        if question_id not in storage.questions:
            bot.answer_callback_query(call.id, "❌ Вопрос не найден")
            return
        
        # Проверяем, можно ли отвечать
        can_answer, reason = can_answer_question(question_id)
        if not can_answer:
            bot.answer_callback_query(call.id, reason)
            return
        
        question = storage.questions[question_id]
        
        storage.admin_pending_answers[ADMIN_ID] = question_id
        
        msg = bot.send_message(
            ADMIN_ID,
            f"✏️ *Ответ на вопрос #{question_id}*\n\n"
            f"👤 От: {question['username']} (`{question['user_id']}`)\n"
            f"⏰ {question['time']} | {question['date']}\n"
            f"💬 Вопрос: {question.get('masked_text', question['text'])[:200]}...\n\n"
            f"*Введите ответ (можно с медиа):*\n"
            f"Используйте [Имя Фамилия] в начале для подписи\n"
            f"Пример: `[Алексей Петров] Ответ...`\n\n"
            f"ℹ️ *Если нужно посмотреть полный текст со ссылками, используйте [/full#{question_id}](#full_{question_id})*",
            parse_mode='Markdown'
        )
        
        bot.answer_callback_query(call.id, "✏️ Введите ответ...")
    
    elif call.data.startswith('full_'):
        # Обработка кликабельного /full
        question_id = int(call.data.replace('full_', ''))
        show_full_question_text(ADMIN_ID, question_id)
        bot.answer_callback_query(call.id)

def ask_admin_name_step(message, user_id, question_id):
    admin_name = message.text.strip()[:30]
    
    if not admin_name:
        bot.send_message(ADMIN_ID, "❌ Имя не может быть пустым.")
        return
    
    # Сохраняем имя во временные данные чата
    if user_id not in storage.active_chats:
        storage.active_chats[user_id] = {}
    
    storage.active_chats[user_id]['admin_name'] = admin_name
    
    # Спрашиваем про ссылки
    msg = bot.send_message(
        ADMIN_ID,
        f"✅ Имя сохранено: *{admin_name}*\n\n"
        f"*Разрешить отправку ссылок?*\n\n"
        f"Напишите `Да` или `Нет` (регистр не важен).\n"
        f"Если выбрать 'Нет', чат автоматически завершится при попытке отправить ссылку.\n\n"
        f"⚠️ *Если ввести что-то другое, по умолчанию будет установлено 'Да'*",
        parse_mode='Markdown'
    )
    
    bot.register_next_step_handler(msg, ask_links_step, user_id, question_id)

def ask_links_step(message, user_id, question_id):
    text = message.text.strip().lower()
    
    # Определяем разрешение ссылок
    if text == 'да':
        allow_links = True
        confirmation = "✅ Ссылки разрешены"
    elif text == 'нет':
        allow_links = False
        confirmation = "❌ Ссылки запрещены"
    else:
        # По умолчанию - да
        allow_links = True
        confirmation = f"❌ Неверный ввод. По умолчанию установлено: *Да*"
    
    # Сохраняем настройку
    if user_id not in storage.chat_settings:
        storage.chat_settings[user_id] = {}
    storage.chat_settings[user_id]['allow_links'] = allow_links
    
    # Переходим к настройке длины сообщений
    msg = bot.send_message(
        ADMIN_ID,
        f"{confirmation}\n\n"
        f"*Настройка максимальной длины сообщений*\n\n"
        f"Введите число от {MIN_MESSAGE_LENGTH} до {MAX_MESSAGE_LENGTH}.\n"
        f"По умолчанию: {DEFAULT_MAX_MESSAGE_LENGTH} символов\n\n"
        f"⚠️ *Если ввести не число или число вне диапазона, будет установлено значение по умолчанию*",
        parse_mode='Markdown'
    )
    
    bot.register_next_step_handler(msg, ask_message_length_step, user_id, question_id, allow_links)

def ask_message_length_step(message, user_id, question_id, allow_links):
    text = message.text.strip()
    
    try:
        max_length = int(text)
        if MIN_MESSAGE_LENGTH <= max_length <= MAX_MESSAGE_LENGTH:
            # Сохраняем настройку
            storage.chat_settings[user_id]['max_message_length'] = max_length
            confirmation_length = f"✅ Макс. длина сообщений: {max_length} символов"
        else:
            # Устанавливаем значение по умолчанию
            storage.chat_settings[user_id]['max_message_length'] = DEFAULT_MAX_MESSAGE_LENGTH
            confirmation_length = f"❌ Число вне диапазона. Установлено по умолчанию: {DEFAULT_MAX_MESSAGE_LENGTH} символов"
    except ValueError:
        # Устанавливаем значение по умолчанию
        storage.chat_settings[user_id]['max_message_length'] = DEFAULT_MAX_MESSAGE_LENGTH
        confirmation_length = f"❌ Неверный ввод. Установлено по умолчанию: {DEFAULT_MAX_MESSAGE_LENGTH} символов"
    
    # Переходим к настройке лимита сообщений
    msg = bot.send_message(
        ADMIN_ID,
        f"{confirmation_length}\n\n"
        f"*Настройка максимального количества сообщений*\n\n"
        f"Введите число от {MIN_MESSAGES} до {MAX_MESSAGES}.\n"
        f"По умолчанию: {DEFAULT_MAX_MESSAGES} сообщений\n\n"
        f"ℹ️ *При достижении лимита чат автоматически завершится*\n\n"
        f"⚠️ *Если ввести не число или число вне диапазона, будет установлено значение по умолчанию*",
        parse_mode='Markdown'
    )
    
    bot.register_next_step_handler(msg, ask_max_messages_step, user_id, question_id, allow_links)

def ask_max_messages_step(message, user_id, question_id, allow_links):
    text = message.text.strip()
    
    try:
        max_messages = int(text)
        if MIN_MESSAGES <= max_messages <= MAX_MESSAGES:
            # Сохраняем настройку
            storage.chat_settings[user_id]['max_messages'] = max_messages
            confirmation_messages = f"✅ Макс. сообщений: {max_messages}"
        else:
            # Устанавливаем значение по умолчанию
            storage.chat_settings[user_id]['max_messages'] = DEFAULT_MAX_MESSAGES
            confirmation_messages = f"❌ Число вне диапазона. Установлено по умолчанию: {DEFAULT_MAX_MESSAGES} сообщений"
    except ValueError:
        # Устанавливаем значение по умолчанию
        storage.chat_settings[user_id]['max_messages'] = DEFAULT_MAX_MESSAGES
        confirmation_messages = f"❌ Неверный ввод. Установлено по умолчанию: {DEFAULT_MAX_MESSAGES} сообщений"
    
    # Завершаем настройку чата
    complete_chat_setup(user_id, question_id, allow_links, confirmation_messages)

def complete_chat_setup(user_id, question_id, allow_links, confirmation_messages):
    """Завершает настройку чата"""
    # Получаем настройки чата
    chat_settings = storage.chat_settings.get(user_id, {})
    max_length = chat_settings.get('max_message_length', DEFAULT_MAX_MESSAGE_LENGTH)
    max_messages = chat_settings.get('max_messages', DEFAULT_MAX_MESSAGES)
    
    # Завершаем создание чата
    storage.active_chats[user_id].update({
        'admin_id': ADMIN_ID,
        'user_name': storage.questions[question_id]['username'],
        'start_time': datetime.now().isoformat(),
        'question_id': question_id
    })
    
    # Сбрасываем счетчик сообщений
    storage.reset_chat_message_count(user_id)
    
    # Уведомляем пользователя
    bot.send_message(
        user_id,
        f"💬 *Переписка начата!*\n\n"
        f"👨‍💼 Администратор: *{storage.active_chats[user_id]['admin_name']}*\n"
        f"🔗 Ссылки: {'✅ Разрешены' if allow_links else '❌ Запрещены'}\n"
        f"📏 Макс. длина сообщения: {max_length} символов\n"
        f"🔢 Макс. сообщений: {max_messages}\n\n"
        f"✨ *Теперь вы можете общаться напрямую!*\n"
        f"⚠️ *Чат автоматически завершится при достижении лимита сообщений*\n"
        f"⏹ *Завершить переписку:* /stop\n"
        f"🚫 *Не используйте другие команды в чате*",
        parse_mode='Markdown'
    )
    
    # Уведомляем администратора
    bot.send_message(
        ADMIN_ID,
        f"💬 *Чат начат!*\n\n"
        f"👤 С пользователем: {storage.questions[question_id]['username']}\n"
        f"👑 Ваше имя в чате: *{storage.active_chats[user_id]['admin_name']}*\n"
        f"🔗 Ссылки: {'✅ Разрешены' if allow_links else '❌ Запрещены'}\n"
        f"📏 Макс. длина сообщения: {max_length} символов\n"
        f"{confirmation_messages}\n\n"
        f"💭 Теперь все ваши сообщения будут пересылаться.\n"
        f"⏹ Используйте /stop для завершения.",
        parse_mode='Markdown'
    )
    
    storage.save_data()

def process_ban_with_reason(message, user_id):
    if message.text == '/cancel':
        bot.send_message(ADMIN_ID, "❌ Блокировка отменена.")
        return
    
    reason = message.text.strip()
    
    storage.banned_users.add(user_id)
    
    if user_id in storage.active_chats:
        end_chat(user_id, "ban")
    
    username = storage.user_profiles.get(user_id, {}).get('username', f'ID: {user_id}')
    bot.send_message(ADMIN_ID, f"🚫 Пользователь `{user_id}` забанен.\nПричина: {reason}")
    
    try:
        bot.send_message(user_id, f"🚫 Вы были заблокированы администратором.\nПричина: {reason}")
    except:
        pass
    
    storage.save_data()

def process_admin_answer(message, question_id):
    if question_id not in storage.questions:
        bot.send_message(ADMIN_ID, "❌ Вопрос не найден")
        return
    
    # Проверяем, можно ли еще отвечать
    can_answer, reason = can_answer_question(question_id)
    if not can_answer:
        bot.send_message(ADMIN_ID, reason)
        return
    
    question = storage.questions[question_id]
    user_id = question['user_id']
    
    admin_name = None
    
    if message.content_type == 'text':
        text = message.text
        name_match = re.match(r'^\s*\[([^\]]+)\]\s*(.+)', text)
        if name_match:
            admin_name = name_match.group(1).strip()
            answer_text = name_match.group(2).strip()
        else:
            answer_text = text.strip()
    elif message.content_type in ['voice', 'photo', 'animation', 'document', 'video_note']:
        if hasattr(message, 'caption') and message.caption:
            text = message.caption
            name_match = re.match(r'^\s*\[([^\]]+)\]\s*(.+)', text)
            if name_match:
                admin_name = name_match.group(1).strip()
                answer_caption = name_match.group(2).strip()
            else:
                answer_caption = text.strip() if text else None
    
    try:
        question_preview = question['text'][:300] + "..." if len(question['text']) > 300 else question['text']
        
        if admin_name:
            header = f"📩 *Ответ на ваш вопрос #{question_id}:*\n\n"
            header += f"*Вопрос:* {question_preview}\n\n"
            header += f"*Ответ от \"{admin_name}\" (администратора):*"
        else:
            header = f"📩 *Ответ на ваш вопрос #{question_id}:*\n\n"
            header += f"*Вопрос:* {question_preview}\n\n"
            header += f"*Ответ от администрации:*"
        
        if message.content_type == 'text':
            full_message = f"{header}\n\n{answer_text}"
            bot.send_message(user_id, full_message, parse_mode='Markdown')
            
        elif message.content_type == 'voice':
            if answer_caption:
                full_caption = f"{header}\n\n{answer_caption}"
            else:
                full_caption = header
            bot.send_voice(user_id, message.voice.file_id, caption=full_caption, parse_mode='Markdown')
            
        elif message.content_type == 'photo':
            if answer_caption:
                full_caption = f"{header}\n\n{answer_caption}"
            else:
                full_caption = header
            bot.send_photo(user_id, message.photo[-1].file_id, caption=full_caption, parse_mode='Markdown')
            
        elif message.content_type == 'animation':
            if answer_caption:
                full_caption = f"{header}\n\n{answer_caption}"
            else:
                full_caption = header
            bot.send_animation(user_id, message.animation.file_id, caption=full_caption, parse_mode='Markdown')
            
        elif message.content_type == 'document':
            if answer_caption:
                full_caption = f"{header}\n\n{answer_caption}"
            else:
                full_caption = header
            bot.send_document(user_id, message.document.file_id, caption=full_caption, parse_mode='Markdown')
            
        elif message.content_type == 'video_note':
            bot.send_video_note(user_id, message.video_note.file_id)
            bot.send_message(user_id, f"{header}\n\n[Кружочек]", parse_mode='Markdown')
        
        # Обновляем статус вопроса и счетчик ответов
        storage.questions[question_id]['status'] = 'answered'
        storage.questions[question_id]['admin_response'] = "Отправлено" if message.content_type != 'text' else answer_text
        storage.questions[question_id]['admin_name'] = admin_name
        storage.questions[question_id]['answer_time'] = datetime.now().strftime("%H:%M")
        
        # Увеличиваем счетчик ответов
        storage.increment_answer_count(question_id)
        
        # Проверяем, сколько ответов осталось
        answer_count = storage.get_answer_count(question_id)
        remaining = MAX_ANSWERS_PER_QUESTION - answer_count
        
        if remaining > 0:
            bot.send_message(ADMIN_ID, f"✅ Ответ #{question_id} отправлен {question['username']}\n\n"
                                     f"ℹ️ Можно отправить еще {remaining} ответов на этот вопрос.")
        else:
            bot.send_message(ADMIN_ID, f"✅ Ответ #{question_id} отправлен {question['username']}\n\n"
                                     f"ℹ️ Достигнут лимит ответов на этот вопрос ({MAX_ANSWERS_PER_QUESTION}).")
        
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Ошибка: {str(e)}")
    
    storage.save_data()

# ===== ЗАВЕРШЕНИЕ ЧАТА =====
def end_chat(user_id, reason="normal"):
    """Завершает чат"""
    if user_id in storage.active_chats:
        chat_data = storage.active_chats[user_id]
        user_name = chat_data['user_name']
        admin_id = chat_data['admin_id']
        
        if reason == "user_used_command":
            bot.send_message(admin_id, f"⏹ Чат с {user_name} завершен (пользователь использовал команду)")
        elif reason == "user_stop":
            bot.send_message(admin_id, f"⏹ Чат с {user_name} завершен пользователем.")
        elif reason == "link_sent":
            bot.send_message(admin_id, f"⏹ Чат с {user_name} завершен (отправка ссылки при запрете)")
        elif reason == "ban":
            bot.send_message(admin_id, f"⏹ Чат с {user_name} завершен (пользователь забанен)")
        elif reason == "message_limit_reached":
            # Сообщение уже отправлено в функции check_chat_message_limit
            pass
        else:  # normal или admin_stop
            bot.send_message(admin_id, f"⏹ Чат с {user_name} завершен.")
        
        # Удаляем данные чата
        del storage.active_chats[user_id]
        # Очищаем настройки чата
        if user_id in storage.chat_settings:
            del storage.chat_settings[user_id]
        # Сбрасываем счетчик сообщений
        if user_id in storage.chat_message_counts:
            del storage.chat_message_counts[user_id]
        
        storage.save_data()

# ===== ЗАПУСК =====
if __name__ == '__main__':
    print("=" * 50)
    print(f"🤖 Бот запущен | Админ: {ADMIN_ID}")
    print(f"👥 Пользователей: {len(storage.user_profiles)}")
    print(f"📨 Вопросов: {len(storage.questions)}")
    print(f"🚫 Забанено: {len(storage.banned_users)}")
    print(f"💬 Активных чатов: {len(storage.active_chats)}")
    print("=" * 50)
    
    try:
        bot.polling(none_stop=True, interval=0)
    except Exception as e:
        print(f"Ошибка при запуске бота: {e}")
