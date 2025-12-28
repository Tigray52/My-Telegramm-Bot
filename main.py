import telebot
import os
import json
import re
import time
import urllib.parse
import threading
from datetime import datetime, timedelta
from telebot import types

bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))
ADMIN_ID = 6337781618

# Хранилище данных
class Storage:
    def __init__(self):
        self.questions = {}
        self.active_chats = {}
        self.banned_users = {}  # {user_id: {'until': timestamp, 'reason': str, 'notify_on_unban': bool}}
        self.muted_users = {}   # {user_id: {'until': timestamp, 'reason': str, 'notify_on_unmute': bool}}
        self.user_profiles = {}
        self.question_counter = 1
        self.user_cooldowns = {}
        self.admin_pending_answers = {}
        self.chat_settings = {}
        self.answer_counts = {}
        self.violation_messages = {}
        self.chat_limits = {}
        self.max_active_questions = 5
        self.user_message_counts = {}
        self.message_history = {}
        self.pending_replies = {}  # {user_id: {'reply_to_msg_id': int, 'reply_to_text': str}}
        self.load_data()
    
    def load_data(self):
        try:
            if os.path.exists('storage.json'):
                with open('storage.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.questions = {int(k): v for k, v in data.get('questions', {}).items()}
                    self.banned_users = data.get('banned_users', {})
                    self.muted_users = data.get('muted_users', {})
                    self.user_profiles = data.get('user_profiles', {})
                    self.question_counter = data.get('counter', 1)
                    self.user_cooldowns = data.get('cooldowns', {})
                    self.chat_settings = data.get('chat_settings', {})
                    self.answer_counts = data.get('answer_counts', {})
                    self.violation_messages = data.get('violation_messages', {})
                    self.chat_limits = data.get('chat_limits', {})
                    self.user_message_counts = data.get('user_message_counts', {})
                    self.message_history = data.get('message_history', {})
                    self.pending_replies = data.get('pending_replies', {})
        except Exception as e:
            print(f"Ошибка загрузки данных: {e}")
    
    def save_data(self):
        data = {
            'questions': self.questions,
            'banned_users': self.banned_users,
            'muted_users': self.muted_users,
            'user_profiles': self.user_profiles,
            'counter': self.question_counter,
            'cooldowns': self.user_cooldowns,
            'chat_settings': self.chat_settings,
            'answer_counts': self.answer_counts,
            'violation_messages': self.violation_messages,
            'chat_limits': self.chat_limits,
            'user_message_counts': self.user_message_counts,
            'message_history': self.message_history,
            'pending_replies': self.pending_replies
        }
        try:
            with open('storage.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения данных: {e}")
    
    def save_violation_message(self, user_id, text, urls, time_str, date_str):
        self.violation_messages[user_id] = {
            'text': text,
            'urls': urls,
            'time': time_str,
            'date': date_str
        }
        self.save_data()
    
    def get_violation_message(self, user_id):
        return self.violation_messages.get(user_id)
    
    def clear_violation_message(self, user_id):
        if user_id in self.violation_messages:
            del self.violation_messages[user_id]
            self.save_data()
    
    def get_answer_count(self, question_id):
        return self.answer_counts.get(question_id, 0)
    
    def increment_answer_count(self, question_id):
        current = self.get_answer_count(question_id)
        self.answer_counts[question_id] = current + 1
        self.save_data()
    
    def can_ask_question(self, user_id):
        active_count = 0
        for q in self.questions.values():
            if q.get('user_id') == user_id and q.get('status') == 'pending':
                active_count += 1
        return active_count < self.max_active_questions, active_count
    
    def is_banned(self, user_id):
        """Проверяет, забанен ли пользователь"""
        if user_id not in self.banned_users:
            return False
        
        ban_data = self.banned_users[user_id]
        if ban_data.get('until') == 0:  # Перманентный бан
            return True
        
        if time.time() < ban_data['until']:
            return True
        else:
            # Время бана истекло, разбаниваем
            notify = ban_data.get('notify_on_unban', True)
            del self.banned_users[user_id]
            self.save_data()
            
            if notify:
                return "expired"  # Возвращаем специальный код для уведомления
            return False
    
    def ban_user(self, user_id, duration_seconds=0, reason="Нарушение правил"):
        """Банит пользователя на указанное время (0 = перманентно)"""
        if duration_seconds == 0:
            until = 0  # Перманентный бан
        else:
            until = time.time() + duration_seconds
        
        self.banned_users[user_id] = {
            'until': until,
            'reason': reason,
            'banned_at': time.time(),
            'notify_on_unban': duration_seconds > 0  # Уведомлять только при временном бане
        }
        self.save_data()
    
    def unban_user(self, user_id):
        """Разбанивает пользователя"""
        if user_id in self.banned_users:
            del self.banned_users[user_id]
            self.save_data()
            return True
        return False
    
    def is_muted(self, user_id):
        """Проверяет, заглушен ли пользователь (не может использовать прямую переписку)"""
        if user_id not in self.muted_users:
            return False
        
        mute_data = self.muted_users[user_id]
        if mute_data.get('until') == 0:  # Перманентный мут
            return True
        
        if time.time() < mute_data['until']:
            return True
        else:
            # Время мута истекло, размучиваем
            notify = mute_data.get('notify_on_unmute', True)
            del self.muted_users[user_id]
            self.save_data()
            
            if notify:
                return "expired"  # Возвращаем специальный код для уведомления
            return False
    
    def mute_user(self, user_id, duration_seconds=0, reason="Нарушение правил"):
        """Мутит пользователя на указанное время (0 = перманентно)"""
        if duration_seconds == 0:
            until = 0  # Перманентный мут
        else:
            until = time.time() + duration_seconds
        
        self.muted_users[user_id] = {
            'until': until,
            'reason': reason,
            'muted_at': time.time(),
            'notify_on_unmute': duration_seconds > 0  # Уведомлять только при временном муте
        }
        self.save_data()
    
    def unmute_user(self, user_id):
        """Размучивает пользователя"""
        if user_id in self.muted_users:
            del self.muted_users[user_id]
            self.save_data()
            return True
        return False
    
    def check_spam(self, user_id):
        """Проверяет пользователя на спам"""
        now = time.time()
        
        if user_id not in self.user_message_counts:
            self.user_message_counts[user_id] = {
                'count': 1,
                'reset_time': now + 10
            }
            self.save_data()
            return False
        
        user_data = self.user_message_counts[user_id]
        
        if now > user_data['reset_time']:
            user_data['count'] = 1
            user_data['reset_time'] = now + 10
            self.save_data()
            return False
        
        user_data['count'] += 1
        self.save_data()
        
        if user_data['count'] > 10:
            return True
        
        return False
    
    def add_to_message_history(self, user_id, message_id, text, is_admin=False):
        """Добавляет сообщение в историю для функции ответа"""
        if user_id not in self.message_history:
            self.message_history[user_id] = []
        
        self.message_history[user_id].append({
            'id': message_id,
            'text': text[:200],
            'time': time.time(),
            'is_admin': is_admin
        })
        
        if len(self.message_history[user_id]) > 100:
            self.message_history[user_id] = self.message_history[user_id][-100:]
        
        self.save_data()
    
    def get_message_by_id(self, user_id, message_id):
        """Находит сообщение по ID в истории"""
        if user_id not in self.message_history:
            return None
        
        for msg in self.message_history[user_id]:
            if msg['id'] == message_id:
                return msg
        return None
    
    def set_pending_reply(self, user_id, reply_to_msg_id, reply_to_text):
        """Устанавливает ожидание ответа на сообщение"""
        self.pending_replies[user_id] = {
            'reply_to_msg_id': reply_to_msg_id,
            'reply_to_text': reply_to_text[:100]
        }
        self.save_data()
    
    def get_pending_reply(self, user_id):
        """Получает информацию об ожидающем ответе"""
        return self.pending_replies.get(user_id)
    
    def clear_pending_reply(self, user_id):
        """Очищает ожидание ответа"""
        if user_id in self.pending_replies:
            del self.pending_replies[user_id]
            self.save_data()

storage = Storage()

# Константы
CHAT_MESSAGE_LIMIT = 350
QUESTION_LIMIT = 400
QUESTION_COOLDOWN = 30
CHAT_REQUEST_COOLDOWN = 60
MAX_ANSWERS_PER_QUESTION = 2
ANSWER_TIME_LIMIT_HOURS = 24
SPAM_LIMIT_MESSAGES = 10
SPAM_LIMIT_SECONDS = 10

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def escape_markdown(text):
    """Экранирует специальные символы Markdown"""
    if not text:
        return text
    
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def mask_url(url):
    """Маскирует URL, оставляя первую букву домена и точку"""
    try:
        if '://' in url:
            protocol, rest = url.split('://', 1)
            original_protocol = url[:len(protocol)+3]
            rest_part = url[len(protocol)+3:]
        else:
            original_protocol = ''
            rest_part = url
        
        if '/' in rest_part:
            domain, path = rest_part.split('/', 1)
            path = '/' + path
        else:
            domain = rest_part
            path = ''
        
        if '.' in domain:
            parts = domain.split('.')
            if len(parts) >= 2:
                first_part = parts[0]
                if len(first_part) > 1:
                    masked_first = first_part[0] + '•' * (len(first_part) - 1)
                else:
                    masked_first = first_part
                
                masked_domain = masked_first + '.' + '.'.join(parts[1:])
            else:
                masked_domain = domain
        else:
            masked_domain = domain
        
        result = original_protocol + masked_domain + path
        return result
        
    except Exception as e:
        print(f"Ошибка маскировки URL {url}: {e}")
        return url

def find_and_mask_urls(text):
    """Находит и маскирует все URL в тексте"""
    url_pattern = r'(?i)(https?://[^\s<>"]+|www\.[^\s<>"]+\.[^\s<>"]+)'
    urls = re.findall(url_pattern, text)
    
    if not urls:
        return text, 0
    
    masked_text = text
    for url in urls:
        normalized_url = url
        if not url.lower().startswith(('http://', 'https://', 'www.')):
            normalized_url = 'http://' + url
        
        masked_url = mask_url(normalized_url)
        
        if not url.lower().startswith(('http://', 'https://')):
            if masked_url.startswith('http://'):
                masked_url = masked_url[7:]
            elif masked_url.startswith('https://'):
                masked_url = masked_url[8:]
        
        masked_text = masked_text.replace(url, masked_url)
    
    return masked_text, len(urls)

def find_all_urls(text):
    """Находит все URL в тексте (возвращает список)"""
    url_pattern = r'(?i)(https?://[^\s<>"]+|www\.[^\s<>"]+\.[^\s<>"]+)'
    urls = re.findall(url_pattern, text)
    
    decoded_urls = []
    for url in urls:
        try:
            decoded = urllib.parse.unquote(url)
            if not decoded.lower().startswith(('http://', 'https://')):
                decoded = 'http://' + decoded
            decoded_urls.append(decoded)
        except:
            decoded_urls.append(url)
    
    return decoded_urls

def parse_duration(duration_str):
    """Парсит строку длительности в секунды"""
    if not duration_str:
        return 0  # Перманентно
    
    duration_str = duration_str.lower().strip()
    total_seconds = 0
    
    patterns = [
        (r'(\d+)\s*y', 365 * 24 * 3600),
        (r'(\d+)\s*mon', 30 * 24 * 3600),
        (r'(\d+)\s*w', 7 * 24 * 3600),
        (r'(\d+)\s*d', 24 * 3600),
        (r'(\d+)\s*h', 3600),
        (r'(\d+)\s*m', 60),
        (r'(\d+)\s*s', 1)
    ]
    
    for pattern, multiplier in patterns:
        match = re.search(pattern, duration_str)
        if match:
            total_seconds += int(match.group(1)) * multiplier
    
    return total_seconds

def format_duration(seconds):
    """Форматирует длительность в читаемый вид"""
    if seconds == 0:
        return "навсегда"
    
    periods = [
        ('год', 365 * 24 * 3600),
        ('месяц', 30 * 24 * 3600),
        ('неделя', 7 * 24 * 3600),
        ('день', 24 * 3600),
        ('час', 3600),
        ('минута', 60),
        ('секунда', 1)
    ]
    
    result = []
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value = seconds // period_seconds
            seconds -= period_value * period_seconds
            
            if period_value == 1:
                result.append(f"{period_value} {period_name}")
            elif 2 <= period_value <= 4:
                if period_name in ['год', 'месяц', 'день', 'час']:
                    result.append(f"{period_value} {period_name}а")
                elif period_name == 'неделя':
                    result.append(f"{period_value} {period_name}и")
                elif period_name == 'минута':
                    result.append(f"{period_value} {period_name}ы")
                else:
                    result.append(f"{period_value} {period_name}")
            else:
                if period_name == 'год':
                    result.append(f"{period_value} лет")
                elif period_name == 'месяц':
                    result.append(f"{period_value} месяцев")
                elif period_name == 'неделя':
                    result.append(f"{period_value} недель")
                elif period_name == 'день':
                    result.append(f"{period_value} дней")
                elif period_name == 'час':
                    result.append(f"{period_value} часов")
                elif period_name == 'минута':
                    result.append(f"{period_value} минут")
                else:
                    result.append(f"{period_value} секунд")
    
    return " ".join(result)

def check_ban_expirations():
    """Проверяет истекшие баны и отправляет уведомления"""
    while True:
        try:
            current_time = time.time()
            
            # Проверяем баны
            for user_id, ban_data in list(storage.banned_users.items()):
                if ban_data['until'] != 0 and current_time >= ban_data['until']:
                    if storage.is_banned(user_id) == "expired":
                        try:
                            bot.send_message(
                                user_id,
                                f"✅ *Ваш бан истек!*\n\n"
                                f"Вы снова можете пользоваться ботом.\n"
                                f"Причина бана: {ban_data['reason']}"
                            )
                        except:
                            pass
            
            # Проверяем муты
            for user_id, mute_data in list(storage.muted_users.items()):
                if mute_data['until'] != 0 and current_time >= mute_data['until']:
                    if storage.is_muted(user_id) == "expired":
                        try:
                            bot.send_message(
                                user_id,
                                f"✅ *Ваш мут истек!*\n\n"
                                f"Вы снова можете использовать прямую переписку.\n"
                                f"Причина мута: {mute_data['reason']}"
                            )
                        except:
                            pass
            
            time.sleep(60)  # Проверяем каждую минуту
        except Exception as e:
            print(f"Ошибка в check_ban_expirations: {e}")
            time.sleep(60)

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
    
    try:
        question_date = datetime.strptime(question['date'], '%d.%m.%Y')
        question_time = datetime.strptime(question['time'], '%H:%M')
        question_datetime = datetime.combine(question_date.date(), question_time.time())
        
        if datetime.now() - question_datetime > timedelta(hours=ANSWER_TIME_LIMIT_HOURS):
            return False, f"⏰ Нельзя отвечать на вопросы старше {ANSWER_TIME_LIMIT_HOURS} часов"
    except:
        pass
    
    answer_count = storage.get_answer_count(question_id)
    if answer_count >= MAX_ANSWERS_PER_QUESTION:
        return False, f"❌ На этот вопрос уже отправлено {MAX_ANSWERS_PER_QUESTION} ответа"
    
    return True, ""

# ===== КОМАНДЫ =====
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    
    ban_status = storage.is_banned(user_id)
    if ban_status is True:
        ban_data = storage.banned_users[user_id]
        if ban_data['until'] == 0:
            ban_time = "навсегда"
        else:
            remaining = ban_data['until'] - time.time()
            if remaining > 0:
                ban_time = f"ещё {format_duration(int(remaining))}"
            else:
                ban_time = "истёк"
        
        bot.send_message(
            user_id, 
            f"🚫 Вы заблокированы администратором.\n"
            f"Причина: {ban_data['reason']}\n"
            f"Бан: {ban_time}"
        )
        return
    
    if is_admin(user_id):
        admin_panel(message)
        return
    
    # Проверка на спам
    if storage.check_spam(user_id):
        storage.ban_user(user_id, 3600, "Спам (более 10 сообщений за 10 секунд)")
        bot.send_message(
            user_id,
            "🚫 Вы были заблокированы за спам на 1 час."
        )
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
        storage.save_data()
    
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
        "• Только текст (медиафайлы не принимаются)\n"
        "• Cooldown: 30 секунд\n"
        "• Максимум 5 активных вопросов\n"
        "• /cancel - отмена\n\n"
        "*💬 Прямая переписка:*\n"
        "• Cooldown: 60 секунд\n"
        "• Админ может принять или отклонить\n"
        "• Используйте /stop в чате для завершения\n"
        "• Можно отвечать на сообщения (кнопка 'Ответить' под сообщением)\n\n"
        "*💬 В чате:*\n"
        f"• Только текстовые сообщения\n"
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
        "• /ban [ID] [время] [причина] - Забанить\n"
        "• /unban [ID] - Разбанить\n"
        "• /mute [ID] [время] [причина] - Заглушить (запретить переписку)\n"
        "• /unmute [ID] - Разглушить\n"
        "• /stop [причина] - Завершить текущий чат с причиной\n"
        "• /message [ID] текст - Отправить сообщение\n"
        "• /full - Раскрыть ссылку в вопросе\n\n"
        
        "*Бан с указанием времени:*\n"
        "`/ban 123456789` - навсегда\n"
        "`/ban 123456789 1d` - на 1 день\n"
        "`/ban 123456789 1w3d5h спам` - на 1 неделю 3 дня 5 часов\n\n"
        
        "*Мут с указанием времени:*\n"
        "`/mute 123456789` - навсегда\n"
        "`/mute 123456789 1h` - на 1 час\n"
        "`/mute 123456789 2d5m флуд` - на 2 дня 5 минут за флуд\n\n"
        
        "*Формат времени:*\n"
        "• y - годы, mon - месяцы, w - недели\n"
        "• d - дни, h - часы, m - минуты, s - секунды\n"
        "• Можно комбинировать: 1d5h, 2w3d, 1y6mon\n\n"
        
        "*Команда /stop:*\n"
        "`/stop` - завершить чат\n"
        "`/stop пользователь грубил` - завершить с причиной\n\n"
        
        "*Формат /message:*\n"
        "`/message [ID] Текст` - без рамок\n"
        "`/message [ID, Имя] Текст` - с именем, без рамок\n"
        "`/message [ID] {true} Текст` - с рамками\n\n"
        
        "*Формат ответа на вопрос:*\n"
        "`[Имя Фамилия] Ответ` - с именем\n"
        "`Просто ответ` - без имени\n\n"
        
        "*Лимиты:*\n"
        f"• Максимум {MAX_ANSWERS_PER_QUESTION} ответа на вопрос\n"
        f"• Нельзя отвечать на вопросы старше {ANSWER_TIME_LIMIT_HOURS} часов\n"
        f"• У пользователя максимум {storage.max_active_questions} активных вопросов\n"
        f"• Антиспам: более {SPAM_LIMIT_MESSAGES} сообщений за {SPAM_LIMIT_SECONDS} секунд = бан"
    )
    bot.send_message(ADMIN_ID, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    user_id = message.from_user.id
    
    if is_user_in_chat(user_id):
        end_chat(user_id, "user_used_command")
        bot.send_message(user_id, "❌ Диалог завершен, так как вы использовали команду.")
        return
    
    if user_id == ADMIN_ID and user_id in storage.admin_pending_answers:
        del storage.admin_pending_answers[user_id]
        bot.send_message(ADMIN_ID, "✅ Ответ отменен.")
    
    bot.send_message(user_id, "✅ Действие отменено.")
    start_command(message)

@bot.message_handler(commands=['stop'])
def stop_command(message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        # Для обычных пользователей старая логика
        ban_status = storage.is_banned(user_id)
        if ban_status is True:
            return
        
        if is_user_in_chat(user_id):
            end_chat(user_id, "user_stop")
            bot.send_message(user_id, "⏹ Вы завершили переписку.")
            return
        
        bot.send_message(user_id, "❌ Вы не находитесь в активной переписке.")
        return
    
    # Для админа - новая логика с причиной
    active_user_id = None
    for uid, chat_data in storage.active_chats.items():
        if chat_data['admin_id'] == ADMIN_ID:
            active_user_id = uid
            break
    
    if not active_user_id:
        bot.send_message(ADMIN_ID, "❌ Нет активных чатов")
        return
    
    # Извлекаем причину из сообщения
    parts = message.text.split(maxsplit=1)
    reason = parts[1] if len(parts) > 1 else None
    
    if reason:
        # Завершаем чат с причиной
        end_chat_with_reason(active_user_id, reason)
        bot.send_message(ADMIN_ID, f"✅ Чат завершен с причиной: {reason}")
    else:
        # Завершаем чат без причины
        end_chat(active_user_id, "admin_stop")
        bot.send_message(ADMIN_ID, "✅ Чат завершен")

def end_chat(user_id, reason="normal"):
    """Завершает чат без указания причины"""
    if user_id in storage.active_chats:
        chat_data = storage.active_chats[user_id]
        user_name = chat_data['user_name']
        admin_id = chat_data['admin_id']
        
        messages = {
            "user_used_command": "⏹ Чат завершен (пользователь использовал команду)",
            "user_stop": "⏹ Пользователь завершил переписку",
            "link_sent": "⏹ Чат завершен (отправка ссылки при запрете)",
            "ban": "⏹ Чат завершен (пользователь забанен)",
            "admin_stop": "⏹ Администратор завершил переписку",
            "normal": "⏹ Чат завершен",
            "admin_cancelled": "⏹ Чат отклонен администратором",
            "mute": "⏹ Чат завершен (пользователь заглушен)"
        }
        
        message_text = messages.get(reason, "⏹ Чат завершен")
        
        try:
            bot.send_message(admin_id, f"{message_text} с {user_name}")
        except:
            pass
        
        if reason not in ["ban", "mute"] and storage.is_banned(user_id) is not True:
            try:
                if reason == "admin_stop":
                    bot.send_message(user_id, "⏹ Администратор завершил переписку.")
                elif reason == "user_stop":
                    bot.send_message(user_id, "⏹ Вы завершили переписку.")
                elif reason == "link_sent":
                    bot.send_message(user_id, "⏹ Переписка завершена. Отправка ссылок запрещена.")
                elif reason == "admin_cancelled":
                    bot.send_message(user_id, "⏹ Администратор отклонил создание переписки.")
                else:
                    bot.send_message(user_id, "⏹ Переписка завершена.")
            except:
                pass
        
        del storage.active_chats[user_id]
        if user_id in storage.chat_settings:
            del storage.chat_settings[user_id]
        if user_id in storage.chat_limits:
            del storage.chat_limits[user_id]
        if user_id in storage.pending_replies:
            del storage.pending_replies[user_id]
        
        storage.save_data()

def end_chat_with_reason(user_id, reason):
    """Завершает чат с указанием причины"""
    if user_id in storage.active_chats:
        chat_data = storage.active_chats[user_id]
        user_name = chat_data['user_name']
        admin_id = chat_data['admin_id']
        
        # Уведомляем админа
        try:
            bot.send_message(admin_id, f"⏹ Чат завершен с {user_name}\nПричина: {reason}")
        except:
            pass
        
        # Уведомляем пользователя
        if storage.is_banned(user_id) is not True:
            try:
                bot.send_message(user_id, f"⏹ Администратор завершил переписку.\nПричина: {reason}")
            except:
                pass
        
        del storage.active_chats[user_id]
        if user_id in storage.chat_settings:
            del storage.chat_settings[user_id]
        if user_id in storage.chat_limits:
            del storage.chat_limits[user_id]
        if user_id in storage.pending_replies:
            del storage.pending_replies[user_id]
        
        storage.save_data()

@bot.message_handler(commands=['admin'])
def admin_command(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔ У вас нет доступа к этой команде")
        return
    
    admin_panel(message)

def admin_panel(message):
    pending_count = len([q for q in storage.questions.values() if q.get('status') == 'pending'])
    
    active_bans = 0
    for user_id, ban_data in storage.banned_users.items():
        if ban_data['until'] == 0 or time.time() < ban_data['until']:
            active_bans += 1
    
    active_mutes = 0
    for user_id, mute_data in storage.muted_users.items():
        if mute_data['until'] == 0 or time.time() < mute_data['until']:
            active_mutes += 1
    
    text = (
        f"👑 *Панель администратора*\n\n"
        f"📊 Статистика:\n"
        f"• Вопросов: {pending_count}\n"
        f"• Чатов: {len(storage.active_chats)}\n"
        f"• Пользователей: {len(storage.user_profiles)}\n"
        f"• Активных банов: {active_bans}\n"
        f"• Активных мутов: {active_mutes}\n"
        f"• Нарушений ссылок: {len(storage.violation_messages)}\n\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}"
    )
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📋 Задачи (/tasks)'),
        types.KeyboardButton('💬 Активные чаты'),
        types.KeyboardButton('🚫 Бан-лист'),
        types.KeyboardButton('🔇 Мут-лист'),
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
    
    parts = message.text.split(maxsplit=3)
    if len(parts) < 2:
        bot.send_message(ADMIN_ID, 
                        "Используйте: /ban ID [время] [причина]\n"
                        "Примеры:\n"
                        "`/ban 123456789` - навсегда\n"
                        "`/ban 123456789 1d` - на 1 день\n"
                        "`/ban 123456789 1w3d5h спам`\n"
                        "`/ban 123456789 1y1d5h10s нарушение правил`",
                        parse_mode='Markdown')
        return
    
    user_id_str = parts[1]
    
    if not user_id_str.isdigit():
        bot.send_message(ADMIN_ID, "❌ ID должен быть числом")
        return
    
    user_id = int(user_id_str)
    
    if user_id == ADMIN_ID:
        bot.send_message(ADMIN_ID, "❌ Нельзя забанить себя")
        return
    
    duration_str = ""
    reason = "Нарушение правил"
    
    if len(parts) >= 3:
        time_match = re.search(r'(\d+[ymondhs]?\s*)+', parts[2].lower())
        if time_match:
            duration_str = parts[2]
            if len(parts) >= 4:
                reason = parts[3]
        else:
            reason = parts[2] if len(parts) == 3 else " ".join(parts[2:])
    
    duration_seconds = parse_duration(duration_str)
    
    storage.ban_user(user_id, duration_seconds, reason)
    
    if user_id in storage.active_chats:
        end_chat(user_id, "ban")
    
    if user_id in storage.violation_messages:
        storage.clear_violation_message(user_id)
    
    duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
    bot.send_message(ADMIN_ID, f"✅ Пользователь `{user_id}` забанен на {duration_text}.\nПричина: {reason}")
    
    try:
        if duration_seconds == 0:
            ban_time = "навсегда"
        else:
            ban_time = format_duration(duration_seconds)
        
        bot.send_message(
            user_id,
            f"🚫 Вы были заблокированы администратором.\n"
            f"Причина: {reason}\n"
            f"Срок: {ban_time}"
        )
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
    
    if storage.unban_user(user_id):
        bot.send_message(ADMIN_ID, f"✅ Пользователь `{user_id}` разбанен.")
        
        try:
            bot.send_message(user_id, "✅ Вы были разблокированы администратором.")
        except:
            pass
    else:
        bot.send_message(ADMIN_ID, f"❌ Пользователь `{user_id}` не найден в бан-листе.")

@bot.message_handler(commands=['mute'])
def mute_command(message):
    if not is_admin(message.from_user.id):
        return
    
    parts = message.text.split(maxsplit=3)
    if len(parts) < 2:
        bot.send_message(ADMIN_ID, 
                        "Используйте: /mute ID [время] [причина]\n"
                        "Примеры:\n"
                        "`/mute 123456789` - навсегда\n"
                        "`/mute 123456789 1h` - на 1 час\n"
                        "`/mute 123456789 2d5m флуд`\n"
                        "`/mute 123456789 1w нарушение правил`",
                        parse_mode='Markdown')
        return
    
    user_id_str = parts[1]
    
    if not user_id_str.isdigit():
        bot.send_message(ADMIN_ID, "❌ ID должен быть числом")
        return
    
    user_id = int(user_id_str)
    
    if user_id == ADMIN_ID:
        bot.send_message(ADMIN_ID, "❌ Нельзя заглушить себя")
        return
    
    duration_str = ""
    reason = "Нарушение правил"
    
    if len(parts) >= 3:
        time_match = re.search(r'(\d+[ymondhs]?\s*)+', parts[2].lower())
        if time_match:
            duration_str = parts[2]
            if len(parts) >= 4:
                reason = parts[3]
        else:
            reason = parts[2] if len(parts) == 3 else " ".join(parts[2:])
    
    duration_seconds = parse_duration(duration_str)
    
    storage.mute_user(user_id, duration_seconds, reason)
    
    duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
    bot.send_message(ADMIN_ID, f"✅ Пользователь `{user_id}` заглушен на {duration_text}.\nПричина: {reason}")
    
    try:
        if duration_seconds == 0:
            mute_time = "навсегда"
        else:
            mute_time = format_duration(duration_seconds)
        
        bot.send_message(
            user_id,
            f"🔇 Вы были заглушены администратором.\n\n"
            f"⚠️ *Вам запрещено использовать прямую переписку.*\n\n"
            f"Причина: {reason}\n"
            f"Срок: {mute_time}\n\n"
            f"Вы по-прежнему можете задавать вопросы через раздел 📨 Задать вопрос."
        )
    except:
        pass
    
    storage.save_data()

@bot.message_handler(commands=['unmute'])
def unmute_command(message):
    if not is_admin(message.from_user.id):
        return
    
    if len(message.text.split()) < 2:
        bot.send_message(ADMIN_ID, "Используйте: /unmute ID")
        return
    
    target = message.text.split(maxsplit=1)[1]
    
    if not target.isdigit():
        bot.send_message(ADMIN_ID, "❌ ID должен быть числом")
        return
    
    user_id = int(target)
    
    if storage.unmute_user(user_id):
        bot.send_message(ADMIN_ID, f"✅ Пользователь `{user_id}` разглушен.")
        
        try:
            bot.send_message(
                user_id,
                "✅ Вы были разглушены администратором.\n\n"
                "Теперь вы снова можете использовать прямую переписку."
            )
        except:
            pass
    else:
        bot.send_message(ADMIN_ID, f"❌ Пользователь `{user_id}` не найден в мут-листе.")

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
    
    if storage.is_banned(user_id) is True:
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

@bot.message_handler(func=lambda m: m.text and m.text.startswith(('/full', '/Full')))
def full_command(message):
    if not is_admin(message.from_user.id):
        return
    
    text = message.text.strip()
    
    question_id = None
    
    match1 = re.search(r'^/full#(\d+)$', text, re.IGNORECASE)
    if match1:
        question_id = int(match1.group(1))
    
    if not question_id:
        match2 = re.search(r'^/full\s+#(\d+)$', text, re.IGNORECASE)
        if match2:
            question_id = int(match2.group(1))
    
    if not question_id:
        parts = text.split()
        if len(parts) == 2 and parts[1].isdigit():
            question_id = int(parts[1])
    
    if question_id:
        show_full_question_text(ADMIN_ID, question_id)
        return
    
    if ADMIN_ID in storage.admin_pending_answers:
        question_id = storage.admin_pending_answers[ADMIN_ID]
        show_full_question_text(ADMIN_ID, question_id)
        return
    
    if message.reply_to_message:
        reply_msg = message.reply_to_message
        question_id = None
        
        match = re.search(r'#(\d+)', reply_msg.text or reply_msg.caption or '')
        if match:
            question_id = int(match.group(1))
        else:
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
    
    full_text = f"📨 *Полный текст вопроса #{question_id}*\n\n"
    
    user_id_display = f"`{question['user_id']}`"
    if question['username']:
        full_text += f"👤 {question['username']} ({user_id_display})\n"
    else:
        full_text += f"👤 {user_id_display}\n"
    
    full_text += f"⏰ {question['time']} | {question['date']}\n\n"
    full_text += f"💬 {question['text']}"
    
    urls = re.findall(r'(?i)https?://[^\s<>"]+|www\.[^\s<>"]+\.[^\s<>"]+', question['text'])
    if urls:
        full_text += f"\n\n🔗 *Ссылки ({len(urls)}):*\n"
        for i, url in enumerate(urls, 1):
            full_text += f"{i}. {url}\n"
    
    bot.send_message(admin_id, full_text, parse_mode='Markdown', disable_web_page_preview=True)
    
    if admin_id in storage.admin_pending_answers:
        msg = bot.send_message(
            admin_id,
            f"Теперь введите ответ на вопрос #{question_id}:\n"
            f"Используйте [Имя Фамилия] в начале для подписи",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_admin_answer, question_id)

def show_full_violation_message(admin_id, user_id):
    """Показывает полное сообщение с ссылками при нарушении правил чата"""
    violation = storage.get_violation_message(user_id)
    if not violation:
        bot.send_message(admin_id, "❌ Данные о нарушении не найдены.")
        return
    
    user_profile = storage.user_profiles.get(user_id, {})
    username = user_profile.get('username', f'ID: {user_id}')
    
    message_text = (
        f"👤 {username} (`{user_id}`)\n"
        f"⏰ {violation['time']} | {violation['date']}\n\n"
        f"💬 {violation['text']}\n\n"
        f"🔗 *Ссылки ({len(violation['urls'])}):*\n"
    )
    
    for i, url in enumerate(violation['urls'], 1):
        message_text += f"{i}. {url}\n"
    
    bot.send_message(admin_id, message_text, parse_mode='Markdown', disable_web_page_preview=True)

# ===== ОБРАБОТКА СООБЩЕНИЙ =====
@bot.message_handler(func=lambda m: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    
    ban_status = storage.is_banned(user_id)
    if ban_status is True:
        return
    
    # Проверка на спам
    if storage.check_spam(user_id):
        storage.ban_user(user_id, 3600, "Спам (более 10 сообщений за 10 секунд)")
        bot.send_message(
            user_id,
            "🚫 Вы были заблокированы за спам на 1 час."
        )
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
    # Проверяем, есть ли ожидающий ответ с кнопки "Ответить"
    pending_reply = storage.get_pending_reply(ADMIN_ID)
    if pending_reply and message.content_type == 'text' and not message.text.startswith('/'):
        reply_to_text = pending_reply['reply_to_text']
        storage.clear_pending_reply(ADMIN_ID)
        
        # Экранируем текст для Markdown
        escaped_reply_text = escape_markdown(message.text)
        escaped_original_text = escape_markdown(reply_to_text)
        
        # Формируем сообщение с ответом
        reply_text = f"↪️ *Ответ на:* {escaped_original_text}\n_________________\n{escaped_reply_text}"
        
        # Находим активный чат
        active_user_id = None
        for uid, chat_data in storage.active_chats.items():
            if chat_data['admin_id'] == ADMIN_ID:
                active_user_id = uid
                break
        
        if active_user_id:
            chat_data = storage.active_chats[active_user_id]
            
            # Экранируем имя админа для безопасного использования в Markdown
            escaped_admin_name = escape_markdown(chat_data['admin_name'])
            
            try:
                sent_msg = bot.send_message(
                    active_user_id,
                    f"👨‍💼 *{escaped_admin_name} (Администратор):*\n{reply_text}",
                    parse_mode='Markdown'
                )
                
                storage.add_to_message_history(active_user_id, sent_msg.message_id, message.text, is_admin=True)
            except Exception as e:
                bot.send_message(ADMIN_ID, f"❌ Не удалось отправить: {str(e)}")
        
        return
    
    if ADMIN_ID in storage.admin_pending_answers:
        if message.content_type == 'text' and message.text.strip().lower().startswith('/full'):
            question_id = storage.admin_pending_answers[ADMIN_ID]
            show_full_question_text(ADMIN_ID, question_id)
            return
        
        question_id = storage.admin_pending_answers[ADMIN_ID]
        del storage.admin_pending_answers[ADMIN_ID]
        process_admin_answer(message, question_id)
        return
    
    if message.text in ['📋 Задачи (/tasks)', '💬 Активные чаты', '🚫 Бан-лист', '🔇 Мут-лист', '🔄 Обновить']:
        if message.text == '📋 Задачи (/tasks)':
            show_tasks(message)
        elif message.text == '💬 Активные чаты':
            show_active_chats(message)
        elif message.text == '🚫 Бан-лист':
            show_bans(message)
        elif message.text == '🔇 Мут-лист':
            show_mutes(message)
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
        # Проверяем, не заглушен ли пользователь
        if storage.is_muted(user_id) is True:
            mute_data = storage.muted_users[user_id]
            if mute_data['until'] == 0:
                mute_time = "навсегда"
            else:
                remaining = mute_data['until'] - time.time()
                if remaining > 0:
                    mute_time = f"ещё {format_duration(int(remaining))}"
                else:
                    mute_time = "истёк"
            
            bot.send_message(
                user_id,
                f"🔇 *Вам запрещено использовать прямую переписку!*\n\n"
                f"Причина: {mute_data['reason']}\n"
                f"Мут: {mute_time}\n\n"
                f"Вы можете задавать вопросы через раздел 📨 Задать вопрос."
            )
            return
        
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
    
    # Проверяем, есть ли ожидающий ответ с кнопки "Ответить"
    pending_reply = storage.get_pending_reply(user_id)
    if pending_reply and message.content_type == 'text' and not message.text.startswith('/'):
        reply_to_text = pending_reply['reply_to_text']
        storage.clear_pending_reply(user_id)
        
        # Экранируем текст для Markdown
        escaped_reply_text = escape_markdown(message.text)
        escaped_original_text = escape_markdown(reply_to_text)
        
        # Формируем сообщение с ответом
        reply_text = f"↪️ *Ответ на:* {escaped_original_text}\n_________________\n{escaped_reply_text}"
        
        # Отправляем админу
        sender = chat_data['user_name']
        
        try:
            # Экранируем имя отправителя для безопасного использования в Markdown
            escaped_sender = escape_markdown(sender)
            
            sent_msg = bot.send_message(
                ADMIN_ID,
                f"👤 *{escaped_sender}:*\n{reply_text}",
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            
            storage.add_to_message_history(ADMIN_ID, sent_msg.message_id, message.text, is_admin=False)
        except Exception as e:
            bot.send_message(user_id, f"❌ Ошибка отправки: {str(e)}")
        
        return
    
    # Разрешаем ТОЛЬКО текстовые сообщения в чате
    if message.content_type != 'text':
        bot.send_message(user_id, "❌ В чате разрешены только текстовые сообщения.")
        return
    
    # Проверяем лимит символов для чата
    chat_limit = storage.chat_limits.get(user_id, 350)
    if len(message.text) > chat_limit:
        bot.send_message(user_id, f"⚠️ Сообщение слишком длинное ({len(message.text)}/{chat_limit} символов)")
        return
    
    # Проверяем настройки чата
    allow_links = storage.chat_settings.get(user_id, {}).get('allow_links', True)
    sender = chat_data['user_name']
    
    try:
        text = message.text.strip()
        
        # Проверяем есть ли ссылки
        urls = find_all_urls(text)
        
        if urls and not allow_links:
            # Ссылки запрещены - маскируем и завершаем чат
            masked_text, url_count = find_and_mask_urls(text)
            
            # Сохраняем полный текст и ссылки для просмотра
            current_time = datetime.now().strftime("%H:%M")
            current_date = datetime.now().strftime("%d.%m.%Y")
            storage.save_violation_message(user_id, text, urls, current_time, current_date)
            
            # Форматируем ID для копирования
            user_id_display = f"`{user_id}`"
            username_display = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
            
            # Экранируем имя отправителя
            escaped_sender = escape_markdown(sender)
            escaped_username = escape_markdown(username_display)
            
            # Отправляем админу с кнопкой "Ответить"
            admin_message = f"👤 *{escaped_sender}* ({escaped_username}) {user_id_display} отправил ссылку:\n\n{masked_text}"
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_user_{user_id}'),
                types.InlineKeyboardButton('🔇 Заглушить', callback_data=f'mute_user_{user_id}'),
                types.InlineKeyboardButton('*Полностью*', callback_data=f'view_violation_{user_id}'),
                types.InlineKeyboardButton('💬 Ответить', callback_data=f'reply_to_msg_{user_id}_{text[:50].replace("_", " ")}')
            )
            
            sent_msg = bot.send_message(
                ADMIN_ID,
                admin_message,
                parse_mode='Markdown',
                reply_markup=markup,
                disable_web_page_preview=True
            )
            
            storage.add_to_message_history(ADMIN_ID, sent_msg.message_id, masked_text, is_admin=False)
            
            # Завершаем чат
            end_chat(user_id, "link_sent")
            bot.send_message(user_id, "⏹ Переписка завершена. Отправка ссылок запрещена.")
            
            return
        
        # Если ссылки разрешены или их нет
        # Экранируем текст для безопасного использования в callback_data
        safe_text = text[:50].replace('_', ' ').replace('*', '').replace('`', '').replace('[', '').replace(']', '')
        
        # Экранируем имя отправителя
        escaped_sender = escape_markdown(sender)
        escaped_message_text = escape_markdown(text[:500])
        
        # Создаем сообщение с кнопкой "Ответить"
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton('💬 Ответить', callback_data=f'reply_to_msg_{user_id}_{safe_text}')
        )
        
        sent_msg = bot.send_message(
            ADMIN_ID,
            f"👤 *{escaped_sender}:*\n{escaped_message_text}",
            parse_mode='Markdown',
            reply_markup=markup,
            disable_web_page_preview=True
        )
        
        storage.add_to_message_history(ADMIN_ID, sent_msg.message_id, text, is_admin=False)
            
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
            # Экранируем текст для безопасного использования в callback_data
            safe_text = message.text[:50].replace('_', ' ').replace('*', '').replace('`', '').replace('[', '').replace(']', '')
            
            # Экранируем имя админа и текст сообщения
            escaped_admin_name = escape_markdown(chat_data['admin_name'])
            escaped_message_text = escape_markdown(message.text)
            
            # Создаем сообщение с кнопкой "Ответить"
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton('💬 Ответить', callback_data=f'reply_to_msg_admin_{safe_text}')
            )
            
            sent_msg = bot.send_message(
                active_user_id,
                f"👨‍💼 *{escaped_admin_name} (Администратор):*\n{escaped_message_text}",
                parse_mode='Markdown',
                reply_markup=markup
            )
            
            storage.add_to_message_history(active_user_id, sent_msg.message_id, message.text, is_admin=True)
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Не удалось отправить: {str(e)}")

# ===== ФУНКЦИИ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =====
def ask_question_start(user_id):
    can_ask, active_count = storage.can_ask_question(user_id)
    if not can_ask:
        bot.send_message(
            user_id, 
            f"❌ *Превышен лимит активных вопросов!*\n\n"
            f"У вас уже {active_count}/{storage.max_active_questions} активных вопросов.\n"
            f"Дождитесь ответа администратора или отмените некоторые вопросы.",
            parse_mode='Markdown'
        )
        return
    
    msg = bot.send_message(
        user_id,
        "📝 *Напишите ваш вопрос:*\n\n"
        f"Максимум {QUESTION_LIMIT} символов.\n"
        "Разрешены только текстовые сообщения.\n\n"
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
    
    if message.content_type != 'text':
        bot.send_message(
            user_id, 
            "❌ *Поддерживаются только текстовые вопросы!*\n\n"
            "Фото, голосовые и другие медиафайлы не принимаются.\n"
            "Пожалуйста, опишите вопрос текстом.",
            parse_mode='Markdown'
        )
        start_command(message)
        return
    
    set_cooldown(user_id, 'question')
    
    question_text = message.text.strip()
    
    if len(question_text) > QUESTION_LIMIT:
        bot.send_message(user_id, f"❌ Вопрос слишком длинный (макс. {QUESTION_LIMIT} символов).")
        start_command(message)
        return
    
    if len(question_text) < 10:
        bot.send_message(user_id, "❌ Вопрос слишком короткий (минимум 10 символов).")
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
        'created_at': datetime.now().isoformat()
    }
    
    storage.questions[question_id] = question_data
    storage.user_profiles[user_id]['questions_sent'] += 1
    storage.question_counter += 1
    
    notify_admin_about_question(question_id, question_data)
    
    confirm_text = f"✅ *Вопрос #{question_id} отправлен!*\n\nАдминистратор ответит в ближайшее время."
    
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
        types.InlineKeyboardButton('❌ Отклонить', callback_data=f'reject_chat_{chat_request_id}')
    )
    
    bot.send_message(
        ADMIN_ID,
        f"💬 *Запрос на переписку #{chat_request_id}*\n"
        f"От: {username} (`{user_id}`)\n"
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
        can_answer, reason = can_answer_question(question['id'])
        answer_button_text = f'Ответить #{question["id"]}'
        if not can_answer:
            answer_button_text += ' ⏰'
        
        display_text = question.get('masked_text', question['text'])
        text_preview = display_text[:80] + "..." if len(display_text) > 80 else display_text
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(answer_button_text, callback_data=f'answer_{question["id"]}'),
            types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_{question["id"]}'),
            types.InlineKeyboardButton('🔇 Заглушить', callback_data=f'mute_{question["id"]}')
        )
        
        user_id_display = f"`{question['user_id']}`"
        
        question_text = (
            f"🔔 #{question['id']}\n"
            f"👤 {question['username']} ({user_id_display})\n"
            f"⏰ {question['time']} | {question['date']}\n"
        )
        
        if not can_answer:
            question_text += f"\n⚠️ {reason}\n"
        
        question_text += f"\n{text_preview}"
        
        bot.send_message(ADMIN_ID, question_text, parse_mode='Markdown', 
                        reply_markup=markup, disable_web_page_preview=True)

def show_active_chats(message):
    if not storage.active_chats:
        bot.send_message(ADMIN_ID, "💭 Нет активных чатов")
        return
    
    text = "💬 *Активные чаты:*\n\n"
    for user_id, chat_data in storage.active_chats.items():
        if chat_data['admin_id'] == ADMIN_ID:
            chat_limit = storage.chat_limits.get(user_id, 350)
            # Экранируем имя пользователя
            escaped_user_name = escape_markdown(chat_data['user_name'])
            escaped_admin_name = escape_markdown(chat_data['admin_name'])
            
            text += f"👤 {escaped_user_name}\n"
            text += f"ID: `{user_id}`\n"
            text += f"Имя админа: {escaped_admin_name}\n"
            text += f"Лимит: {chat_limit} символов\n"
            text += f"Ссылки: {'✅ Разрешены' if storage.chat_settings.get(user_id, {}).get('allow_links', True) else '❌ Запрещены'}\n\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

def show_bans(message):
    active_bans = []
    for user_id, ban_data in storage.banned_users.items():
        if ban_data['until'] == 0 or time.time() < ban_data['until']:
            active_bans.append((user_id, ban_data))
    
    if not active_bans:
        bot.send_message(ADMIN_ID, "✅ Нет активных банов")
        return
    
    text = "🚫 *Бан-лист:*\n\n"
    for user_id, ban_data in active_bans:
        username = storage.user_profiles.get(user_id, {}).get('username', f'ID: {user_id}')
        
        # Экранируем имя пользователя
        escaped_username = escape_markdown(username)
        escaped_reason = escape_markdown(ban_data['reason'])
        
        if ban_data['until'] == 0:
            duration = "навсегда"
        else:
            remaining = ban_data['until'] - time.time()
            if remaining > 0:
                duration = f"ещё {format_duration(int(remaining))}"
            else:
                duration = "истёк"
        
        text += f"• {escaped_username} (`{user_id}`)\n"
        text += f"  Причина: {escaped_reason}\n"
        text += f"  Бан: {duration}\n\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

def show_mutes(message):
    active_mutes = []
    for user_id, mute_data in storage.muted_users.items():
        if mute_data['until'] == 0 or time.time() < mute_data['until']:
            active_mutes.append((user_id, mute_data))
    
    if not active_mutes:
        bot.send_message(ADMIN_ID, "✅ Нет активных мутов")
        return
    
    text = "🔇 *Мут-лист:*\n\n"
    for user_id, mute_data in active_mutes:
        username = storage.user_profiles.get(user_id, {}).get('username', f'ID: {user_id}')
        
        # Экранируем имя пользователя
        escaped_username = escape_markdown(username)
        escaped_reason = escape_markdown(mute_data['reason'])
        
        if mute_data['until'] == 0:
            duration = "навсегда"
        else:
            remaining = mute_data['until'] - time.time()
            if remaining > 0:
                duration = f"ещё {format_duration(int(remaining))}"
            else:
                duration = "истёк"
        
        text += f"• {escaped_username} (`{user_id}`)\n"
        text += f"  Причина: {escaped_reason}\n"
        text += f"  Мут: {duration}\n\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

def notify_admin_about_question(question_id, question_data):
    display_text = question_data.get('masked_text', question_data['text'])
    text_preview = display_text[:100] + "..." if len(display_text) > 100 else display_text
    
    buttons = []
    
    can_answer, reason = can_answer_question(question_id)
    if can_answer:
        buttons.append(types.InlineKeyboardButton('✏️ Ответить', callback_data=f'answer_{question_id}'))
    else:
        buttons.append(types.InlineKeyboardButton('✏️ Ответить ⏰', callback_data=f'answer_{question_id}'))
    
    buttons.append(types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_{question_id}'))
    buttons.append(types.InlineKeyboardButton('🔇 Заглушить', callback_data=f'mute_{question_id}'))
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(*buttons)
    
    user_id_display = f"`{question_data['user_id']}`"
    
    # Экранируем текст вопроса
    escaped_question_text = escape_markdown(text_preview)
    
    notification = (
        f"📨 *Вопрос #{question_id}*\n"
        f"👤 {question_data['username']} ({user_id_display})\n"
        f"⏰ {question_data['time']} | {question_data['date']}"
    )
    
    if not can_answer:
        escaped_reason = escape_markdown(reason)
        notification += f"\n\n⚠️ {escaped_reason}"
    
    if question_data.get('url_count', 0) > 0:
        url_word = "ссылка" if question_data['url_count'] == 1 else "ссылки"
        notification += f"\n⚠️ *Внимание:* в сообщении присутствует {question_data['url_count']} {url_word}"
    
    notification += f"\n\n💬 {escaped_question_text}"
    
    if question_data.get('url_count', 0) > 0:
        notification += f"\n\n🔗 *Важно:* для просмотра полного текста со ссылками используйте [/full#{question_id}](#full_{question_id})"
    
    bot.send_message(ADMIN_ID, notification, parse_mode='Markdown', 
                     reply_markup=markup, disable_web_page_preview=True)

def process_admin_answer(message, question_id):
    if question_id not in storage.questions:
        bot.send_message(ADMIN_ID, "❌ Вопрос не найден")
        return
    
    can_answer, reason = can_answer_question(question_id)
    if not can_answer:
        bot.send_message(ADMIN_ID, reason)
        return
    
    question = storage.questions[question_id]
    user_id = question['user_id']
    
    admin_name = None
    answer_text = None
    
    if message.content_type == 'text':
        text = message.text
        name_match = re.match(r'^\s*\[([^\]]+)\]\s*(.+)', text)
        if name_match:
            admin_name = name_match.group(1).strip()
            answer_text = name_match.group(2).strip()
        else:
            answer_text = text.strip()
    
    try:
        question_preview = question['text'][:300] + "..." if len(question['text']) > 300 else question['text']
        
        # Экранируем все переменные для безопасного использования в Markdown
        escaped_question_preview = escape_markdown(question_preview)
        escaped_answer_text = escape_markdown(answer_text) if answer_text else ""
        
        if admin_name:
            escaped_admin_name = escape_markdown(admin_name)
            header = f"📩 *Ответ на ваш вопрос #{question_id}:*\n\n"
            header += f"*Вопрос:* {escaped_question_preview}\n\n"
            header += f"*Ответ от \"{escaped_admin_name}\" (администратора):*"
        else:
            header = f"📩 *Ответ на ваш вопрос #{question_id}:*\n\n"
            header += f"*Вопрос:* {escaped_question_preview}\n\n"
            header += f"*Ответ от администрации:*"
        
        if message.content_type == 'text':
            full_message = f"{header}\n\n{escaped_answer_text}"
            bot.send_message(user_id, full_message, parse_mode='Markdown')
        
        # Обновляем статус вопроса
        storage.questions[question_id]['status'] = 'answered'
        storage.questions[question_id]['admin_response'] = answer_text
        storage.questions[question_id]['admin_name'] = admin_name
        storage.questions[question_id]['answer_time'] = datetime.now().strftime("%H:%M")
        
        storage.increment_answer_count(question_id)
        answer_count = storage.get_answer_count(question_id)
        remaining = MAX_ANSWERS_PER_QUESTION - answer_count
        
        if remaining > 0:
            bot.send_message(ADMIN_ID, f"✅ Ответ #{question_id} отправлен {question['username']}\n\n"
                                     f"ℹ️ Можно отправить еще {remaining} ответов на этот вопрос.")
        else:
            bot.send_message(ADMIN_ID, f"✅ Ответ #{question_id} отправлен {question['username']}\n\n"
                                     f"ℹ️ Достигнут лимит ответов на этот вопрос ({MAX_ANSWERS_PER_QUESTION}).")
        
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Ошибка отправки: {str(e)}")
    
    storage.save_data()

# ===== CALLBACK ОБРАБОТЧИК =====
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    if call.data.startswith('view_violation_'):
        user_id = int(call.data.replace('view_violation_', ''))
        show_full_violation_message(ADMIN_ID, user_id)
        bot.answer_callback_query(call.id, "Показываю полное сообщение...")
        return
    
    elif call.data.startswith('accept_chat_'):
        question_id = int(call.data.replace('accept_chat_', ''))
        
        if question_id not in storage.questions:
            bot.answer_callback_query(call.id, "❌ Запрос устарел")
            return
        
        question = storage.questions[question_id]
        user_id = question['user_id']
        
        # Проверяем, не обработан ли уже этот запрос
        if question.get('status') != 'pending':
            bot.answer_callback_query(call.id, "❌ Этот запрос уже был обработан")
            return
        
        storage.questions[question_id]['status'] = 'accepted'
        storage.save_data()
        
        msg = bot.send_message(
            ADMIN_ID,
            f"💬 *Принят запрос на переписку*\n\n"
            f"👤 Пользователь: {question['username']} (`{user_id}`)\n\n"
            f"📝 *Как вас звать в этой переписке?*\n"
            f"(Напишите /cancel для отмены)",
            parse_mode='Markdown'
        )
        
        bot.register_next_step_handler(msg, ask_admin_name_step, user_id, question_id)
        bot.answer_callback_query(call.id, "✅ Запрос принят")
        return
    
    elif call.data.startswith('reject_chat_'):
        question_id = int(call.data.replace('reject_chat_', ''))
        
        if question_id not in storage.questions:
            bot.answer_callback_query(call.id, "❌ Запрос устарел")
            return
        
        question = storage.questions[question_id]
        user_id = question['user_id']
        
        # Проверяем, не обработан ли уже этот запрос
        if question.get('status') != 'pending':
            bot.answer_callback_query(call.id, "❌ Этот запрос уже был обработан")
            return
        
        storage.questions[question_id]['status'] = 'rejected'
        storage.save_data()
        
        bot.answer_callback_query(call.id, "❌ Запрос отклонен")
        
        try:
            bot.send_message(
                user_id,
                "❌ *Администратор отклонил ваш запрос на переписку.*\n\n"
                "Попробуйте задать вопрос через раздел 📨 Задать вопрос."
            )
        except:
            pass
        return
    
    elif call.data.startswith('reply_to_msg_'):
        # Кнопка "Ответить" от админа к пользователю
        parts = call.data.replace('reply_to_msg_', '').split('_', 1)
        if len(parts) == 2:
            user_id_str = parts[0]
            reply_to_text = parts[1]
            
            if user_id_str.isdigit():
                user_id = int(user_id_str)
                
                # Устанавливаем ожидание ответа
                storage.set_pending_reply(ADMIN_ID, 0, reply_to_text)
                
                # Экранируем текст для безопасного отображения
                escaped_reply_to_text = escape_markdown(reply_to_text)
                
                bot.send_message(
                    ADMIN_ID,
                    f"💬 *Вы отвечаете на сообщение:*\n"
                    f"{escaped_reply_to_text}\n\n"
                    f"Введите ваш ответ:",
                    parse_mode='Markdown'
                )
                bot.answer_callback_query(call.id, "✏️ Введите ответ...")
        return
    
    elif call.data.startswith('reply_to_msg_admin_'):
        # Кнопка "Ответить" от пользователя к админу
        reply_to_text = call.data.replace('reply_to_msg_admin_', '').replace('_', ' ')
        
        # Находим активный чат пользователя
        user_id = call.from_user.id
        if is_user_in_chat(user_id):
            # Устанавливаем ожидание ответа
            storage.set_pending_reply(user_id, 0, reply_to_text)
            
            # Экранируем текст для безопасного отображения
            escaped_reply_to_text = escape_markdown(reply_to_text)
            
            bot.send_message(
                user_id,
                f"💬 *Вы отвечаете на сообщение:*\n"
                f"{escaped_reply_to_text}\n\n"
                f"Введите ваш ответ:",
                parse_mode='Markdown'
            )
            bot.answer_callback_query(call.id, "✏️ Введите ответ...")
        return
    
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
            f"ID: `{user_id}`\n\n"
            f"Введите время и причину бана:\n"
            f"Примеры:\n"
            f"• `1d спам` - на 1 день за спам\n"
            f"• `1w нарушение правил` - на 1 неделю\n"
            f"• `нарушение` - навсегда\n\n"
            f"Или нажмите /cancel для отмены",
            parse_mode='Markdown'
        )
        
        bot.register_next_step_handler(msg, process_ban_with_reason, user_id)
        bot.answer_callback_query(call.id, "📝 Введите данные...")
    
    elif call.data.startswith('mute_') or call.data.startswith('mute_user_'):
        if call.data.startswith('mute_'):
            question_id = int(call.data.replace('mute_', ''))
            if question_id not in storage.questions:
                bot.answer_callback_query(call.id, "❌ Вопрос не найден")
                return
            user_id = storage.questions[question_id]['user_id']
        else:
            user_id = int(call.data.replace('mute_user_', ''))
        
        msg = bot.send_message(
            ADMIN_ID,
            f"🔇 *Заглушение пользователя*\n\n"
            f"ID: `{user_id}`\n\n"
            f"Введите время и причину мута:\n"
            f"Примеры:\n"
            f"• `1h флуд` - на 1 час за флуд\n"
            f"• `2d нарушение правил` - на 2 дня\n"
            f"• `нарушение` - навсегда\n\n"
            f"Или нажмите /cancel для отмены",
            parse_mode='Markdown'
        )
        
        bot.register_next_step_handler(msg, process_mute_with_reason, user_id)
        bot.answer_callback_query(call.id, "📝 Введите данные...")
    
    elif call.data.startswith('answer_'):
        question_id = int(call.data.replace('answer_', ''))
        
        if question_id not in storage.questions:
            bot.answer_callback_query(call.id, "❌ Вопрос не найден")
            return
        
        can_answer, reason = can_answer_question(question_id)
        if not can_answer:
            bot.answer_callback_query(call.id, reason)
            return
        
        question = storage.questions[question_id]
        
        storage.admin_pending_answers[ADMIN_ID] = question_id
        
        # Экранируем текст вопроса для безопасного отображения
        escaped_question_text = escape_markdown(question.get('masked_text', question['text'])[:200])
        
        msg = bot.send_message(
            ADMIN_ID,
            f"✏️ *Ответ на вопрос #{question_id}*\n\n"
            f"👤 От: {question['username']} (`{question['user_id']}`)\n"
            f"⏰ {question['time']} | {question['date']}\n"
            f"💬 Вопрос: {escaped_question_text}...\n\n"
            f"*Введите ответ (только текст):*\n"
            f"Используйте [Имя Фамилия] в начале для подписи\n"
            f"Пример: `[Алексей Петров] Ответ...`\n\n"
            f"ℹ️ *Если нужно посмотреть полный текст со ссылками, используйте [/full#{question_id}](#full_{question_id})*",
            parse_mode='Markdown'
        )
        
        bot.answer_callback_query(call.id, "✏️ Введите ответ...")
    
    elif call.data.startswith('full_'):
        question_id = int(call.data.replace('full_', ''))
        show_full_question_text(ADMIN_ID, question_id)
        bot.answer_callback_query(call.id)

def ask_admin_name_step(message, user_id, question_id):
    if message.text == '/cancel':
        bot.send_message(ADMIN_ID, "❌ Создание чата отменено.")
        
        try:
            bot.send_message(
                user_id,
                "❌ *Во время составления правил для переписки, администратор передумал и отклонил ваш запрос.*"
            )
        except:
            pass
        
        if question_id in storage.questions:
            storage.questions[question_id]['status'] = 'rejected'
            storage.save_data()
        
        return
    
    admin_name = message.text.strip()[:30]
    
    if not admin_name:
        bot.send_message(ADMIN_ID, "❌ Имя не может быть пустым.")
        return
    
    if user_id not in storage.active_chats:
        storage.active_chats[user_id] = {}
    
    storage.active_chats[user_id]['admin_name'] = admin_name
    
    msg = bot.send_message(
        ADMIN_ID,
        f"✅ Имя сохранено: *{admin_name}*\n\n"
        f"*Разрешить отправку ссылок?*\n\n"
        f"Напишите `Да` или `Нет` (регистр не важен).\n"
        f"Если выбрать 'Нет', чат автоматически завершится при попытке отправить ссылку.\n\n"
        f"⚠️ *Если ввести что-то другое, по умолчанию будет установлено 'Да'*\n"
        f"(Или /cancel для отмены)",
        parse_mode='Markdown'
    )
    
    bot.register_next_step_handler(msg, ask_links_step, user_id, question_id)

def ask_links_step(message, user_id, question_id):
    if message.text == '/cancel':
        bot.send_message(ADMIN_ID, "❌ Создание чата отменено.")
        
        try:
            bot.send_message(
                user_id,
                "❌ *Во время составления правил для переписки, администратор передумал и отклонил ваш запрос.*"
            )
        except:
            pass
        
        if question_id in storage.questions:
            storage.questions[question_id]['status'] = 'rejected'
            storage.save_data()
        
        return
    
    text = message.text.strip().lower()
    
    if text == 'да':
        allow_links = True
    elif text == 'нет':
        allow_links = False
    else:
        allow_links = True
    
    if user_id not in storage.chat_settings:
        storage.chat_settings[user_id] = {}
    storage.chat_settings[user_id]['allow_links'] = allow_links
    
    msg = bot.send_message(
        ADMIN_ID,
        f"✅ {'Ссылки разрешены' if allow_links else 'Ссылки запрещены'}\n\n"
        f"📝 *Какой лимит символов установим на одно сообщение?*\n\n"
        f"• Минимум: 15 символов\n"
        f"• Максимум: 500 символов\n"
        f"• По умолчанию: 350 символов\n\n"
        f"Введите число (или /cancel для отмены):",
        parse_mode='Markdown'
    )
    
    bot.register_next_step_handler(msg, ask_chat_limit_step, user_id, question_id, allow_links)

def ask_chat_limit_step(message, user_id, question_id, allow_links):
    if message.text == '/cancel':
        bot.send_message(ADMIN_ID, "❌ Создание чата отменено.")
        
        try:
            bot.send_message(
                user_id,
                "❌ *Во время составления правил для переписки, администратор передумал и отклонил ваш запрос.*"
            )
        except:
            pass
        
        if question_id in storage.questions:
            storage.questions[question_id]['status'] = 'rejected'
            storage.save_data()
        
        return
    
    limit = 350
    
    try:
        user_limit = int(message.text.strip())
        
        if 15 <= user_limit <= 500:
            limit = user_limit
            confirmation = f"✅ Лимит установлен: {limit} символов"
        else:
            confirmation = f"⚠️ Введено число вне диапазона. Установлено по умолчанию: {limit} символов"
    except (ValueError, TypeError):
        confirmation = f"⚠️ Неверный формат. Установлено по умолчанию: {limit} символов"
    
    storage.chat_limits[user_id] = limit
    
    complete_chat_setup(user_id, question_id, confirmation, allow_links, limit)

def complete_chat_setup(user_id, question_id, confirmation, allow_links, limit):
    """Завершает настройку чата"""
    question = storage.questions[question_id]
    
    storage.active_chats[user_id].update({
        'admin_id': ADMIN_ID,
        'user_name': question['username'],
        'start_time': datetime.now().isoformat(),
        'question_id': question_id
    })
    
    # Экранируем все переменные для безопасного использования в Markdown
    escaped_admin_name = escape_markdown(storage.active_chats[user_id]['admin_name'])
    escaped_username = escape_markdown(question['username'])
    
    # Сообщение пользователю
    bot.send_message(
        user_id,
        f"💬 *Переписка начата!*\n\n"
        f"👨‍💼 Администратор: *{escaped_admin_name}*\n"
        f"🔗 Ссылки: {'✅ Разрешены' if allow_links else '❌ Запрещены'}\n"
        f"📝 Лимит сообщений: {limit} символов\n\n"
        f"✨ *Теперь вы можете общаться напрямую!*\n"
        f"💬 *Под каждым сообщением есть кнопка 'Ответить'*\n"
        f"⚠️ *Ограничение:* {limit} символов на сообщение\n"
        f"⏹ *Завершить переписку:* /stop\n"
        f"🚫 *Не используйте другие команды в чате*",
        parse_mode='Markdown'
    )
    
    # Сообщение админу с ID пользователя в скобках
    bot.send_message(
        ADMIN_ID,
        f"💬 *Чат начат!*\n\n"
        f"{confirmation}\n"
        f"🔗 Ссылки: {'✅ Разрешены' if allow_links else '❌ Запрещены'}\n\n"
        f"👤 С пользователем: {escaped_username} (`{user_id}`)\n"
        f"👑 Ваше имя в чате: *{escaped_admin_name}*\n\n"
        f"💭 Теперь все ваши сообщения будут пересылаться.\n"
        f"💬 *Под каждым сообщением есть кнопка 'Ответить'*\n"
        f"⏹ Используйте /stop для завершения.",
        parse_mode='Markdown'
    )
    
    storage.save_data()

def process_ban_with_reason(message, user_id):
    if message.text == '/cancel':
        bot.send_message(ADMIN_ID, "❌ Блокировка отменена.")
        return
    
    text = message.text.strip()
    
    parts = text.split(maxsplit=1)
    duration_str = ""
    reason = "Нарушение правил"
    
    if len(parts) == 1:
        if re.search(r'\d+[ymondhs]', parts[0].lower()):
            duration_str = parts[0]
        else:
            reason = parts[0]
    elif len(parts) == 2:
        if re.search(r'\d+[ymondhs]', parts[0].lower()):
            duration_str = parts[0]
            reason = parts[1]
        else:
            reason = text
    
    duration_seconds = parse_duration(duration_str)
    
    storage.ban_user(user_id, duration_seconds, reason)
    
    if user_id in storage.active_chats:
        end_chat(user_id, "ban")
    
    if user_id in storage.violation_messages:
        storage.clear_violation_message(user_id)
    
    duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
    username = storage.user_profiles.get(user_id, {}).get('username', f'ID: {user_id}')
    
    # Экранируем имя пользователя и причину
    escaped_username = escape_markdown(username)
    escaped_reason = escape_markdown(reason)
    
    bot.send_message(ADMIN_ID, f"🚫 Пользователь `{user_id}` ({escaped_username}) забанен на {duration_text}.\nПричина: {escaped_reason}")
    
    try:
        if duration_seconds == 0:
            ban_time = "навсегда"
        else:
            ban_time = format_duration(duration_seconds)
        
        bot.send_message(
            user_id,
            f"🚫 Вы были заблокированы администратором.\n"
            f"Причина: {reason}\n"
            f"Срок: {ban_time}"
        )
    except:
        pass
    
    storage.save_data()

def process_mute_with_reason(message, user_id):
    if message.text == '/cancel':
        bot.send_message(ADMIN_ID, "❌ Заглушение отменено.")
        return
    
    text = message.text.strip()
    
    parts = text.split(maxsplit=1)
    duration_str = ""
    reason = "Нарушение правил"
    
    if len(parts) == 1:
        if re.search(r'\d+[ymondhs]', parts[0].lower()):
            duration_str = parts[0]
        else:
            reason = parts[0]
    elif len(parts) == 2:
        if re.search(r'\d+[ymondhs]', parts[0].lower()):
            duration_str = parts[0]
            reason = parts[1]
        else:
            reason = text
    
    duration_seconds = parse_duration(duration_str)
    
    storage.mute_user(user_id, duration_seconds, reason)
    
    duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
    username = storage.user_profiles.get(user_id, {}).get('username', f'ID: {user_id}')
    
    # Экранируем имя пользователя и причину
    escaped_username = escape_markdown(username)
    escaped_reason = escape_markdown(reason)
    
    bot.send_message(ADMIN_ID, f"🔇 Пользователь `{user_id}` ({escaped_username}) заглушен на {duration_text}.\nПричина: {escaped_reason}")
    
    try:
        if duration_seconds == 0:
            mute_time = "навсегда"
        else:
            mute_time = format_duration(duration_seconds)
        
        bot.send_message(
            user_id,
            f"🔇 Вы были заглушены администратором.\n\n"
            f"⚠️ *Вам запрещено использовать прямую переписку.*\n\n"
            f"Причина: {reason}\n"
            f"Срок: {mute_time}\n\n"
            f"Вы по-прежнему можете задавать вопросы через раздел 📨 Задать вопрос."
        )
    except:
        pass
    
    storage.save_data()

# ===== ЗАПУСК =====
if __name__ == '__main__':
    print("=" * 50)
    print(f"🤖 Бот запущен | Админ: {ADMIN_ID}")
    print(f"👥 Пользователей: {len(storage.user_profiles)}")
    print(f"📨 Вопросов: {len(storage.questions)}")
    
    active_bans = 0
    for user_id, ban_data in storage.banned_users.items():
        if ban_data['until'] == 0 or time.time() < ban_data['until']:
            active_bans += 1
    
    active_mutes = 0
    for user_id, mute_data in storage.muted_users.items():
        if mute_data['until'] == 0 or time.time() < mute_data['until']:
            active_mutes += 1
    
    print(f"🚫 Активных банов: {active_bans}")
    print(f"🔇 Активных мутов: {active_mutes}")
    print(f"💬 Активных чатов: {len(storage.active_chats)}")
    print(f"⚠️  Нарушений ссылок: {len(storage.violation_messages)}")
    print(f"📝 Максимум активных вопросов: {storage.max_active_questions}")
    print(f"🛡️  Антиспам: {SPAM_LIMIT_MESSAGES} сообщений за {SPAM_LIMIT_SECONDS} секунд")
    print("=" * 50)
    
    # Запускаем поток для проверки истекших банов и мутов
    expiration_check_thread = threading.Thread(target=check_ban_expirations, daemon=True)
    expiration_check_thread.start()
    
    try:
        bot.polling(none_stop=True, interval=0)
    except Exception as e:
        print(f"Ошибка при запуске бота: {e}")
