import telebot
import os
import json
import threading
import time
from datetime import datetime, timedelta
from telebot import types
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))
ADMIN_ID = 6337781618  # Ваш основной ID админа

# ===== РАСШИРЕННЫЕ ХРАНИЛИЩА =====
class BotStorage:
    def __init__(self):
        # Основные хранилища
        self.questions = {}  # {номер: {данные вопроса}}
        self.active_chats = {}  # {user_id: {данные чата}}
        self.banned_users = set()  # ID забаненных
        self.user_profiles = {}  # {user_id: {username, имя_в_чате, etc}}
        self.admin_profiles = {}  # {admin_id: {имя_в_чате, статус}}
        self.pending_responses = {}  # Ожидающие ответы от админов
        self.chat_history = {}  # История всех переписок
        self.media_cache = {}  # Кэш медиафайлов
        
        # Статистика
        self.stats = {
            'total_questions': 0,
            'answered_questions': 0,
            'total_chats': 0,
            'completed_chats': 0,
            'banned_users': 0,
            'active_sessions': 0
        }
        
        # Загружаем сохраненные данные
        self.load_data()
    
    def save_data(self):
        """Сохраняем все данные в файлы"""
        try:
            data = {
                'questions': self.questions,
                'banned_users': list(self.banned_users),
                'user_profiles': self.user_profiles,
                'stats': self.stats
            }
            with open('bot_data.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # Сохраняем историю отдельно
            with open('chat_history.json', 'w', encoding='utf-8') as f:
                json.dump(self.chat_history, f, ensure_ascii=False, indent=2)
                
            logger.info("Данные сохранены")
        except Exception as e:
            logger.error(f"Ошибка сохранения: {e}")
    
    def load_data(self):
        """Загружаем сохраненные данные"""
        try:
            if os.path.exists('bot_data.json'):
                with open('bot_data.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.questions = data.get('questions', {})
                    self.banned_users = set(data.get('banned_users', []))
                    self.user_profiles = data.get('user_profiles', {})
                    self.stats = data.get('stats', self.stats)
            
            if os.path.exists('chat_history.json'):
                with open('chat_history.json', 'r', encoding='utf-8') as f:
                    self.chat_history = json.load(f)
                    
            logger.info("Данные загружены")
        except Exception as e:
            logger.error(f"Ошибка загрузки: {e}")

storage = BotStorage()
question_counter = len(storage.questions) + 1

# ===== СИСТЕМА КОНТРОЛЯ АДМИНОВ =====
def is_admin(user_id):
    """Проверяет, является ли пользователь админом"""
    return user_id == ADMIN_ID  # Можно расширить для нескольких админов

def prevent_admin_action(user_id, action_type):
    """Блокирует действия админов"""
    if is_admin(user_id):
        actions = {
            'ask_question': "Администраторы не могут задавать вопросы через бота.",
            'request_chat': "Администраторы не могут запрашивать переписку.",
            'ban_self': "Вы не можете забанить себя.",
            'clear_self': "Вы не можете очистить свою историю."
        }
        return actions.get(action_type, "Это действие недоступно для администраторов.")
    return None

# ===== УЛУЧШЕННЫЙ ТАЙМЕР ЧАТОВ =====
class ChatManager:
    def __init__(self):
        self.active_timers = {}
        
    def start_chat_timer(self, user_id, chat_data):
        """Запускает таймер для чата"""
        timer = threading.Timer(300, self.chat_timeout, args=[user_id])  # 5 минут
        timer.start()
        self.active_timers[user_id] = {
            'timer': timer,
            'start_time': datetime.now(),
            'data': chat_data
        }
    
    def reset_chat_timer(self, user_id):
        """Сбрасывает таймер чата"""
        if user_id in self.active_timers:
            self.active_timers[user_id]['timer'].cancel()
            self.start_chat_timer(user_id, self.active_timers[user_id]['data'])
    
    def chat_timeout(self, user_id):
        """Таймаут чата по неактивности"""
        if user_id in storage.active_chats:
            chat_data = storage.active_chats[user_id]
            bot.send_message(user_id, "⏳ *Переписка завершена* из-за неактивности (5 минут)", parse_mode='Markdown')
            bot.send_message(ADMIN_ID, f"⏳ Чат с {chat_data['user_name']} завершен по таймауту")
            
            # Сохраняем в историю
            self.save_chat_history(user_id, "timeout")
            del storage.active_chats[user_id]
            
            if user_id in self.active_timers:
                del self.active_timers[user_id]
    
    def stop_chat_timer(self, user_id):
        """Останавливает таймер чата"""
        if user_id in self.active_timers:
            self.active_timers[user_id]['timer'].cancel()
            del self.active_timers[user_id]
    
    def save_chat_history(self, user_id, end_reason="manual"):
        """Сохраняет историю чата"""
        if user_id in storage.active_chats:
            chat_data = storage.active_chats[user_id]
            history_entry = {
                'user_id': user_id,
                'user_name': chat_data['user_name'],
                'admin_name': chat_data['admin_name'],
                'start_time': chat_data['start_time'].isoformat(),
                'end_time': datetime.now().isoformat(),
                'end_reason': end_reason,
                'messages': chat_data.get('messages', [])
            }
            
            if user_id not in storage.chat_history:
                storage.chat_history[user_id] = []
            storage.chat_history[user_id].append(history_entry)
            storage.save_data()

chat_manager = ChatManager()

# ===== РАСШИРЕННЫЙ ИНТЕРФЕЙС ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =====
@bot.message_handler(commands=['start'])
def start(message):
    """Улучшенное меню старта с проверкой бана"""
    user_id = message.from_user.id
    
    # Проверка бана
    if user_id in storage.banned_users:
        bot.send_message(user_id, "🚫 *Доступ запрещен*\n\nВы были заблокированы администратором.", parse_mode='Markdown')
        return
    
    # Регистрация пользователя
    if user_id not in storage.user_profiles:
        storage.user_profiles[user_id] = {
            'username': message.from_user.username or message.from_user.first_name,
            'first_name': message.from_user.first_name,
            'registration_date': datetime.now().isoformat(),
            'question_count': 0,
            'chat_count': 0
        }
    
    # Блокировка действий для админов
    if is_admin(user_id):
        bot.send_message(user_id, "👑 *Панель администратора*\n\nИспользуйте /admin для доступа к функциям управления.", parse_mode='Markdown')
        return
    
    # Создаем красивую клавиатуру
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📨 Задать вопрос'),
        types.KeyboardButton('💬 Прямая переписка'),
        types.KeyboardButton('ℹ️ Помощь'),
        types.KeyboardButton('📊 Мой профиль')
    )
    
    welcome_text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Я — интеллектуальный помощник администрации.\n"
        "Выберите действие:\n\n"
        "• *Задать вопрос* — получите письменный ответ\n"
        "• *Прямая переписка* — живой диалог с админом\n"
        "• *Помощь* — инструкции по использованию\n"
        "• *Мой профиль* — статистика и настройки"
    )
    
    bot.send_message(user_id, welcome_text, parse_mode='Markdown', reply_markup=markup)
    storage.save_data()

@bot.message_handler(func=lambda m: m.text in ['📨 Задать вопрос', '💬 Прямая переписка', 'ℹ️ Помощь', '📊 Мой профиль'])
def handle_user_menu(message):
    """Обработка меню пользователя"""
    user_id = message.from_user.id
    
    # Блокировка для админов
    if is_admin(user_id):
        error_msg = prevent_admin_action(user_id, 'ask_question' if message.text == '📨 Задать вопрос' else 'request_chat')
        if error_msg:
            bot.send_message(user_id, error_msg)
        return
    
    if user_id in storage.banned_users:
        bot.send_message(user_id, "🚫 Ваш доступ заблокирован")
        return
    
    if message.text == '📨 Задать вопрос':
        ask_question_flow(message)
    elif message.text == '💬 Прямая переписка':
        request_chat_flow(message)
    elif message.text == 'ℹ️ Помощь':
        show_help(message)
    elif message.text == '📊 Мой профиль':
        show_user_profile(message)

def ask_question_flow(message):
    """Процесс задания вопроса"""
    msg = bot.send_message(message.chat.id, 
        "📝 *Задайте ваш вопрос*\n\n"
        "Опишите подробно вашу проблему или вопрос. "
        "Администратор ответит в ближайшее время.\n\n"
        "_Вы можете прикрепить фото, документ или голосовое сообщение._",
        parse_mode='Markdown',
        reply_markup=types.ReplyKeyboardRemove()
    )
    bot.register_next_step_handler(msg, process_user_question)

def process_user_question(message):
    """Обработка вопроса от пользователя"""
    global question_counter
    user_id = message.from_user.id
    
    # Проверяем медиа-контент
    has_media = False
    media_info = ""
    
    if message.content_type == 'photo':
        has_media = True
        media_info = "[Фото] "
        # Сохраняем ID фото
        file_id = message.photo[-1].file_id
        if user_id not in storage.media_cache:
            storage.media_cache[user_id] = []
        storage.media_cache[user_id].append({'type': 'photo', 'file_id': file_id, 'question_id': question_counter})
    
    elif message.content_type == 'document':
        has_media = True
        media_info = f"[Документ: {message.document.file_name}] "
    
    elif message.content_type == 'voice':
        has_media = True
        media_info = "[Голосовое сообщение] "
    
    elif message.content_type == 'text':
        text_content = message.text
    else:
        bot.send_message(user_id, "❌ Этот тип контента не поддерживается")
        return
    
    # Получаем текст (если есть)
    text_content = message.caption if has_media and message.caption else (message.text if not has_media else "")
    
    # Сохраняем вопрос
    question_data = {
        'id': question_counter,
        'user_id': user_id,
        'username': storage.user_profiles[user_id]['username'],
        'text': text_content,
        'has_media': has_media,
        'media_type': message.content_type if has_media else None,
        'media_info': media_info,
        'timestamp': datetime.now().isoformat(),
        'status': 'pending',
        'admin_response': None,
        'response_time': None
    }
    
    storage.questions[question_counter] = question_data
    storage.user_profiles[user_id]['question_count'] += 1
    storage.stats['total_questions'] += 1
    
    # Уведомляем админа
    notify_admin_about_question(question_counter, question_data)
    
    # Подтверждение пользователю
    confirm_text = (
        f"✅ *Вопрос #{question_counter} принят!*\n\n"
        f"Статус: ⏳ Ожидает ответа\n"
        f"Время: {datetime.now().strftime('%H:%M')}\n\n"
        f"Администратор ответит в ближайшее время."
    )
    bot.send_message(user_id, confirm_text, parse_mode='Markdown')
    
    # Возвращаем меню
    show_main_menu(user_id)
    
    question_counter += 1
    storage.save_data()

def request_chat_flow(message):
    """Процесс запроса переписки"""
    user_id = message.from_user.id
    
    # Проверяем, нет ли уже активного чата
    if user_id in storage.active_chats:
        bot.send_message(user_id, "💬 У вас уже есть активная переписка!")
        return
    
    # Создаем запрос
    request_id = f"chat_req_{user_id}_{int(time.time())}"
    
    # Сохраняем в ожидающие
    storage.pending_responses[request_id] = {
        'user_id': user_id,
        'username': storage.user_profiles[user_id]['username'],
        'timestamp': datetime.now().isoformat(),
        'status': 'waiting'
    }
    
    # Отправляем запрос админу
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('✅ Принять', callback_data=f'accept_chat_{request_id}'),
        types.InlineKeyboardButton('❌ Отклонить', callback_data=f'decline_chat_{request_id}')
    )
    
    request_text = (
        f"💬 *Новый запрос на переписку*\n\n"
        f"👤 Пользователь: {storage.user_profiles[user_id]['username']}\n"
        f"🆔 ID: `{user_id}`\n"
        f"📊 Вопросов задано: {storage.user_profiles[user_id]['question_count']}\n"
        f"⏰ Время: {datetime.now().strftime('%H:%M')}"
    )
    
    bot.send_message(ADMIN_ID, request_text, parse_mode='Markdown', reply_markup=markup)
    
    # Уведомляем пользователя
    bot.send_message(user_id, 
        "💭 *Запрос отправлен*\n\n"
        "Администратор уведомлен. Ожидайте подтверждения...",
        parse_mode='Markdown'
    )

# ===== РАСШИРЕННАЯ АДМИН-ПАНЕЛЬ =====
@bot.message_handler(commands=['admin', 'админ'])
def admin_panel(message):
    """Полноценная админ-панель"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.send_message(user_id, "⛔ У вас нет доступа к этой команде")
        return
    
    # Создаем профессиональную клавиатуру
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    
    # Первый ряд: основные функции
    markup.row(
        types.KeyboardButton('📋 Задачи (/Tasks)'),
        types.KeyboardButton('💬 Активные чаты'),
        types.KeyboardButton('📊 Статистика')
    )
    
    # Второй ряд: управление
    markup.row(
        types.KeyboardButton('🚫 Управление банами'),
        types.KeyboardButton('👥 Пользователи'),
        types.KeyboardButton('⚙️ Настройки')
    )
    
    # Третий ряд: утилиты
    markup.row(
        types.KeyboardButton('🔄 Обновить'),
        types.KeyboardButton('❓ Помощь'),
        types.KeyboardButton('🧹 Очистка')
    )
    
    admin_text = (
        f"👑 *Панель администратора*\n\n"
        f"Добро пожаловать, Администратор!\n\n"
        f"📈 *Текущая статистика:*\n"
        f"• Вопросов в ожидании: {len([q for q in storage.questions.values() if q['status'] == 'pending'])}\n"
        f"• Активных чатов: {len(storage.active_chats)}\n"
        f"• Всего пользователей: {len(storage.user_profiles)}\n"
        f"• Забанено: {len(storage.banned_users)}\n\n"
        f"🕐 Время сервера: {datetime.now().strftime('%H:%M:%S')}"
    )
    
    bot.send_message(user_id, admin_text, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == '📋 Задачи (/Tasks)' and is_admin(m.from_user.id))
def show_tasks(message):
    """Показывает все задачи (вопросы без ответов)"""
    pending_questions = [q for q in storage.questions.values() if q['status'] == 'pending']
    
    if not pending_questions:
        bot.send_message(ADMIN_ID, "✅ *Нет задач в ожидании*\n\nВсе вопросы обработаны!", parse_mode='Markdown')
        return
    
    # Отправляем общее количество
    bot.send_message(ADMIN_ID, 
        f"📋 *Задачи на рассмотрение*\n\n"
        f"Всего задач: *{len(pending_questions)}*\n"
        f"Отсортировано по времени получения",
        parse_mode='Markdown'
    )
    
    # Отправляем каждую задачу отдельным сообщением с кнопками
    for question in sorted(pending_questions, key=lambda x: x['timestamp']):
        question_text = (
            f"🔔 *Задача #{question['id']}*\n\n"
            f"👤 Пользователь: {question['username']}\n"
            f"🆔 ID: `{question['user_id']}`\n"
            f"⏰ Получено: {datetime.fromisoformat(question['timestamp']).strftime('%H:%M')}\n\n"
        )
        
        if question['has_media']:
            question_text += f"📎 {question['media_info']}\n"
        
        question_text += f"💬 Вопрос: {question['text'][:200]}..." if len(question['text']) > 200 else f"💬 Вопрос: {question['text']}"
        
        # Создаем интерактивные кнопки
        markup = types.InlineKeyboardMarkup(row_width=3)
        markup.add(
            types.InlineKeyboardButton('✏️ Ответить', callback_data=f'answer_task_{question["id"]}'),
            types.InlineKeyboardButton('👁 Просмотреть', callback_data=f'view_task_{question["id"]}'),
            types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_from_task_{question["id"]}')
        )
        
        # Если есть медиа, пытаемся показать превью
        if question['has_media'] and question['user_id'] in storage.media_cache:
            # Здесь можно добавить отправку медиа
            pass
        
        bot.send_message(ADMIN_ID, question_text, parse_mode='Markdown', reply_markup=markup)
    
    # Кнопка для массовых действий
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📥 Экспорт всех задач', callback_data='export_tasks'))
    
    bot.send_message(ADMIN_ID, 
        f"📊 *Сводка по задачам*\n"
        f"Используйте кнопки под каждым вопросом для действий.",
        parse_mode='Markdown',
        reply_markup=markup
    )

@bot.message_handler(commands=['Tasks'])
def tasks_command(message):
    """Команда /Tasks для быстрого доступа"""
    if is_admin(message.from_user.id):
        show_tasks(message)

# ===== СИСТЕМА ПЕРЕПИСКИ С ИМЕНАМИ =====
@bot.callback_query_handler(func=lambda call: call.data.startswith('accept_chat_'))
def accept_chat_request(call):
    """Админ принимает запрос на переписку"""
    request_id = call.data.replace('accept_chat_', '')
    
    if request_id not in storage.pending_responses:
        bot.answer_callback_query(call.id, "Запрос устарел или уже обработан")
        return
    
    request_data = storage.pending_responses[request_id]
    user_id = request_data['user_id']
    
    # Удаляем из ожидающих
    del storage.pending_responses[request_id]
    
    # Спрашиваем у админа, как его звать
    msg = bot.send_message(ADMIN_ID, 
        f"✅ *Принят запрос на переписку*\n\n"
        f"Пользователь: {request_data['username']}\n\n"
        f"📝 *Как вас звать в этой переписке?*\n"
        f"Напишите имя, которое будет отображаться у пользователя\n"
        f"(например: *Антон*, *Техподдержка*, *Менеджер*)\n\n"
        f"_Вы можете использовать /cancel для отмены_",
        parse_mode='Markdown'
    )
    
    # Сохраняем временные данные
    storage.pending_responses[f'waiting_name_{user_id}'] = {
        'request_id': request_id,
        'user_id': user_id,
        'username': request_data['username']
    }
    
    bot.register_next_step_handler(msg, process_admin_name, user_id)
    bot.answer_callback_query(call.id, "Запрос принят")

def process_admin_name(message, user_id):
    """Обрабатывает имя админа для чата"""
    if message.text == '/cancel':
        bot.send_message(ADMIN_ID, "❌ Создание чата отменено")
        if f'waiting_name_{user_id}' in storage.pending_responses:
            del storage.pending_responses[f'waiting_name_{user_id}']
        return
    
    admin_name = message.text.strip()
    
    if len(admin_name) > 20:
        bot.send_message(ADMIN_ID, "❌ Имя слишком длинное. Максимум 20 символов.")
        msg = bot.send_message(ADMIN_ID, "Введите более короткое имя:")
        bot.register_next_step_handler(msg, process_admin_name, user_id)
        return
    
    # Создаем активный чат
    storage.active_chats[user_id] = {
        'admin_id': ADMIN_ID,
        'user_name': storage.pending_responses[f'waiting_name_{user_id}']['username'],
        'admin_name': admin_name,
        'start_time': datetime.now(),
        'messages': [],
        'status': 'active'
    }
    
    # Удаляем временные данные
    del storage.pending_responses[f'waiting_name_{user_id}']
    
    # Уведомляем пользователя
    bot.send_message(user_id,
        f"💬 *Переписка начата*\n\n"
        f"✅ Администратор принял ваш запрос!\n\n"
        f"👨‍💼 *{admin_name} (Администратор)*\n"
        f"Теперь вы можете общаться напрямую.\n\n"
        f"📝 Просто напишите сообщение — оно будет доставлено.",
        parse_mode='Markdown'
    )
    
    # Уведомляем админа
    bot.send_message(ADMIN_ID,
        f"💬 *Чат начат*\n\n"
        f"Пользователь: {storage.active_chats[user_id]['user_name']}\n"
        f"Ваше имя в чате: *{admin_name}*\n\n"
        f"Теперь все ваши сообщения будут пересылаться пользователю.\n"
        f"Используйте /stopchat для завершения.",
        parse_mode='Markdown'
    )
    
    # Запускаем таймер
    chat_manager.start_chat_timer(user_id, storage.active_chats[user_id])
    
    storage.stats['total_chats'] += 1
    storage.save_data()

# ===== ОБРАБОТКА СООБЩЕНИЙ В ЧАТЕ =====
@bot.message_handler(func=lambda m: m.from_user.id in storage.active_chats)
def handle_user_chat_message(message):
    """Обрабатывает сообщения от пользователя в активном чате"""
    user_id = message.from_user.id
    chat_data = storage.active_chats.get(user_id)
    
    if not chat_data:
        return
    
    # Сбрасываем таймер
    chat_manager.reset_chat_timer(user_id)
    
    # Формируем сообщение для админа
    admin_message = f"👤 *{chat_data['user_name']}:*\n"
    
    # Обрабатываем разные типы контента
    if message.content_type == 'text':
        admin_message += message.text
        
        # Сохраняем в историю
        chat_data['messages'].append({
            'from': 'user',
            'text': message.text,
            'time': datetime.now().isoformat(),
            'type': 'text'
        })
        
    elif message.content_type == 'photo':
        admin_message += "[Фото]\n"
        if message.caption:
            admin_message += f"Подпись: {message.caption}"
        
        # Пересылаем фото админу
        bot.send_photo(ADMIN_ID, message.photo[-1].file_id, 
                      caption=f"👤 {chat_data['user_name']} отправил(а) фото")
        
        chat_data['messages'].append({
            'from': 'user',
            'type': 'photo',
            'file_id': message.photo[-1].file_id,
            'caption': message.caption,
            'time': datetime.now().isoformat()
        })
    
    elif message.content_type == 'document':
        admin_message += f"[Документ: {message.document.file_name}]"
        
        bot.send_document(ADMIN_ID, message.document.file_id,
                         caption=f"👤 {chat_data['user_name']}: {message.document.file_name}")
        
        chat_data['messages'].append({
            'from': 'user',
            'type': 'document',
            'file_name': message.document.file_name,
            'file_id': message.document.file_id,
            'time': datetime.now().isoformat()
        })
    
    elif message.content_type == 'voice':
        admin_message += "[Голосовое сообщение]"
        
        bot.send_voice(ADMIN_ID, message.voice.file_id,
                      caption=f"👤 {chat_data['user_name']}: голосовое")
        
        chat_data['messages'].append({
            'from': 'user',
            'type': 'voice',
            'file_id': message.voice.file_id,
            'time': datetime.now().isoformat()
        })
    
    else:
        admin_message += f"[{message.content_type.capitalize()}]"
    
    # Отправляем текстовое уведомление админу
    if message.content_type == 'text':
        bot.send_message(ADMIN_ID, admin_message, parse_mode='Markdown')
    
    storage.save_data()

@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.chat.id == ADMIN_ID)
def handle_admin_chat_message(message):
    """Обрабатывает сообщения от админа (пересылает в активный чат)"""
    # Находим активный чат
    active_user_id = None
    for user_id, chat_data in storage.active_chats.items():
        if chat_data['admin_id'] == ADMIN_ID:
            active_user_id = user_id
            break
    
    if not active_user_id:
        # Проверяем, не команда ли это
        if message.text and message.text.startswith('/'):
            return  # Команды обрабатываются отдельно
        bot.send_message(ADMIN_ID, "❌ Нет активных чатов для отправки сообщения")
        return
    
    chat_data = storage.active_chats[active_user_id]
    
    # Сбрасываем таймер
    chat_manager.reset_chat_timer(active_user_id)
    
    # Формируем сообщение для пользователя
    user_message = f"👨‍💼 *{chat_data['admin_name']} (Администратор):*\n"
    
    # Обрабатываем контент
    if message.content_type == 'text':
        # Проверяем команды
        if message.text.startswith('/stop'):
            end_chat(active_user_id, ADMIN_ID, "admin_stop")
            return
        elif message.text.startswith('/clear'):
            clear_chat(active_user_id, ADMIN_ID)
            return
        
        user_message += message.text
        
        # Сохраняем в историю
        chat_data['messages'].append({
            'from': 'admin',
            'text': message.text,
            'time': datetime.now().isoformat(),
            'type': 'text'
        })
        
        # Отправляем пользователю
        try:
            bot.send_message(active_user_id, user_message, parse_mode='Markdown')
            bot.send_message(ADMIN_ID, f"✅ Отправлено пользователю {chat_data['user_name']}")
        except Exception as e:
            bot.send_message(ADMIN_ID, f"❌ Не удалось отправить: {str(e)}")
    
    elif message.content_type == 'photo':
        user_message += "[Фото]"
        if message.caption:
            user_message += f"\n{message.caption}"
        
        try:
            bot.send_photo(active_user_id, message.photo[-1].file_id,
                          caption=f"👨‍💼 {chat_data['admin_name']} (Администратор)")
            bot.send_message(ADMIN_ID, f"✅ Фото отправлено {chat_data['user_name']}")
        except:
            bot.send_message(ADMIN_ID, f"❌ Не удалось отправить фото")
    
    elif message.content_type == 'document':
        try:
            bot.send_document(active_user_id, message.document.file_id,
                            caption=f"👨‍💼 {chat_data['admin_name']} (Администратор)")
            bot.send_message(ADMIN_ID, f"✅ Документ отправлен {chat_data['user_name']}")
        except:
            bot.send_message(ADMIN_ID, "❌ Не удалось отправить документ")
    
    elif message.content_type == 'voice':
        try:
            bot.send_voice(active_user_id, message.voice.file_id,
                          caption=f"👨‍💼 {chat_data['admin_name']} (Администратор)")
            bot.send_message(ADMIN_ID, f"✅ Голосовое отправлено {chat_data['user_name']}")
        except:
            bot.send_message(ADMIN_ID, "❌ Не удалось отправить голосовое")
    
    storage.save_data()

# ===== КОМАНДЫ УПРАВЛЕНИЯ ЧАТОМ =====
@bot.message_handler(commands=['stop', 'stopchat'])
def stop_chat_command(message):
    """Команда для завершения чата"""
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔ Эта команда только для администраторов")
        return
    
    # Находим активный чат
    active_user_id = None
    for user_id, chat_data in storage.active_chats.items():
        if chat_data['admin_id'] == ADMIN_ID:
            active_user_id = user_id
            break
    
    if active_user_id:
        end_chat(active_user_id, message.from_user.id, "command")
    else:
        bot.send_message(ADMIN_ID, "❌ Нет активных чатов для завершения")

def end_chat(user_id, admin_id, reason="manual"):
    """Завершает чат"""
    if user_id in storage.active_chats:
        chat_data = storage.active_chats[user_id]
        
        # Останавливаем таймер
        chat_manager.stop_chat_timer(user_id)
        
        # Сохраняем историю
        chat_manager.save_chat_history(user_id, reason)
        
        # Уведомляем пользователя
        bot.send_message(user_id, 
            f"⏹ *Переписка завершена*\n\n"
            f"Администратор завершил диалог.\n"
            f"Спасибо за обращение!",
            parse_mode='Markdown'
        )
        
        # Уведомляем админа
        duration = (datetime.now() - chat_data['start_time']).seconds
        minutes = duration // 60
        seconds = duration % 60
        
        bot.send_message(admin_id,
            f"⏹ *Чат завершен*\n\n"
            f"Пользователь: {chat_data['user_name']}\n"
            f"Длительность: {minutes} мин {seconds} сек\n"
            f"Сообщений: {len(chat_data['messages'])}\n\n"
            f"История чата сохранена.",
            parse_mode='Markdown'
        )
        
        # Удаляем из активных
        del storage.active_chats[user_id]
        storage.stats['completed_chats'] += 1
        storage.save_data()

@bot.message_handler(commands=['clear'])
def clear_chat_command(message):
    """Очистка чата (только для админа)"""
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔ Эта команда только для администраторов")
        return
    
    # Находим активный чат
    active_user_id = None
    for user_id, chat_data in storage.active_chats.items():
        if chat_data['admin_id'] == ADMIN_ID:
            active_user_id = user_id
            break
    
    if active_user_id:
        clear_chat(active_user_id, message.from_user.id)
    else:
        bot.send_message(ADMIN_ID, "❌ Нет активных чатов для очистки")

def clear_chat(user_id, admin_id):
    """Очищает текущий чат (сохраняя историю)"""
    if user_id in storage.active_chats:
        chat_data = storage.active_chats[user_id]
        
        # Сохраняем текущую историю
        chat_manager.save_chat_history(user_id, "cleared")
        
        # Создаем новый чистый чат с теми же параметрами
        storage.active_chats[user_id] = {
            'admin_id': chat_data['admin_id'],
            'user_name': chat_data['user_name'],
            'admin_name': chat_data['admin_name'],
            'start_time': datetime.now(),
            'messages': [],
            'status': 'active'
        }
        
        bot.send_message(admin_id, f"🧹 Чат с {chat_data['user_name']} очищен. История сохранена.")
        bot.send_message(user_id, "🧹 История текущей переписки очищена администратором.")
        
        # Перезапускаем таймер
        chat_manager.stop_chat_timer(user_id)
        chat_manager.start_chat_timer(user_id, storage.active_chats[user_id])
        
        storage.save_data()

# ===== СИСТЕМА БАНОВ =====
@bot.message_handler(commands=['ban'])
def ban_command(message):
    """Команда для бана пользователя"""
    if not is_admin(message.from_user.id):
        return
    
    if len(message.text.split()) < 2:
        bot.send_message(ADMIN_ID, "Используйте: /ban @username или /ban ID")
        return
    
    target = message.text.split(maxsplit=1)[1]
    
    # Определяем, это ID или username
    user_id_to_ban = None
    
    if target.startswith('@'):
        # Ищем по username
        username = target[1:]
        for uid, profile in storage.user_profiles.items():
            if profile['username'].lower() == username.lower():
                user_id_to_ban = uid
                break
    elif target.isdigit():
        user_id_to_ban = int(target)
    
    if not user_id_to_ban:
        bot.send_message(ADMIN_ID, f"❌ Пользователь не найден: {target}")
        return
    
    if user_id_to_ban == ADMIN_ID:
        bot.send_message(ADMIN_ID, "❌ Нельзя забанить себя")
        return
    
    # Баним
    storage.banned_users.add(user_id_to_ban)
    
    # Завершаем активный чат, если есть
    if user_id_to_ban in storage.active_chats:
        end_chat(user_id_to_ban, ADMIN_ID, "banned")
    
    bot.send_message(ADMIN_ID, 
        f"🚫 *Пользователь забанен*\n\n"
        f"ID: `{user_id_to_ban}`\n"
        f"Username: {storage.user_profiles.get(user_id_to_ban, {}).get('username', 'Неизвестно')}\n\n"
        f"Все активные сессии завершены.",
        parse_mode='Markdown'
    )
    
    storage.stats['banned_users'] = len(storage.banned_users)
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
    user_id_to_unban = None
    
    if target.startswith('@'):
        username = target[1:]
        for uid, profile in storage.user_profiles.items():
            if profile['username'].lower() == username.lower():
                user_id_to_unban = uid
                break
    elif target.isdigit():
        user_id_to_unban = int(target)
    
    if not user_id_to_unban:
        bot.send_message(ADMIN_ID, f"❌ Пользователь не найден")
        return
    
    if user_id_to_unban in storage.banned_users:
        storage.banned_users.remove(user_id_to_unban)
        bot.send_message(ADMIN_ID, f"✅ Пользователь разбанен: {target}")
        storage.stats['banned_users'] = len(storage.banned_users)
        storage.save_data()
    else:
        bot.send_message(ADMIN_ID, f"ℹ️ Пользователь не был забанен")

# ===== ПОЛНАЯ КОМАНДА ПОМОЩИ =====
@bot.message_handler(commands=['help', 'helper', 'помощь'])
def help_command(message):
    """Расширенная помощь"""
    if is_admin(message.from_user.id):
        # Помощь для админа
        help_text = (
            "👑 *ПОМОЩЬ ДЛЯ АДМИНИСТРАТОРА*\n\n"
            
            "📋 *Основные команды:*\n"
            "• /admin - Панель управления\n"
            "• /tasks или кнопка '📋 Задачи' - Просмотр всех вопросов\n"
            "• /stats - Подробная статистика\n"
            "• /helper - Эта справка\n\n"
            
            "💬 *Управление чатами:*\n"
            "• Просто пишите сообщения - они отправятся в активный чат\n"
            "• /stop или /stopchat - Завершить текущий чат\n"
            "• /clear - Очистить историю текущего чата\n"
            "• /ban @username - Забанить пользователя\n"
            "• /unban @username - Разбанить\n\n"
            
            "🛠 *Функции панели:*\n"
            "• '📋 Задачи' - Все вопросы без ответов\n"
            "• '💬 Активные чаты' - Управление переписками\n"
            "• '📊 Статистика' - Детальная аналитика\n"
            "• '🚫 Управление банами' - Список и управление\n"
            "• '👥 Пользователи' - Информация о пользователях\n"
            "• '⚙️ Настройки' - Конфигурация бота\n\n"
            
            "📎 *Особенности:*\n"
            "• Поддержка фото, документов, голосовых\n"
            "• Автосохранение истории\n"
            "• Таймаут чата 5 минут\n"
            "• Автоматические уведомления\n\n"
            
            "🆘 *Экстренные команды:*\n"
            "/emergency - Экстренное оповещение всех пользователей"
        )
    else:
        # Помощь для пользователей
        help_text = (
            "ℹ️ *ПОМОЩЬ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ*\n\n"
            
            "👋 *Как пользоваться ботом:*\n"
            "1. Нажмите '📨 Задать вопрос' для письменного обращения\n"
            "2. Выберите '💬 Прямая переписка' для живого диалога\n"
            "3. Администратор ответит в ближайшее время\n\n"
            
            "📎 *Что можно отправлять:*\n"
            "• Текстовые сообщения\n"
            "• Фотографии (с подписями)\n"
            "• Документы (до 20MB)\n"
            "• Голосовые сообщения\n\n"
            
            "⏰ *Время ответа:*\n"
            "• Вопросы: до 24 часов\n"
            "• Переписка: мгновенно при наличии свободного админа\n\n"
            
            "🚫 *Правила:*\n"
            "• Уважительное общение\n"
            "• Запрещен спам\n"
            "• Запрещены оскорбления\n\n"
            
            "📞 *Контакты:*\n"
            "По экстренным вопросам: @UsernameFLX"
        )
    
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

# ===== ЗАПУСК БОТА =====
@bot.message_handler(commands=['emergency'])
def emergency_command(message):
    """Экстренная команда (только для админа)"""
    if not is_admin(message.from_user.id):
        return
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('✅ Подтвердить', callback_data='confirm_emergency'))
    markup.add(types.InlineKeyboardButton('❌ Отмена', callback_data='cancel_emergency'))
    
    bot.send_message(ADMIN_ID,
        "🚨 *ЭКСТРЕННОЕ ОПОВЕЩЕНИЕ*\n\n"
        "Вы собираетесь отправить сообщение ВСЕМ пользователям бота.\n\n"
        "❓ *Вы уверены?*",
        parse_mode='Markdown',
        reply_markup=markup
    )

def show_main_menu(user_id):
    """Показывает главное меню"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📨 Задать вопрос'),
        types.KeyboardButton('💬 Прямая переписка'),
        types.KeyboardButton('ℹ️ Помощь'),
        types.KeyboardButton('📊 Мой профиль')
    )
    bot.send_message(user_id, "Главное меню:", reply_markup=markup)

def notify_admin_about_question(question_id, question_data):
    """Уведомляет админа о новом вопросе"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('✏️ Ответить', callback_data=f'answer_{question_id}'),
        types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_{question_id}'),
        types.InlineKeyboardButton('👁 Просмотреть', callback_data=f'view_{question_id}')
    )
    
    notification = (
        f"📨 *Новый вопрос #{question_id}*\n\n"
        f"👤 Пользователь: {question_data['username']}\n"
        f"🆔 ID: `{question_data['user_id']}`\n"
        f"⏰ Время: {datetime.fromisoformat(question_data['timestamp']).strftime('%H:%M:%S')}\n"
    )
    
    if question_data['has_media']:
        notification += f"📎 Тип: {question_data['media_info']}\n"
    
    notification += f"\n💬 Вопрос: {question_data['text'][:300]}..."
    
    bot.send_message(ADMIN_ID, notification, parse_mode='Markdown', reply_markup=markup)

# ===== ЗАПУСК СИСТЕМЫ =====
if __name__ == '__main__':
    logger.info("=" * 50)
    logger.info("🚀 ЗАПУСК СИСТЕМЫ АДМИНИСТРИРОВАНИЯ БОТА")
    logger.info(f"Администратор: {ADMIN_ID}")
    logger.info(f"Загружено пользователей: {len(storage.user_profiles)}")
    logger.info(f"Вопросов в базе: {len(storage.questions)}")
    logger.info(f"Забанено пользователей: {len(storage.banned_users)}")
    logger.info("=" * 50)
    
    # Запускаем бота
    try:
        bot.polling(none_stop=True, interval=0, timeout=60)
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        # Пытаемся сохранить данные перед выходом
        storage.save_data()
