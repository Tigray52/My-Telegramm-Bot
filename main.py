import telebot
import os
import json
import re
import time
import sqlite3
import threading
import urllib.parse
from datetime import datetime, timedelta
from telebot import types
from collections import defaultdict

bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))
MAIN_ADMIN_ID = 6337781618  # Оригинальный админ, который указан в скрипте

# ===== БАЗА ДАННЫХ =====
class Database:
    def __init__(self, db_name='bot_database.db'):
        self.db_name = db_name
        self.lock = threading.Lock()
        self.init_database()
        self.load_admins_from_db()
    
    def load_admins_from_db(self):
        """Загружает список администраторов из БД"""
        pass  # Будет загружено через storage
    
    def init_database(self):
        """Инициализация таблиц базы данных"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            # Пользователи
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    questions_sent INTEGER DEFAULT 0,
                    warnings INTEGER DEFAULT 0,
                    is_banned BOOLEAN DEFAULT FALSE,
                    ban_reason TEXT,
                    ban_until TIMESTAMP,
                    is_muted_questions BOOLEAN DEFAULT FALSE,
                    mute_questions_reason TEXT,
                    mute_questions_until TIMESTAMP,
                    is_muted_chat BOOLEAN DEFAULT FALSE,
                    mute_chat_reason TEXT,
                    mute_chat_until TIMESTAMP
                )
            ''')
            
            # Вопросы
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    telegram_id INTEGER,
                    question_text TEXT NOT NULL,
                    masked_text TEXT,
                    url_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    admin_response TEXT,
                    admin_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    answered_at TIMESTAMP,
                    answer_count INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            # Активные чаты
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS active_chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER UNIQUE,
                    telegram_id INTEGER UNIQUE,
                    admin_id INTEGER,
                    user_name TEXT,
                    admin_name TEXT,
                    allow_links BOOLEAN DEFAULT TRUE,
                    message_limit INTEGER DEFAULT 350,
                    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            # Сообщения в чатах
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    telegram_id INTEGER,
                    is_admin BOOLEAN,
                    message_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (chat_id) REFERENCES active_chats(id)
                )
            ''')
            
            # Нарушения (ссылки)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS violations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    telegram_id INTEGER,
                    message_text TEXT,
                    urls_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            # Cooldowns
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cooldowns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action_type TEXT,
                    last_action TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, action_type),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            # Администраторы
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    added_by INTEGER,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_main_admin BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (added_by) REFERENCES admins(telegram_id)
                )
            ''')
            
            # Автоприветственные сообщения
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS autohello_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER NOT NULL,
                    message_num INTEGER NOT NULL,
                    message_text TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(admin_id, message_num),
                    FOREIGN KEY (admin_id) REFERENCES admins(telegram_id)
                )
            ''')
            
            # Индексы для производительности
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_is_banned ON users(is_banned)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_is_muted_questions ON users(is_muted_questions)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_is_muted_chat ON users(is_muted_chat)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_questions_status ON questions(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_questions_user_id ON questions(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_active_chats_telegram_id ON active_chats(telegram_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_active_chats_admin_id ON active_chats(admin_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_admins_telegram_id ON admins(telegram_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_admins_is_main_admin ON admins(is_main_admin)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_autohello_admin_id ON autohello_messages(admin_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_autohello_admin_num ON autohello_messages(admin_id, message_num)')
            
            # Добавляем основного админа если его нет
            cursor.execute('SELECT * FROM admins WHERE telegram_id = ?', (MAIN_ADMIN_ID,))
            if not cursor.fetchone():
                cursor.execute('''
                    INSERT INTO admins (telegram_id, username, first_name, added_by, added_at, is_main_admin)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (MAIN_ADMIN_ID, 'main_admin', 'Main Admin', MAIN_ADMIN_ID, datetime.now(), True))
            
            conn.commit()
            conn.close()
    
    # ===== АДМИНИСТРАТОРЫ =====
    def add_admin(self, telegram_id, username, first_name, added_by):
        """Добавляет администратора"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            try:
                cursor.execute('''
                    INSERT INTO admins (telegram_id, username, first_name, added_by, added_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (telegram_id, username, first_name, added_by, datetime.now()))
                
                conn.commit()
                success = True
            except sqlite3.IntegrityError:
                success = False
            
            conn.close()
            return success
    
    def remove_admin(self, telegram_id):
        """Удаляет администратора"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            # Проверяем, не главный ли это админ
            cursor.execute('SELECT is_main_admin FROM admins WHERE telegram_id = ?', (telegram_id,))
            admin = cursor.fetchone()
            
            if admin and admin[0]:  # Это главный админ
                conn.close()
                return False, "Нельзя удалить главного администратора"
            
            cursor.execute('DELETE FROM admins WHERE telegram_id = ?', (telegram_id,))
            conn.commit()
            
            deleted = cursor.rowcount > 0
            conn.close()
            
            if deleted:
                return True, "Успешно удален"
            else:
                return False, "Администратор не найден"
    
    def get_all_admins(self):
        """Получает всех администраторов"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM admins ORDER BY is_main_admin DESC, added_at DESC')
            admins = cursor.fetchall()
            conn.close()
            
            return [dict(admin) for admin in admins]
    
    def is_admin(self, telegram_id):
        """Проверяет, является ли пользователь администратором"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            cursor.execute('SELECT 1 FROM admins WHERE telegram_id = ?', (telegram_id,))
            is_admin = cursor.fetchone() is not None
            conn.close()
            
            return is_admin
    
    def get_admin_info(self, telegram_id):
        """Получает информацию об администраторе"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM admins WHERE telegram_id = ?', (telegram_id,))
            admin = cursor.fetchone()
            conn.close()
            
            return dict(admin) if admin else None
    
    def get_main_admin(self):
        """Получает главного администратора"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM admins WHERE is_main_admin = TRUE')
            admin = cursor.fetchone()
            conn.close()
            
            return dict(admin) if admin else None
    
    # ===== АВТОПРИВЕТСТВЕННЫЕ СООБЩЕНИЯ =====
    def set_autohello_message(self, admin_id, message_num, message_text):
        """Устанавливает автоприветственное сообщение"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            # Проверяем валидность номера
            if not 1 <= message_num <= 10:
                conn.close()
                return False, "Номер сообщения должен быть от 1 до 10"
            
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO autohello_messages 
                    (admin_id, message_num, message_text, is_active, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (admin_id, message_num, message_text, True, datetime.now()))
                
                conn.commit()
                success = True
                message = f"Сообщение #{message_num} сохранено"
            except Exception as e:
                success = False
                message = f"Ошибка: {str(e)}"
            
            conn.close()
            return success, message
    
    def disable_autohello_messages(self, admin_id, message_nums):
        """Отключает автоприветственные сообщения"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            try:
                # Создаем список чисел
                nums = []
                for num_str in message_nums:
                    try:
                        num = int(num_str)
                        if 1 <= num <= 10:
                            nums.append(num)
                    except:
                        pass
                
                if not nums:
                    conn.close()
                    return False, "Нет валидных номеров сообщений"
                
                # Отключаем сообщения
                placeholders = ','.join(['?'] * len(nums))
                cursor.execute(f'''
                    UPDATE autohello_messages 
                    SET is_active = FALSE, updated_at = ?
                    WHERE admin_id = ? AND message_num IN ({placeholders})
                ''', [datetime.now(), admin_id] + nums)
                
                conn.commit()
                success = True
                message = f"Отключено сообщений: {len(nums)}"
            except Exception as e:
                success = False
                message = f"Ошибка: {str(e)}"
            
            conn.close()
            return success, message
    
    def clear_autohello_messages(self, admin_id):
        """Очищает все автоприветственные сообщения"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            try:
                cursor.execute('DELETE FROM autohello_messages WHERE admin_id = ?', (admin_id,))
                conn.commit()
                success = True
                message = "Все автоприветственные сообщения очищены"
            except Exception as e:
                success = False
                message = f"Ошибка: {str(e)}"
            
            conn.close()
            return success, message
    
    def get_autohello_messages(self, admin_id):
        """Получает все активные автоприветственные сообщения"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT message_num, message_text 
                FROM autohello_messages 
                WHERE admin_id = ? AND is_active = TRUE
                ORDER BY message_num
            ''', (admin_id,))
            
            messages = cursor.fetchall()
            conn.close()
            
            result = {}
            for msg in messages:
                result[msg['message_num']] = msg['message_text']
            return result
    
    def get_all_autohello_messages(self, admin_id):
        """Получает все автоприветственные сообщения (включая неактивные)"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT message_num, message_text, is_active
                FROM autohello_messages 
                WHERE admin_id = ?
                ORDER BY message_num
            ''', (admin_id,))
            
            messages = cursor.fetchall()
            conn.close()
            
            result = {}
            for msg in messages:
                result[msg['message_num']] = {
                    'text': msg['message_text'],
                    'active': bool(msg['is_active'])
                }
            return result
    
    # ===== ПОЛЬЗОВАТЕЛИ =====
    def get_or_create_user(self, telegram_id, username, first_name):
        """Получает или создает пользователя"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
            user = cursor.fetchone()
            
            if not user:
                cursor.execute('''
                    INSERT INTO users (telegram_id, username, first_name, joined_date, last_seen)
                    VALUES (?, ?, ?, ?, ?)
                ''', (telegram_id, username, first_name, datetime.now(), datetime.now()))
                
                user_id = cursor.lastrowid
                cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
                user = cursor.fetchone()
            else:
                cursor.execute('UPDATE users SET last_seen = ? WHERE id = ?', 
                             (datetime.now(), user['id']))
            
            conn.commit()
            conn.close()
            
            return dict(user) if user else None
    
    def update_user_ban(self, user_id, is_banned, reason=None, ban_until=None):
        """Обновляет статус бана пользователя"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE users 
                SET is_banned = ?, ban_reason = ?, ban_until = ?
                WHERE id = ?
            ''', (is_banned, reason, ban_until, user_id))
            
            conn.commit()
            conn.close()
    
    def update_user_mute_questions(self, user_id, is_muted, reason=None, mute_until=None):
        """Обновляет статус мута в вопросах"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE users 
                SET is_muted_questions = ?, mute_questions_reason = ?, mute_questions_until = ?
                WHERE id = ?
            ''', (is_muted, reason, mute_until, user_id))
            
            conn.commit()
            conn.close()
    
    def update_user_mute_chat(self, user_id, is_muted, reason=None, mute_until=None):
        """Обновляет статус мута в чате"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE users 
                SET is_muted_chat = ?, mute_chat_reason = ?, mute_chat_until = ?
                WHERE id = ?
            ''', (is_muted, reason, mute_until, user_id))
            
            conn.commit()
            conn.close()
    
    def get_user_by_telegram_id(self, telegram_id):
        """Получает пользователя по Telegram ID"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
            user = cursor.fetchone()
            conn.close()
            
            return dict(user) if user else None
    
    def get_all_users(self, limit=None):
        """Получает всех пользователей с пагинацией"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = 'SELECT * FROM users ORDER BY joined_date DESC'
            if limit:
                query += f' LIMIT {limit}'
            
            cursor.execute(query)
            users = cursor.fetchall()
            conn.close()
            
            return [dict(user) for user in users]
    
    def get_banned_users(self):
        """Получает всех забаненных пользователей"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM users WHERE is_banned = TRUE ORDER BY ban_until DESC')
            users = cursor.fetchall()
            conn.close()
            
            return [dict(user) for user in users]
    
    def get_muted_questions_users(self):
        """Получает всех заглушенных в вопросах пользователей"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM users WHERE is_muted_questions = TRUE ORDER BY mute_questions_until DESC')
            users = cursor.fetchall()
            conn.close()
            
            return [dict(user) for user in users]
    
    def get_muted_chat_users(self):
        """Получает всех заглушенных в чате пользователей"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM users WHERE is_muted_chat = TRUE ORDER BY mute_chat_until DESC')
            users = cursor.fetchall()
            conn.close()
            
            return [dict(user) for user in users]
    
    def get_all_muted_users(self):
        """Получает всех заглушенных пользователей (и в чате, и в вопросах)"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM users 
                WHERE is_muted_questions = TRUE OR is_muted_chat = TRUE 
                ORDER BY mute_questions_until DESC, mute_chat_until DESC
            ''')
            users = cursor.fetchall()
            conn.close()
            
            return [dict(user) for user in users]
    
    def get_user_statistics(self, telegram_id):
        """Получает статистику пользователя"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT 
                    u.*,
                    COUNT(DISTINCT q.id) as total_questions,
                    COUNT(DISTINCT CASE WHEN q.status = "pending" THEN q.id END) as pending_questions,
                    COUNT(DISTINCT CASE WHEN q.status = "answered" THEN q.id END) as answered_questions,
                    COUNT(DISTINCT CASE WHEN DATE(q.created_at) = DATE("now") THEN q.id END) as questions_today
                FROM users u
                LEFT JOIN questions q ON u.id = q.user_id
                WHERE u.telegram_id = ?
                GROUP BY u.id
            ''', (telegram_id,))
            
            user_data = cursor.fetchone()
            
            if not user_data:
                conn.close()
                return None
            
            result = dict(user_data)
            
            cursor.execute('SELECT * FROM active_chats WHERE telegram_id = ?', (telegram_id,))
            active_chat = cursor.fetchone()
            result['in_chat'] = bool(active_chat)
            if active_chat:
                result['chat_start_time'] = dict(active_chat)['start_time']
            
            conn.close()
            return result
    
    def increment_user_questions(self, user_id):
        """Увеличивает счетчик вопросов пользователя"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE users 
                SET questions_sent = questions_sent + 1 
                WHERE id = ?
            ''', (user_id,))
            
            conn.commit()
            conn.close()
    
    # ===== ВОПРОСЫ =====
    def add_question(self, telegram_id, question_text, masked_text, url_count):
        """Добавляет новый вопрос"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            cursor.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            user_row = cursor.fetchone()
            
            if not user_row:
                conn.close()
                return None
            
            user_id = user_row[0]
            
            cursor.execute('''
                INSERT INTO questions 
                (user_id, telegram_id, question_text, masked_text, url_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, telegram_id, question_text, masked_text, url_count, datetime.now()))
            
            question_id = cursor.lastrowid
            
            cursor.execute('''
                UPDATE users 
                SET questions_sent = questions_sent + 1 
                WHERE id = ?
            ''', (user_id,))
            
            conn.commit()
            conn.close()
            
            return question_id
    
    def get_question(self, question_id):
        """Получает вопрос по ID"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT q.*, u.username, u.telegram_id as user_telegram_id
                FROM questions q
                JOIN users u ON q.user_id = u.id
                WHERE q.id = ?
            ''', (question_id,))
            
            question = cursor.fetchone()
            conn.close()
            
            if question:
                question_dict = dict(question)
                if question_dict['created_at']:
                    created = datetime.fromisoformat(question_dict['created_at']) 
                    question_dict['date'] = created.strftime('%d.%m.%Y')
                    question_dict['time'] = created.strftime('%H:%M')
                return question_dict
            
            return None
    
    def get_pending_questions(self):
        """Получает все ожидающие вопросы (только те, на которые еще не ответили)"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT q.*, u.username, u.telegram_id as user_telegram_id
                FROM questions q
                JOIN users u ON q.user_id = u.id
                WHERE q.status = 'pending' AND q.answer_count = 0
                ORDER BY q.created_at ASC
            ''')
            
            questions = cursor.fetchall()
            conn.close()
            
            result = []
            for question in questions:
                q_dict = dict(question)
                if q_dict['created_at']:
                    created = datetime.fromisoformat(q_dict['created_at'])
                    q_dict['date'] = created.strftime('%d.%m.%Y')
                    q_dict['time'] = created.strftime('%H:%M')
                result.append(q_dict)
            
            return result
    
    def update_question_status(self, question_id, status, admin_response=None, admin_name=None):
        """Обновляет статус вопроса"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            update_data = {'status': status}
            if admin_response:
                update_data['admin_response'] = admin_response
            if admin_name:
                update_data['admin_name'] = admin_name
            if status == 'answered':
                update_data['answered_at'] = datetime.now()
            
            set_clause = ', '.join([f"{k} = ?" for k in update_data.keys()])
            values = list(update_data.values()) + [question_id]
            
            cursor.execute(f'''
                UPDATE questions 
                SET {set_clause}
                WHERE id = ?
            ''', values)
            
            conn.commit()
            conn.close()
    
    def increment_answer_count(self, question_id):
        """Увеличивает счетчик ответов на вопрос"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE questions 
                SET answer_count = answer_count + 1 
                WHERE id = ?
            ''', (question_id,))
            
            conn.commit()
            conn.close()
    
    def cleanup_answered_questions(self):
        """Очищает вопросы, на которые уже ответили"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM questions 
                WHERE status = 'answered' AND answer_count > 0
            ''')
            
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            
            return deleted_count
    
    def cleanup_old_questions(self):
        """Очищает вопросы старше 24 часов"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT q.id, u.telegram_id, u.username
                FROM questions q
                JOIN users u ON q.user_id = u.id
                WHERE q.status = 'pending'
                AND q.created_at < datetime('now', '-24 hours')
            ''')
            
            old_questions = cursor.fetchall()
            
            cursor.execute('''
                UPDATE questions 
                SET status = 'expired'
                WHERE status = 'pending'
                AND created_at < datetime('now', '-24 hours')
            ''')
            
            conn.commit()
            conn.close()
            
            return old_questions
    
    # ===== АКТИВНЫЕ ЧАТЫ =====
    def start_chat(self, telegram_id, admin_id, user_name, admin_name, allow_links, message_limit):
        """Начинает новый чат"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            cursor.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            user_row = cursor.fetchone()
            
            if not user_row:
                conn.close()
                return None
            
            user_id = user_row[0]
            
            cursor.execute('DELETE FROM active_chats WHERE user_id = ?', (user_id,))
            
            cursor.execute('''
                INSERT INTO active_chats 
                (user_id, telegram_id, admin_id, user_name, admin_name, 
                 allow_links, message_limit, start_time, last_activity)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, telegram_id, admin_id, user_name, admin_name, 
                  allow_links, message_limit, datetime.now(), datetime.now()))
            
            chat_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            return chat_id
    
    def end_chat(self, telegram_id):
        """Завершает чат"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM active_chats WHERE telegram_id = ?', (telegram_id,))
            
            conn.commit()
            conn.close()
    
    def get_active_chat(self, telegram_id):
        """Получает активный чат пользователя"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM active_chats WHERE telegram_id = ?', (telegram_id,))
            chat = cursor.fetchone()
            conn.close()
            
            return dict(chat) if chat else None
    
    def get_all_active_chats(self):
        """Получает все активные чаты"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM active_chats')
            chats = cursor.fetchall()
            conn.close()
            
            return [dict(chat) for chat in chats]
    
    def update_chat_activity(self, telegram_id):
        """Обновляет время последней активности в чате"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE active_chats 
                SET last_activity = ?
                WHERE telegram_id = ?
            ''', (datetime.now(), telegram_id))
            
            conn.commit()
            conn.close()
    
    # ===== COOLDOWNS =====
    def check_cooldown(self, telegram_id, action_type, cooldown_time):
        """Проверяет cooldown для действия"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT last_action FROM cooldowns 
                WHERE user_id = (SELECT id FROM users WHERE telegram_id = ?)
                AND action_type = ?
            ''', (telegram_id, action_type))
            
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                return True, 0
            
            last_action = datetime.fromisoformat(row[0])
            elapsed = (datetime.now() - last_action).total_seconds()
            
            if elapsed >= cooldown_time:
                return True, 0
            else:
                remaining = int(cooldown_time - elapsed)
                return False, remaining
    
    def set_cooldown(self, telegram_id, action_type):
        """Устанавливает cooldown для действия"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            cursor.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            user_row = cursor.fetchone()
            
            if not user_row:
                conn.close()
                return
            
            user_id = user_row[0]
            
            cursor.execute('''
                INSERT OR REPLACE INTO cooldowns (user_id, action_type, last_action)
                VALUES (?, ?, ?)
            ''', (user_id, action_type, datetime.now()))
            
            conn.commit()
            conn.close()
    
    # ===== СТАТИСТИКА =====
    def get_statistics(self):
        """Получает статистику"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            stats = {}
            
            cursor.execute('SELECT COUNT(*) FROM users')
            stats['total_users'] = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(*) FROM users 
                WHERE DATE(last_seen) = DATE('now')
            ''')
            stats['active_today'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM questions WHERE status = "pending" AND answer_count = 0')
            stats['pending_questions'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM active_chats')
            stats['active_chats'] = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(*) FROM questions 
                WHERE DATE(created_at) = DATE('now')
            ''')
            stats['questions_today'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_banned = TRUE')
            stats['bans'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_muted_questions = TRUE')
            stats['mutes_questions'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_muted_chat = TRUE')
            stats['mutes_chat'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM admins')
            stats['admins'] = cursor.fetchone()[0]
            
            conn.close()
            return stats

# ===== ХРАНИЛИЩЕ =====
class Storage:
    def __init__(self):
        self.db = Database()
        self.cache = {
            'questions': {},
            'active_chats': {},
            'admins': set(),
            'admin_info': {},
            'autohello_messages': {}
        }
        self.load_admins()
    
    def load_admins(self):
        """Загружает администраторов в кэш"""
        admins = self.db.get_all_admins()
        for admin in admins:
            admin_id = admin['telegram_id']
            self.cache['admins'].add(admin_id)
            self.cache['admin_info'][admin_id] = admin
            
            # Загружаем автоприветственные сообщения
            self.load_autohello_messages(admin_id)
    
    def load_autohello_messages(self, admin_id):
        """Загружает автоприветственные сообщения для админа"""
        messages = self.db.get_autohello_messages(admin_id)
        if admin_id not in self.cache['autohello_messages']:
            self.cache['autohello_messages'][admin_id] = {}
        self.cache['autohello_messages'][admin_id] = messages
    
    # ===== АДМИНИСТРАТОРЫ =====
    def add_admin(self, telegram_id, username, first_name, added_by):
        success = self.db.add_admin(telegram_id, username, first_name, added_by)
        if success:
            self.cache['admins'].add(telegram_id)
            # Обновляем информацию об админе
            admin_info = self.db.get_admin_info(telegram_id)
            if admin_info:
                self.cache['admin_info'][telegram_id] = admin_info
        return success
    
    def remove_admin(self, telegram_id):
        if telegram_id == MAIN_ADMIN_ID:
            return False, "Нельзя удалить главного администратора"
        
        deleted, result_message = self.db.remove_admin(telegram_id)
        if deleted:
            self.cache['admins'].discard(telegram_id)
            if telegram_id in self.cache['admin_info']:
                del self.cache['admin_info'][telegram_id]
            if telegram_id in self.cache['autohello_messages']:
                del self.cache['autohello_messages'][telegram_id]
        return deleted, result_message
    
    def get_all_admins(self):
        return self.db.get_all_admins()
    
    def is_admin(self, telegram_id):
        return telegram_id in self.cache['admins']
    
    def get_admin_info(self, telegram_id):
        if telegram_id in self.cache['admin_info']:
            return self.cache['admin_info'][telegram_id]
        return self.db.get_admin_info(telegram_id)
    
    def get_main_admin(self):
        return self.db.get_main_admin()
    
    # ===== АВТОПРИВЕТСТВЕННЫЕ СООБЩЕНИЯ =====
    def set_autohello_message(self, admin_id, message_num, message_text):
        success, message = self.db.set_autohello_message(admin_id, message_num, message_text)
        if success:
            self.load_autohello_messages(admin_id)
        return success, message
    
    def disable_autohello_messages(self, admin_id, message_nums):
        success, message = self.db.disable_autohello_messages(admin_id, message_nums)
        if success:
            self.load_autohello_messages(admin_id)
        return success, message
    
    def clear_autohello_messages(self, admin_id):
        success, message = self.db.clear_autohello_messages(admin_id)
        if success:
            self.load_autohello_messages(admin_id)
        return success, message
    
    def get_autohello_messages(self, admin_id):
        if admin_id in self.cache['autohello_messages']:
            return self.cache['autohello_messages'][admin_id]
        return {}
    
    def get_all_autohello_messages(self, admin_id):
        return self.db.get_all_autohello_messages(admin_id)
    
    def send_autohello_messages(self, user_id, admin_id, admin_name):
        """Отправляет автоприветственные сообщения"""
        messages = self.get_autohello_messages(admin_id)
        if not messages:
            return
        
        sorted_messages = sorted(messages.items())  # Сортируем по номеру
        for msg_num, msg_text in sorted_messages:
            try:
                # Экранируем имя админа
                escaped_admin_name = escape_markdown(admin_name)
                
                bot.send_message(
                    user_id,
                    f"👨‍💼 *{escaped_admin_name} (Администратор):*\n{msg_text}",
                    parse_mode='Markdown'
                )
                time.sleep(0.3)  # Небольшая задержка между сообщениями
            except Exception as e:
                print(f"Ошибка отправки автоприветствия #{msg_num}: {e}")
    
    # ===== ПОЛЬЗОВАТЕЛЕЙ =====
    def get_or_create_user(self, telegram_id, username, first_name):
        return self.db.get_or_create_user(telegram_id, username, first_name)
    
    def get_user(self, telegram_id):
        return self.db.get_user_by_telegram_id(telegram_id)
    
    def get_all_users(self, limit=None):
        return self.db.get_all_users(limit)
    
    def get_banned_users(self):
        return self.db.get_banned_users()
    
    def get_muted_questions_users(self):
        return self.db.get_muted_questions_users()
    
    def get_muted_chat_users(self):
        return self.db.get_muted_chat_users()
    
    def get_all_muted_users(self):
        return self.db.get_all_muted_users()
    
    def get_user_statistics(self, telegram_id):
        return self.db.get_user_statistics(telegram_id)
    
    def is_banned(self, telegram_id):
        user = self.get_user(telegram_id)
        if not user:
            return False
        
        if not user['is_banned']:
            return False
        
        if user['ban_until']:
            ban_until = datetime.fromisoformat(user['ban_until'])
            if datetime.now() > ban_until:
                self.db.update_user_ban(user['id'], False)
                return False
        
        return True
    
    def ban_user(self, telegram_id, duration_seconds=0, reason="Нарушение правил", banned_by=None):
        # Нельзя забанить администратора
        if self.is_admin(telegram_id):
            return False, "Нельзя забанить администратора"
        
        user = self.get_user(telegram_id)
        if not user:
            return False, "Пользователь не найден"
        
        ban_until = None
        if duration_seconds > 0:
            ban_until = datetime.fromtimestamp(time.time() + duration_seconds)
        
        self.db.update_user_ban(user['id'], True, reason, ban_until)
        
        self.db.end_chat(telegram_id)
        
        # Уведомляем всех админов, кроме того, кто забанил
        if banned_by:
            self.notify_admins_about_ban(telegram_id, banned_by, duration_seconds, reason)
        
        return True, "Пользователь забанен"
    
    def notify_admins_about_ban(self, banned_user_id, banned_by_admin_id, duration_seconds, reason):
        """Уведомляет всех админов о бане (кроме того, кто забанил)"""
        admins = self.get_all_admins()
        banned_user = self.get_user(banned_user_id)
        banning_admin = self.get_admin_info(banned_by_admin_id)
        
        if not banned_user or not banning_admin:
            return
        
        banned_username = banned_user.get('username') or banned_user.get('first_name', f'ID: {banned_user_id}')
        banning_admin_name = banning_admin.get('username') or banning_admin.get('first_name', f'ID: {banned_by_admin_id}')
        
        duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
        
        notification = (
            f"🚫 *Администратор забанил пользователя*\n\n"
            f"👤 *Пользователь:* {banned_username} (`{banned_user_id}`)\n"
            f"👑 *Администратор:* {banning_admin_name} (`{banned_by_admin_id}`)\n"
            f"⏰ *Срок:* {duration_text}\n"
            f"📝 *Причина:* {reason}"
        )
        
        for admin in admins:
            admin_id = admin['telegram_id']
            if admin_id != banned_by_admin_id:  # Не отправляем тому, кто забанил
                try:
                    bot.send_message(admin_id, notification, parse_mode='Markdown')
                except:
                    pass
    
    def unban_user(self, telegram_id, reason="Причина не указана", unbanned_by=None):
        user = self.get_user(telegram_id)
        if not user:
            return False, "Пользователь не найден"
        
        self.db.update_user_ban(user['id'], False)
        
        # Уведомляем всех админов, кроме того, кто разбанил
        if unbanned_by:
            self.notify_admins_about_unban(telegram_id, unbanned_by, reason)
        
        return True, "Пользователь разбанен"
    
    def notify_admins_about_unban(self, unbanned_user_id, unbanned_by_admin_id, reason):
        """Уведомляет всех админов о разбане (кроме того, кто разбанил)"""
        admins = self.get_all_admins()
        unbanned_user = self.get_user(unbanned_user_id)
        unbanning_admin = self.get_admin_info(unbanned_by_admin_id)
        
        if not unbanned_user or not unbanning_admin:
            return
        
        unbanned_username = unbanned_user.get('username') or unbanned_user.get('first_name', f'ID: {unbanned_user_id}')
        unbanning_admin_name = unbanning_admin.get('username') or unbanning_admin.get('first_name', f'ID: {unbanned_by_admin_id}')
        
        notification = (
            f"✅ *Администратор разбанил пользователя*\n\n"
            f"👤 *Пользователь:* {unbanned_username} (`{unbanned_user_id}`)\n"
            f"👑 *Администратор:* {unbanning_admin_name} (`{unbanned_by_admin_id}`)\n"
            f"📝 *Причина:* {reason}"
        )
        
        for admin in admins:
            admin_id = admin['telegram_id']
            if admin_id != unbanned_by_admin_id:  # Не отправляем тому, кто разбанил
                try:
                    bot.send_message(admin_id, notification, parse_mode='Markdown')
                except:
                    pass
    
    def is_muted_questions(self, telegram_id):
        user = self.get_user(telegram_id)
        if not user:
            return False
        
        if not user['is_muted_questions']:
            return False
        
        if user['mute_questions_until']:
            mute_until = datetime.fromisoformat(user['mute_questions_until'])
            if datetime.now() > mute_until:
                self.db.update_user_mute_questions(user['id'], False)
                return False
        
        return True
    
    def is_muted_chat(self, telegram_id):
        user = self.get_user(telegram_id)
        if not user:
            return False
        
        if not user['is_muted_chat']:
            return False
        
        if user['mute_chat_until']:
            mute_until = datetime.fromisoformat(user['mute_chat_until'])
            if datetime.now() > mute_until:
                self.db.update_user_mute_chat(user['id'], False)
                return False
        
        return True
    
    def mute_user_questions(self, telegram_id, duration_seconds=0, reason="Нарушение правил", muted_by=None):
        # Нельзя замутить администратора
        if self.is_admin(telegram_id):
            return False, "Нельзя замутить администратора"
        
        user = self.get_user(telegram_id)
        if not user:
            return False, "Пользователь не найден"
        
        mute_until = None
        if duration_seconds > 0:
            mute_until = datetime.fromtimestamp(time.time() + duration_seconds)
        
        self.db.update_user_mute_questions(user['id'], True, reason, mute_until)
        
        # Уведомляем всех админов о муте в вопросах
        if muted_by:
            self.notify_admins_about_mute_questions(telegram_id, muted_by, duration_seconds, reason)
        
        return True, "Пользователь заглушен в вопросах"
    
    def notify_admins_about_mute_questions(self, muted_user_id, muted_by_admin_id, duration_seconds, reason):
        """Уведомляет всех админов о муте в вопросах"""
        admins = self.get_all_admins()
        muted_user = self.get_user(muted_user_id)
        muting_admin = self.get_admin_info(muted_by_admin_id)
        
        if not muted_user or not muting_admin:
            return
        
        muted_username = muted_user.get('username') or muted_user.get('first_name', f'ID: {muted_user_id}')
        muting_admin_name = muting_admin.get('username') or muting_admin.get('first_name', f'ID: {muted_by_admin_id}')
        
        duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
        
        notification = (
            f"🔇 *Администратор заглушил пользователя в вопросах*\n\n"
            f"👤 *Пользователь:* {muted_username} (`{muted_user_id}`)\n"
            f"👑 *Администратор:* {muting_admin_name} (`{muted_by_admin_id}`)\n"
            f"⏰ *Срок:* {duration_text}\n"
            f"📝 *Причина:* {reason}"
        )
        
        for admin in admins:
            admin_id = admin['telegram_id']
            if admin_id != muted_by_admin_id:  # Не отправляем тому, кто замутил
                try:
                    bot.send_message(admin_id, notification, parse_mode='Markdown')
                except:
                    pass
    
    def unmute_user_questions(self, telegram_id, reason="Причина не указана", unmuted_by=None):
        user = self.get_user(telegram_id)
        if not user:
            return False, "Пользователь не найден"
        
        self.db.update_user_mute_questions(user['id'], False)
        
        # Уведомляем всех админов о снятии мута с вопросов
        if unmuted_by:
            self.notify_admins_about_unmute_questions(telegram_id, unmuted_by, reason)
        
        return True, "Мут в вопросах снят"
    
    def notify_admins_about_unmute_questions(self, unmuted_user_id, unmuted_by_admin_id, reason):
        """Уведомляет всех админов о снятии мута с вопросов"""
        admins = self.get_all_admins()
        unmuted_user = self.get_user(unmuted_user_id)
        unmuting_admin = self.get_admin_info(unmuted_by_admin_id)
        
        if not unmuted_user or not unmuting_admin:
            return
        
        unmuted_username = unmuted_user.get('username') or unmuted_user.get('first_name', f'ID: {unmuted_user_id}')
        unmuting_admin_name = unmuting_admin.get('username') or unmuting_admin.get('first_name', f'ID: {unmuted_by_admin_id}')
        
        notification = (
            f"🔊 *Администратор снял мут с вопросов пользователя*\n\n"
            f"👤 *Пользователь:* {unmuted_username} (`{unmuted_user_id}`)\n"
            f"👑 *Администратор:* {unmuting_admin_name} (`{unmuted_by_admin_id}`)\n"
            f"📝 *Причина:* {reason}"
        )
        
        for admin in admins:
            admin_id = admin['telegram_id']
            if admin_id != unmuted_by_admin_id:  # Не отправляем тому, кто снял мут
                try:
                    bot.send_message(admin_id, notification, parse_mode='Markdown')
                except:
                    pass
    
    def mute_user_chat(self, telegram_id, duration_seconds=0, reason="Нарушение правил", muted_by=None):
        # Нельзя замутить администратора
        if self.is_admin(telegram_id):
            return False, "Нельзя замутить администратора"
        
        user = self.get_user(telegram_id)
        if not user:
            return False, "Пользователь не найден"
        
        mute_until = None
        if duration_seconds > 0:
            mute_until = datetime.fromtimestamp(time.time() + duration_seconds)
        
        self.db.update_user_mute_chat(user['id'], True, reason, mute_until)
        
        self.db.end_chat(telegram_id)
        
        # Уведомляем всех админов о муте в чате
        if muted_by:
            self.notify_admins_about_mute_chat(telegram_id, muted_by, duration_seconds, reason)
        
        return True, "Пользователь заглушен в переписке"
    
    def notify_admins_about_mute_chat(self, muted_user_id, muted_by_admin_id, duration_seconds, reason):
        """Уведомляет всех админов о муте в чате"""
        admins = self.get_all_admins()
        muted_user = self.get_user(muted_user_id)
        muting_admin = self.get_admin_info(muted_by_admin_id)
        
        if not muted_user or not muting_admin:
            return
        
        muted_username = muted_user.get('username') or muted_user.get('first_name', f'ID: {muted_user_id}')
        muting_admin_name = muting_admin.get('username') or muting_admin.get('first_name', f'ID: {muted_by_admin_id}')
        
        duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
        
        notification = (
            f"🔇 *Администратор заглушил пользователя в переписке*\n\n"
            f"👤 *Пользователь:* {muted_username} (`{muted_user_id}`)\n"
            f"👑 *Администратор:* {muting_admin_name} (`{muted_by_admin_id}`)\n"
            f"⏰ *Срок:* {duration_text}\n"
            f"📝 *Причина:* {reason}"
        )
        
        for admin in admins:
            admin_id = admin['telegram_id']
            if admin_id != muted_by_admin_id:  # Не отправляем тому, кто замутил
                try:
                    bot.send_message(admin_id, notification, parse_mode='Markdown')
                except:
                    pass
    
    def unmute_user_chat(self, telegram_id, reason="Причина не указана", unmuted_by=None):
        user = self.get_user(telegram_id)
        if not user:
            return False, "Пользователь не найден"
        
        self.db.update_user_mute_chat(user['id'], False)
        
        # Уведомляем всех админов о снятии мута с чата
        if unmuted_by:
            self.notify_admins_about_unmute_chat(telegram_id, unmuted_by, reason)
        
        return True, "Мут в переписке снят"
    
    def notify_admins_about_unmute_chat(self, unmuted_user_id, unmuted_by_admin_id, reason):
        """Уведомляет всех админов о снятии мута с чата"""
        admins = self.get_all_admins()
        unmuted_user = self.get_user(unmuted_user_id)
        unmuting_admin = self.get_admin_info(unmuted_by_admin_id)
        
        if not unmuted_user or not unmuting_admin:
            return
        
        unmuted_username = unmuted_user.get('username') or unmuted_user.get('first_name', f'ID: {unmuted_user_id}')
        unmuting_admin_name = unmuting_admin.get('username') or unmuting_admin.get('first_name', f'ID: {unmuted_by_admin_id}')
        
        notification = (
            f"🔊 *Администратор снял мут с переписки пользователя*\n\n"
            f"👤 *Пользователь:* {unmuted_username} (`{unmuted_user_id}`)\n"
            f"👑 *Администратор:* {unmuting_admin_name} (`{unmuted_by_admin_id}`)\n"
            f"📝 *Причина:* {reason}"
        )
        
        for admin in admins:
            admin_id = admin['telegram_id']
            if admin_id != unmuted_by_admin_id:  # Не отправляем тому, кто снял мут
                try:
                    bot.send_message(admin_id, notification, parse_mode='Markdown')
                except:
                    pass
    
    # ===== ВОПРОСЫ =====
    def add_question(self, telegram_id, username, question_text, masked_text, url_count):
        question_id = self.db.add_question(telegram_id, question_text, masked_text, url_count)
        
        if question_id:
            self.cache['questions'][question_id] = {
                'id': question_id,
                'user_id': telegram_id,
                'username': username,
                'text': question_text,
                'masked_text': masked_text,
                'url_count': url_count,
                'status': 'pending',
                'time': datetime.now().strftime('%H:%M'),
                'date': datetime.now().strftime('%d.%m.%Y'),
                'created_at': datetime.now().isoformat(),
                'answer_count': 0
            }
        
        return question_id
    
    def get_question(self, question_id):
        if question_id in self.cache['questions']:
            return self.cache['questions'][question_id]
        
        question = self.db.get_question(question_id)
        if question:
            formatted_question = {
                'id': question['id'],
                'user_id': question['user_telegram_id'],
                'username': question['username'],
                'text': question['question_text'],
                'masked_text': question['masked_text'],
                'url_count': question['url_count'],
                'status': question['status'],
                'admin_response': question['admin_response'],
                'admin_name': question['admin_name'],
                'time': question.get('time', ''),
                'date': question.get('date', ''),
                'created_at': question['created_at'],
                'answer_count': question.get('answer_count', 0)
            }
            
            self.cache['questions'][question_id] = formatted_question
            return formatted_question
        
        return None
    
    def get_pending_questions(self):
        questions = self.db.get_pending_questions()
        result = []
        
        for question in questions:
            formatted = {
                'id': question['id'],
                'user_id': question['user_telegram_id'],
                'username': question['username'],
                'text': question['question_text'],
                'masked_text': question['masked_text'],
                'url_count': question['url_count'],
                'status': question['status'],
                'time': question.get('time', ''),
                'date': question.get('date', ''),
                'created_at': question['created_at'],
                'answer_count': question.get('answer_count', 0)
            }
            result.append(formatted)
            
            self.cache['questions'][question['id']] = formatted
        
        return result
    
    def update_question_status(self, question_id, status, admin_response=None, admin_name=None):
        self.db.update_question_status(question_id, status, admin_response, admin_name)
        
        if question_id in self.cache['questions']:
            self.cache['questions'][question_id]['status'] = status
            if admin_response:
                self.cache['questions'][question_id]['admin_response'] = admin_response
            if admin_name:
                self.cache['questions'][question_id]['admin_name'] = admin_name
    
    def increment_answer_count(self, question_id):
        self.db.increment_answer_count(question_id)
        
        if question_id in self.cache['questions']:
            self.cache['questions'][question_id]['answer_count'] = \
                self.cache['questions'][question_id].get('answer_count', 0) + 1
    
    def get_answer_count(self, question_id):
        question = self.get_question(question_id)
        if question:
            return question.get('answer_count', 0)
        return 0
    
    def cleanup_answered_questions(self):
        deleted_count = self.db.cleanup_answered_questions()
        
        # Очищаем кэш от отвеченных вопросов
        to_remove = []
        for qid, question in self.cache['questions'].items():
            if question.get('status') == 'answered' and question.get('answer_count', 0) > 0:
                to_remove.append(qid)
        
        for qid in to_remove:
            del self.cache['questions'][qid]
        
        return deleted_count
    
    # ===== АКТИВНЫЕ ЧАТЫ =====
    def start_chat(self, telegram_id, admin_id, user_name, admin_name, allow_links, message_limit):
        chat_id = self.db.start_chat(telegram_id, admin_id, user_name, admin_name, allow_links, message_limit)
        
        if chat_id:
            self.cache['active_chats'][telegram_id] = {
                'admin_id': admin_id,
                'user_name': user_name,
                'admin_name': admin_name,
                'allow_links': allow_links,
                'message_limit': message_limit,
                'start_time': datetime.now().isoformat()
            }
        
        return chat_id
    
    def end_chat(self, telegram_id):
        self.db.end_chat(telegram_id)
        
        if telegram_id in self.cache['active_chats']:
            del self.cache['active_chats'][telegram_id]
    
    def get_active_chat(self, telegram_id):
        if telegram_id in self.cache['active_chats']:
            return self.cache['active_chats'][telegram_id]
        
        chat = self.db.get_active_chat(telegram_id)
        if chat:
            chat_data = {
                'admin_id': chat['admin_id'],
                'user_name': chat['user_name'],
                'admin_name': chat['admin_name'],
                'allow_links': bool(chat['allow_links']),
                'message_limit': chat['message_limit'],
                'start_time': chat['start_time']
            }
            self.cache['active_chats'][telegram_id] = chat_data
            return chat_data
        
        return None
    
    def get_all_active_chats(self):
        chats = self.db.get_all_active_chats()
        
        for chat in chats:
            telegram_id = chat['telegram_id']
            if telegram_id not in self.cache['active_chats']:
                self.cache['active_chats'][telegram_id] = {
                    'admin_id': chat['admin_id'],
                    'user_name': chat['user_name'],
                    'admin_name': chat['admin_name'],
                    'allow_links': bool(chat['allow_links']),
                    'message_limit': chat['message_limit'],
                    'start_time': chat['start_time']
                }
        
        return list(self.cache['active_chats'].values())
    
    def update_chat_activity(self, telegram_id):
        self.db.update_chat_activity(telegram_id)
    
    # ===== COOLDOWNS =====
    def check_cooldown(self, telegram_id, action_type, cooldown_time):
        return self.db.check_cooldown(telegram_id, action_type, cooldown_time)
    
    def set_cooldown(self, telegram_id, action_type):
        self.db.set_cooldown(telegram_id, action_type)
    
    # ===== СПАМ-ЗАЩИТА =====
    def check_spam(self, telegram_id):
        return False
    
    # ===== СТАТИСТИКА =====
    def get_statistics(self):
        return self.db.get_statistics()

storage = Storage()

# ===== КОНСТАНТЫ =====
CHAT_MESSAGE_LIMIT = 350
QUESTION_LIMIT = 400
QUESTION_COOLDOWN = 30
CHAT_REQUEST_COOLDOWN = 60
MAX_ANSWERS_PER_QUESTION = 2
ANSWER_TIME_LIMIT_HOURS = 24
SPAM_LIMIT_MESSAGES = 10
SPAM_LIMIT_SECONDS = 10

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def escape_markdown_v2(text):
    if not text:
        return text
    
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def escape_markdown(text):
    if not text:
        return text
    
    escape_chars = r'_*[]()~`>#+-=|{}!'
    escaped = re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)
    escaped = re.sub(r'\\\.(?=\s|$)', '.', escaped)
    
    return escaped

def mask_url(url):
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
    if not duration_str:
        return 0
    
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
                elif period_name == 'месец':
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
    while True:
        try:
            users = storage.get_all_users()
            for user in users:
                if user['is_banned'] and user['ban_until']:
                    ban_until = datetime.fromisoformat(user['ban_until'])
                    if datetime.now() > ban_until:
                        storage.db.update_user_ban(user['id'], False)
                        
                        try:
                            bot.send_message(
                                user['telegram_id'],
                                f"✅ *Ваш бан истек!*\n\n"
                                f"Вы снова можете пользоваться ботом.\n"
                                f"Причина бана: {user['ban_reason']}"
                            )
                        except:
                            pass
            
            for user in users:
                if user['is_muted_questions'] and user['mute_questions_until']:
                    mute_until = datetime.fromisoformat(user['mute_questions_until'])
                    if datetime.now() > mute_until:
                        storage.db.update_user_mute_questions(user['id'], False)
                        
                        try:
                            bot.send_message(
                                user['telegram_id'],
                                f"✅ *Ваш мут в вопросах истек!*\n\n"
                                f"Вы снова можете задавать вопросы.\n"
                                f"Причина мута: {user['mute_questions_reason']}"
                            )
                        except:
                            pass
            
            for user in users:
                if user['is_muted_chat'] and user['mute_chat_until']:
                    mute_until = datetime.fromisoformat(user['mute_chat_until'])
                    if datetime.now() > mute_until:
                        storage.db.update_user_mute_chat(user['id'], False)
                        
                        try:
                            bot.send_message(
                                user['telegram_id'],
                                f"✅ *Ваш мут в переписке истек!*\n\n"
                                f"Вы снова можете запрашивать прямую переписку.\n"
                                f"Причина мута: {user['mute_chat_reason']}"
                            )
                        except:
                            pass
            
            time.sleep(60)
        except Exception as e:
            print(f"Ошибка в check_ban_expirations: {e}")
            time.sleep(60)

def cleanup_old_questions():
    while True:
        try:
            old_questions = storage.db.cleanup_old_questions()
            
            for question_id, telegram_id, username in old_questions:
                try:
                    bot.send_message(
                        telegram_id,
                        f"⏰ *Вопрос #{question_id} не получил ответа*\n\n"
                        f"К сожалению, администратор не ответил на ваш вопрос в течение 24 часов.\n"
                        f"Вы можете задать новый вопрос через меню 📨 Задать вопрос."
                    )
                except:
                    pass
                
                try:
                    # Уведомляем всех админов
                    admins = storage.get_all_admins()
                    for admin in admins:
                        try:
                            bot.send_message(
                                admin['telegram_id'],
                                f"⏰ Вопрос #{question_id} от {username} автоматически закрыт (24 часа)"
                            )
                        except:
                            pass
                except:
                    pass
            
            # Очищаем отвеченные вопросы
            deleted_count = storage.cleanup_answered_questions()
            if deleted_count > 0:
                print(f"Очищено {deleted_count} отвеченных вопросов")
            
            time.sleep(3600)
        except Exception as e:
            print(f"Ошибка в cleanup_old_questions: {e}")
            time.sleep(300)

def is_admin(user_id):
    return storage.is_admin(user_id)

def is_user_in_chat(user_id):
    return storage.get_active_chat(user_id) is not None

def can_answer_question(question_id):
    question = storage.get_question(question_id)
    if not question:
        return False, "❌ Вопрос не найден"
    
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
    
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    user = storage.get_or_create_user(user_id, username, message.from_user.first_name)
    
    if not user:
        bot.send_message(user_id, "❌ Ошибка при создании пользователя.")
        return
    
    if storage.is_banned(user_id):
        user_data = storage.get_user(user_id)
        if user_data['ban_until']:
            ban_until = datetime.fromisoformat(user_data['ban_until'])
            remaining = ban_until - datetime.now()
            if remaining.total_seconds() > 0:
                ban_time = f"ещё {format_duration(int(remaining.total_seconds()))}"
            else:
                ban_time = "истёк"
        else:
            ban_time = "навсегда"
        
        bot.send_message(
            user_id, 
            f"🚫 Вы заблокированы администратором.\n"
            f"Причина: {user_data['ban_reason']}\n"
            f"Бан: {ban_time}"
        )
        return
    
    if is_admin(user_id):
        admin_panel(message)
        return
    
    if storage.check_spam(user_id):
        storage.ban_user(user_id, 3600, "Спам (более 10 сообщений за 10 секунд)")
        bot.send_message(
            user_id,
            "🚫 Вы были заблокированы за спам на 1 час."
        )
        return
    
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
        "• Используйте /stop в чате для завершения\n\n"
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
        "• /help - Функции\n"
        "• /tasks - Список вопросов\n"
        "• /ban [ID] [время] [причина] - Забанить\n"
        "• /unban [ID] [причина] - Разбанить\n"
        "• /mute chat [ID] [время] [причина] - Заглушить в переписке\n"
        "• /mute question [ID] [время] [причина] - Заглушить в вопросах\n"
        "• /unmute chat [ID] [причина] - Снять мут с переписки\n"
        "• /unmute question [ID] [причина] - Снять мут с вопросов\n"
        "• /stop [причина] - Завершить текущий чат с причиной\n"
        "• /message [ID] текст - Отправить сообщение\n"
        "• /full - Раскрыть ссылку в вопросе\n"
        "• /stats - Статистика бота\n"
        "• /clients [число/all] - Список пользователей\n"
        "• /stauser [ID] - Статистика пользователя\n"
        "• /allmuted [chat/question] - Все заглушенные\n"
        "• /admin [ID] - Назначить администратора\n"
        "• /adminoff [ID] - Снять администратора\n"
        "• /adminlist - Список администраторов\n"
        "• /adminmessage [сообщение] - Рассылка всем админам\n"
        "• /autohello - Управление автоприветствиями\n\n"
        
        "*Бан с указанием времени:*\n"
        "`/ban 123456789` - навсегда\n"
        "`/ban 123456789 1d` - на 1 день\n"
        "`/ban 123456789 1y1d1h1m1s спам` - сложный формат\n\n"
        
        "*Мут с указанием времени:*\n"
        "`/mute chat 123456789` - мут в переписке навсегда\n"
        "`/mute question 123456789 1h` - мут в вопросах на 1 час\n"
        "`/unmute chat 123456789 прощен` - снять мут с переписки\n"
        "`/unmute question 123456789` - снять мут с вопросов\n\n"
        
        "*Команда /allmuted:*\n"
        "`/allmuted` - все заглушенные\n"
        "`/allmuted chat` - заглушенные в переписке\n"
        "`/allmuted question` - заглушенные в вопросах\n\n"
        
        "*Админ-команды:*\n"
        "`/admin 123456789` - назначить админа\n"
        "`/adminoff 123456789` - снять админа\n"
        "`/adminlist` - список всех админов\n"
        "`/adminmessage Важное сообщение` - рассылка всем админам\n\n"
        
        "*Автоприветствия:*\n"
        "`/autohello {1} Текст` - установить сообщение 1\n"
        "`/autohello {2} Текст` - установить сообщение 2\n"
        "`/autohello [off 1,2]` - отключить сообщения 1 и 2\n"
        "`/autohello list` - посмотреть все сообщения\n"
        "`/autohello clear` - очистить все сообщения"
    )
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    user_id = message.from_user.id
    
    if is_user_in_chat(user_id):
        end_chat(user_id, "user_used_command")
        bot.send_message(user_id, "❌ Диалог завершен, так как вы использовали команду.")
        return
    
    bot.send_message(user_id, "✅ Действие отменено.")
    start_command(message)

@bot.message_handler(commands=['stop'])
def stop_command(message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        if storage.is_banned(user_id):
            return
        
        if is_user_in_chat(user_id):
            end_chat(user_id, "user_stop")
            bot.send_message(user_id, "⏹ Вы завершили переписку.")
            return
        
        bot.send_message(user_id, "❌ Вы не находитесь в активной переписке.")
        return
    
    active_user_id = None
    for uid, chat_data in storage.cache['active_chats'].items():
        if chat_data['admin_id'] == user_id:
            active_user_id = uid
            break
    
    if not active_user_id:
        bot.send_message(user_id, "❌ Нет активных чатов")
        return
    
    parts = message.text.split(maxsplit=1)
    reason = parts[1] if len(parts) > 1 else None
    
    if reason:
        end_chat_with_reason(active_user_id, reason)
    else:
        end_chat(active_user_id, "admin_stop")
        bot.send_message(user_id, "✅ Чат завершен")

def end_chat(user_id, reason="normal"):
    chat_data = storage.get_active_chat(user_id)
    if not chat_data:
        return
    
    admin_id = chat_data['admin_id']
    user_name = chat_data['user_name']
    
    messages = {
        "user_used_command": "⏹ Чат завершен (пользователь использовал команду)",
        "user_stop": "⏹ Пользователь завершил переписку",
        "link_sent": "⏹ Чат завершен (отправка ссылки при запрете)",
        "ban": "⏹ Чат завершен (пользователь забанен)",
        "admin_stop": "⏹ Администратор завершил переписку",
        "normal": "⏹ Чат завершен",
        "admin_cancelled": "⏹ Чат отклонен администратором",
        "mute_chat": "⏹ Чат завершен (пользователь заглушен в переписке)"
    }
    
    message_text = messages.get(reason, "⏹ Чат завершен")
    
    try:
        bot.send_message(admin_id, f"{message_text} с {user_name} (`{user_id}`)")
    except:
        pass
    
    if reason not in ["ban", "mute_chat"] and not storage.is_banned(user_id):
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
    
    storage.end_chat(user_id)

def end_chat_with_reason(user_id, reason):
    chat_data = storage.get_active_chat(user_id)
    if not chat_data:
        return
    
    admin_id = chat_data['admin_id']
    user_name = chat_data['user_name']
    
    try:
        bot.send_message(admin_id, f"⏹ Чат завершен с {user_name} (`{user_id}`)\nПричина: {reason}")
    except:
        pass
    
    if not storage.is_banned(user_id):
        try:
            bot.send_message(user_id, f"⏹ Администратор завершил переписку.\nПричина: {reason}")
        except:
            pass
    
    storage.end_chat(user_id)

@bot.message_handler(commands=['admin'])
def admin_command(message):
    """Назначение администратора"""
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔ У вас нет доступа к этой команде")
        return
    
    main_admin = storage.get_main_admin()
    if not main_admin or message.from_user.id != main_admin['telegram_id']:
        bot.send_message(message.chat.id, "⛔ Только главный администратор может назначать других администраторов")
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, 
                        "Используйте: /admin ID\n"
                        "Пример: /admin 123456789",
                        parse_mode='Markdown')
        return
    
    user_id_str = parts[1]
    
    if not user_id_str.isdigit():
        bot.send_message(message.chat.id, "❌ ID должен быть числом")
        return
    
    user_id = int(user_id_str)
    
    if user_id == MAIN_ADMIN_ID:
        bot.send_message(message.chat.id, "❌ Этот пользователь уже является главным администратором")
        return
    
    if storage.is_admin(user_id):
        bot.send_message(message.chat.id, f"✅ Пользователь `{user_id}` уже является администратором")
        return
    
    # Получаем информацию о пользователе
    user = storage.get_user(user_id)
    if not user:
        bot.send_message(message.chat.id, f"❌ Пользователь с ID `{user_id}` не найден")
        return
    
    username = user.get('username', '')
    first_name = user.get('first_name', 'Пользователь')
    
    # Добавляем администратора
    success = storage.add_admin(user_id, username, first_name, message.from_user.id)
    
    if success:
        bot.send_message(message.chat.id, f"✅ Пользователь `{user_id}` назначен администратором")
        
        # Уведомляем всех админов
        admins = storage.get_all_admins()
        admin_name = message.from_user.first_name
        admin_id = message.from_user.id
        
        notification = (
            f"👑 *Новый администратор назначен*\n\n"
            f"👤 *Пользователь:* {first_name} (@{username if username else 'без_username'})\n"
            f"🆔 *ID:* `{user_id}`\n"
            f"👑 *Назначил:* {admin_name} (`{admin_id}`)"
        )
        
        for admin in admins:
            try:
                if admin['telegram_id'] != message.from_user.id:  # Не отправляем тому, кто назначил
                    bot.send_message(admin['telegram_id'], notification, parse_mode='Markdown')
            except:
                pass
        
        try:
            bot.send_message(
                user_id,
                f"👑 *Вы назначены администратором!*\n\n"
                f"Теперь у вас есть доступ к командам:\n"
                f"• /help - Функции\n"
                f"• /tasks - Список вопросов\n"
                f"• /stats - Статистика\n"
                f"• и другим административным функциям\n\n"
                f"Назначил: {message.from_user.first_name} (`{message.from_user.id}`)"
            )
            time.sleep(0.5)
            # Отправляем панель администратора новому админу
            admin_panel_for_user(user_id)
        except:
            pass
    else:
        bot.send_message(message.chat.id, f"❌ Ошибка при назначении администратора")

@bot.message_handler(commands=['adminoff'])
def adminoff_command(message):
    """Снятие администратора"""
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔ У вас нет доступа к этой команде")
        return
    
    main_admin = storage.get_main_admin()
    if not main_admin or message.from_user.id != main_admin['telegram_id']:
        bot.send_message(message.chat.id, "⛔ Только главный администратор может снимать других администраторов")
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, 
                        "Используйте: /adminoff ID\n"
                        "Пример: /adminoff 123456789",
                        parse_mode='Markdown')
        return
    
    user_id_str = parts[1]
    
    if not user_id_str.isdigit():
        bot.send_message(message.chat.id, "❌ ID должен быть числом")
        return
    
    user_id = int(user_id_str)
    
    if user_id == MAIN_ADMIN_ID:
        bot.send_message(message.chat.id, "❌ Нельзя снять главного администратора")
        
        # Уведомляем главного админа о попытке
        admin_name = message.from_user.first_name
        admin_id = message.from_user.id
        
        warning = (
            f"⚠️ *Попытка снятия главного администратора!*\n\n"
            f"👤 *Пользователь:* {admin_name}\n"
            f"🆔 *ID:* `{admin_id}`\n"
            f"⏰ *Время:* {datetime.now().strftime('%H:%M:%S')}\n"
            f"📅 *Дата:* {datetime.now().strftime('%d.%m.%Y')}"
        )
        
        try:
            bot.send_message(MAIN_ADMIN_ID, warning, parse_mode='Markdown')
        except:
            pass
        
        return
    
    if not storage.is_admin(user_id):
        bot.send_message(message.chat.id, f"❌ Пользователь `{user_id}` не является администратором")
        return
    
    # Удаляем администратора
    deleted, result_message = storage.remove_admin(user_id)
    
    if deleted:
        bot.send_message(message.chat.id, f"✅ Пользователь `{user_id}` снят с должности администратора")
        
        # Уведомляем всех админов
        admins = storage.get_all_admins()
        admin_name = message.from_user.first_name
        admin_id = message.from_user.id
        
        removed_admin_info = storage.get_admin_info(user_id)
        removed_admin_name = removed_admin_info.get('first_name', f'ID: {user_id}') if removed_admin_info else f'ID: {user_id}'
        
        notification = (
            f"👑 *Администратор снят с должности*\n\n"
            f"👤 *Пользователь:* {removed_admin_name}\n"
            f"🆔 *ID:* `{user_id}`\n"
            f"👑 *Снял:* {admin_name} (`{admin_id}`)"
        )
        
        for admin in admins:
            try:
                if admin['telegram_id'] != message.from_user.id:  # Не отправляем тому, кто снял
                    bot.send_message(admin['telegram_id'], notification, parse_mode='Markdown')
            except:
                pass
        
        try:
            bot.send_message(
                user_id,
                f"👑 *Вы сняты с должности администратора*\n\n"
                f"Теперь у вас нет доступа к административным функциям бота.\n"
                f"Снял: {message.from_user.first_name} (`{message.from_user.id}`)"
            )
        except:
            pass
    else:
        bot.send_message(message.chat.id, f"❌ {result_message}")

@bot.message_handler(commands=['adminlist'])
def adminlist_command(message):
    """Список администраторов"""
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔ У вас нет доступа к этой команде")
        return
    
    admins = storage.get_all_admins()
    
    if not admins:
        bot.send_message(message.chat.id, "👑 Нет администраторов в базе данных.")
        return
    
    text = f"👑 *Список администраторов ({len(admins)}):*\n\n"
    
    for i, admin in enumerate(admins, 1):
        admin_id = admin['telegram_id']
        username = admin.get('username', '')
        first_name = admin.get('first_name', '')
        
        # ИСПРАВЛЕНИЕ: убираем двойной @
        display_name = ""
        if username:
            if username.startswith('@'):
                username = username[1:]  # Убираем первый @
            display_name = f"@{username}"  # Добавляем один @
        elif first_name:
            display_name = first_name
        else:
            display_name = f"ID: {admin_id}"
        
        is_main = " (Главный)" if admin.get('is_main_admin') else ""
        
        text += f"{i}. {display_name} `({admin_id})`{is_main}\n"
        
        if admin.get('added_at'):
            added_at = datetime.fromisoformat(admin['added_at'])
            text += f"   Назначен: {added_at.strftime('%d.%m.%Y %H:%M')}\n"
        
        # Добавляем информацию о том, кто назначил
        added_by = admin.get('added_by')
        if added_by:
            added_by_admin = storage.get_admin_info(added_by)
            if added_by_admin:
                added_by_name = added_by_admin.get('first_name', f'ID: {added_by}')
                text += f"   Назначил: {added_by_name}\n"
        
        text += "\n"
    
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            bot.send_message(message.chat.id, part, parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(commands=['adminmessage'])
def adminmessage_command(message):
    """Рассылка сообщений всем администраторам (только для главного админа)"""
    if message.from_user.id != MAIN_ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ Только главный администратор может использовать эту команду")
        return
    
    if len(message.text) <= 13:
        bot.send_message(message.chat.id, 
                        "Используйте: /adminmessage [сообщение]\n"
                        "Пример: /adminmessage Важное обновление!",
                        parse_mode='Markdown')
        return
    
    message_text = message.text[13:].strip()
    
    if not message_text:
        bot.send_message(message.chat.id, "❌ Сообщение не может быть пустым")
        return
    
    admins = storage.get_all_admins()
    
    if not admins:
        bot.send_message(message.chat.id, "❌ Нет администраторов для рассылки")
        return
    
    admin_name = message.from_user.first_name
    admin_id = message.from_user.id
    
    notification = (
        f"📢 *Сообщение от главного администратора*\n\n"
        f"👑 *Отправитель:* {admin_name} (`{admin_id}`)\n"
        f"⏰ *Время:* {datetime.now().strftime('%H:%M:%S')}\n"
        f"📅 *Дата:* {datetime.now().strftime('%d.%m.%Y')}\n\n"
        f"💬 *Сообщение:*\n{message_text}"
    )
    
    success_count = 0
    fail_count = 0
    
    for admin in admins:
        try:
            bot.send_message(admin['telegram_id'], notification, parse_mode='Markdown')
            success_count += 1
        except Exception as e:
            print(f"Ошибка отправки админу {admin['telegram_id']}: {e}")
            fail_count += 1
    
    result_message = (
        f"✅ *Рассылка завершена*\n\n"
        f"📤 Отправлено: {success_count} из {len(admins)}\n"
        f"❌ Ошибок: {fail_count}"
    )
    
    bot.send_message(message.chat.id, result_message, parse_mode='Markdown')

def admin_panel_for_user(user_id):
    """Отправляет панель администратора конкретному пользователю"""
    stats = storage.get_statistics()
    
    text = (
        f"👑 *Панель администратора*\n\n"
        f"📊 Статистика:\n"
        f"• Вопросов: {stats['pending_questions']}\n"
        f"• Чатов: {stats['active_chats']}\n"
        f"• Пользователей: {stats['total_users']}\n"
        f"• Активных сегодня: {stats['active_today']}\n"
        f"• Активных банов: {stats['bans']}\n"
        f"• Муты в вопр.: {stats['mutes_questions']}\n"
        f"• Муты в чате: {stats['mutes_chat']}\n"
        f"• Вопросов сегодня: {stats['questions_today']}\n"
        f"• Администраторов: {stats['admins']}\n\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}"
    )
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton(f'📋 Вопросы ({stats["pending_questions"]})'),
        types.KeyboardButton(f'💬 Чаты ({stats["active_chats"]})'),
        types.KeyboardButton(f'🚫 Баны ({stats["bans"]})'),
        types.KeyboardButton(f'🔇 Муты в вопр. ({stats["mutes_questions"]})'),
        types.KeyboardButton(f'🔇 Муты в чате ({stats["mutes_chat"]})'),
        types.KeyboardButton('🔄 Обновить')
    )
    
    bot.send_message(user_id, text, parse_mode='Markdown', reply_markup=markup)

def admin_panel(message):
    admin_panel_for_user(message.from_user.id)

@bot.message_handler(commands=['tasks'])
def tasks_command(message):
    if not is_admin(message.from_user.id):
        return
    
    show_tasks(message)

@bot.message_handler(commands=['stats'])
def stats_command(message):
    if not is_admin(message.from_user.id):
        return
    
    stats = storage.get_statistics()
    
    text = (
        f"📊 *Статистика бота*\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"🟢 Активных сегодня: {stats['active_today']}\n"
        f"📨 Вопросов сегодня: {stats['questions_today']}\n"
        f"⏳ Ожидающих ответа: {stats['pending_questions']}\n"
        f"💬 Активных чатов: {stats['active_chats']}\n"
        f"🚫 Активных банов: {stats['bans']}\n"
        f"🔇 Муты в вопросах: {stats['mutes_questions']}\n"
        f"🔇 Муты в переписке: {stats['mutes_chat']}\n"
        f"👑 Администраторов: {stats['admins']}\n\n"
        f"🔄 Бот запущен: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
    )
    
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(commands=['ban'])
def ban_command(message):
    if not is_admin(message.from_user.id):
        return
    
    parts = message.text.split(maxsplit=3)
    if len(parts) < 2:
        bot.send_message(message.chat.id, 
                        "Используйте: /ban ID [время] [причина]\n"
                        "Примеры:\n"
                        "`/ban 123456789` - навсегда\n"
                        "`/ban 123456789 1d` - на 1 день\n"
                        "`/ban 123456789 1y1d1h1m1s спам`\n"
                        "`/ban 123456789 1y1d5h10s нарушение правил`",
                        parse_mode='Markdown')
        return
    
    user_id_str = parts[1]
    
    if not user_id_str.isdigit():
        bot.send_message(message.chat.id, "❌ ID должен быть числом")
        return
    
    user_id = int(user_id_str)
    
    # Проверяем, не админ ли это
    if storage.is_admin(user_id):
        bot.send_message(message.chat.id, "❌ Нельзя забанить администратора")
        
        # Если пытались забанить главного админа - уведомляем его
        if user_id == MAIN_ADMIN_ID:
            admin_name = message.from_user.first_name
            admin_id = message.from_user.id
            
            warning = (
                f"⚠️ *Попытка бана главного администратора!*\n\n"
                f"👤 *Пользователь:* {admin_name}\n"
                f"🆔 *ID:* `{admin_id}`\n"
                f"⏰ *Время:* {datetime.now().strftime('%H:%M:%S')}\n"
                f"📅 *Дата:* {datetime.now().strftime('%d.%m.%Y')}"
            )
            
            try:
                bot.send_message(MAIN_ADMIN_ID, warning, parse_mode='Markdown')
            except:
                pass
        
        return
    
    if user_id == message.from_user.id:
        bot.send_message(message.chat.id, "❌ Нельзя забанить себя")
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
    
    success, result_message = storage.ban_user(user_id, duration_seconds, reason, message.from_user.id)
    
    if success:
        duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
        bot.send_message(message.chat.id, f"✅ Пользователь `{user_id}` забанен на {duration_text}.\nПричина: {reason}")
        
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
    else:
        bot.send_message(message.chat.id, f"❌ {result_message}")

@bot.message_handler(commands=['unban'])
def unban_command(message):
    if not is_admin(message.from_user.id):
        return
    
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Используйте: /unban ID [причина]")
        return
    
    target = parts[1]
    
    if not target.isdigit():
        bot.send_message(message.chat.id, "❌ ID должен быть числом")
        return
    
    user_id = int(target)
    
    reason = "Причина не указана"
    if len(parts) >= 3:
        reason = parts[2]
    
    success, result_message = storage.unban_user(user_id, reason, message.from_user.id)
    
    if success:
        bot.send_message(message.chat.id, f"✅ Пользователь `{user_id}` разбанен.\nПричина: {reason}")
        
        try:
            bot.send_message(user_id, f"✅ Вы были разблокированы администратором.\nПричина: {reason}")
        except:
            pass
    else:
        bot.send_message(message.chat.id, f"❌ {result_message}")

@bot.message_handler(commands=['mute'])
def mute_command(message):
    if not is_admin(message.from_user.id):
        return
    
    parts = message.text.split(maxsplit=4)
    if len(parts) < 3:
        bot.send_message(message.chat.id, 
                        "Используйте:\n"
                        "`/mute chat ID [время] [причина]` - мут в переписке\n"
                        "`/mute question ID [время] [причина]` - мут в вопросах\n\n"
                        "*Примеры:*\n"
                        "`/mute chat 123456789` - навсегда в переписке\n"
                        "`/mute question 123456789 1h` - на 1 час в вопросах\n"
                        "`/mute chat 123456789 2d5m флуд` - на 2 дня 5 минут\n"
                        "`/mute question 123456789 1y6mon2w3d нарушение`",
                        parse_mode='Markdown')
        return
    
    mute_type = parts[1].lower()
    user_id_str = parts[2]
    
    if mute_type not in ['chat', 'question']:
        bot.send_message(message.chat.id, "❌ Тип мута должен быть 'chat' или 'question'")
        return
    
    if not user_id_str.isdigit():
        bot.send_message(message.chat.id, "❌ ID должен быть числом")
        return
    
    user_id = int(user_id_str)
    
    # Проверяем, не админ ли это
    if storage.is_admin(user_id):
        bot.send_message(message.chat.id, "❌ Нельзя замутить администратора")
        return
    
    if user_id == message.from_user.id:
        bot.send_message(message.chat.id, "❌ Нельзя замутить себя")
        return
    
    duration_str = ""
    reason = "Нарушение правил"
    
    if len(parts) >= 4:
        time_match = re.search(r'(\d+[ymondhs]?\s*)+', parts[3].lower())
        if time_match:
            duration_str = parts[3]
            if len(parts) >= 5:
                reason = parts[4]
        else:
            reason = parts[3] if len(parts) == 4 else " ".join(parts[3:])
    
    duration_seconds = parse_duration(duration_str)
    
    if mute_type == 'chat':
        success, result_message = storage.mute_user_chat(user_id, duration_seconds, reason, message.from_user.id)
        mute_text = "в переписке"
    else:
        success, result_message = storage.mute_user_questions(user_id, duration_seconds, reason, message.from_user.id)
        mute_text = "в вопросах"
    
    if success:
        duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
        bot.send_message(message.chat.id, f"✅ Пользователь `{user_id}` заглушен {mute_text} на {duration_text}.\nПричина: {reason}")
        
        try:
            if duration_seconds == 0:
                mute_time = "навсегда"
            else:
                mute_time = format_duration(duration_seconds)
            
            if mute_type == 'chat':
                message_to_user = (
                    f"🔇 Вы были заглушены в переписке администратором.\n\n"
                    f"⚠️ *Вам запрещено использовать прямую переписку.*\n\n"
                    f"Причина: {reason}\n"
                    f"Срок: {mute_time}\n\n"
                    f"Вы по-прежнему можете задавать вопросы через раздел 📨 Задать вопрос."
                )
            else:
                message_to_user = (
                    f"🔇 Вы были заглушены в вопросах администратором.\n\n"
                    f"⚠️ *Вам запрещено задавать вопросы.*\n\n"
                    f"Причина: {reason}\n"
                    f"Срок: {mute_time}\n\n"
                    f"Вы по-прежнему можете использовать прямую переписку через раздел 💬 Прямая переписка."
                )
            
            bot.send_message(user_id, message_to_user)
        except:
            pass
    else:
        bot.send_message(message.chat.id, f"❌ {result_message}")

@bot.message_handler(commands=['unmute'])
def unmute_command(message):
    if not is_admin(message.from_user.id):
        return
    
    parts = message.text.split(maxsplit=3)
    if len(parts) < 3:
        bot.send_message(message.chat.id, 
                        "Используйте:\n"
                        "`/unmute chat ID [причина]` - снять мут с переписки\n"
                        "`/unmute question ID [причина]` - снять мут с вопросов\n\n"
                        "*Примеры:*\n"
                        "`/unmute chat 123456789` - снять мут с переписки\n"
                        "`/unmute question 123456789 прощен` - снять мут с вопросов\n"
                        "`/unmute chat 123456789 прощен, но было` - с причиной",
                        parse_mode='Markdown')
        return
    
    mute_type = parts[1].lower()
    user_id_str = parts[2]
    
    if mute_type not in ['chat', 'question']:
        bot.send_message(message.chat.id, "❌ Тип должен быть 'chat' или 'question'")
        return
    
    if not user_id_str.isdigit():
        bot.send_message(message.chat.id, "❌ ID должен быть числом")
        return
    
    user_id = int(user_id_str)
    
    reason = "Причина не указана"
    if len(parts) >= 4:
        reason = parts[3]
    
    if mute_type == 'chat':
        user = storage.get_user(user_id)
        if not user:
            bot.send_message(message.chat.id, f"❌ Пользователь `{user_id}` не найден")
            return
        
        if not user['is_muted_chat']:
            bot.send_message(message.chat.id, f"ℹ️ Пользователь `{user_id}` не заглушен в переписке")
            return
        
        success, result_message = storage.unmute_user_chat(user_id, reason, message.from_user.id)
        
        if success:
            bot.send_message(message.chat.id, f"✅ С пользователя `{user_id}` снят мут в переписке.\nПричина: {reason}")
            
            try:
                bot.send_message(
                    user_id,
                    f"🔊 *С вас снят мут в переписке!*\n\n"
                    f"Теперь вы снова можете использовать прямую переписку.\n"
                    f"Причина: {reason}"
                )
            except:
                pass
        else:
            bot.send_message(message.chat.id, f"❌ {result_message}")
    
    else:  # question
        user = storage.get_user(user_id)
        if not user:
            bot.send_message(message.chat.id, f"❌ Пользователь `{user_id}` не найден")
            return
        
        if not user['is_muted_questions']:
            bot.send_message(message.chat.id, f"ℹ️ Пользователь `{user_id}` не заглушен в вопросах")
            return
        
        success, result_message = storage.unmute_user_questions(user_id, reason, message.from_user.id)
        
        if success:
            bot.send_message(message.chat.id, f"✅ С пользователя `{user_id}` снят мут в вопросах.\nПричина: {reason}")
            
            try:
                bot.send_message(
                    user_id,
                    f"🔊 *С вас снят мут в вопросах!*\n\n"
                    f"Теперь вы снова можете задавать вопросы.\n"
                    f"Причина: {reason}"
                )
            except:
                pass
        else:
            bot.send_message(message.chat.id, f"❌ {result_message}")

@bot.message_handler(commands=['allmuted'])
def allmuted_command(message):
    if not is_admin(message.from_user.id):
        return
    
    parts = message.text.split()
    mute_type = None
    
    if len(parts) >= 2:
        mute_type = parts[1].lower()
        if mute_type not in ['chat', 'question']:
            bot.send_message(message.chat.id, 
                           "Используйте:\n"
                           "`/allmuted` - все заглушенные\n"
                           "`/allmuted chat` - заглушенные в переписке\n"
                           "`/allmuted question` - заглушенные в вопросах",
                           parse_mode='Markdown')
            return
    
    if mute_type == 'chat':
        muted_users = storage.get_muted_chat_users()
        title = "в переписке"
    elif mute_type == 'question':
        muted_users = storage.get_muted_questions_users()
        title = "в вопросах"
    else:
        muted_users = storage.get_all_muted_users()
        title = "вообще"
    
    if not muted_users:
        bot.send_message(message.chat.id, f"✅ Нет пользователей заглушенных {title}.")
        return
    
    text = f"🔇 *Пользователи заглушенные {title} ({len(muted_users)}):*\n\n"
    
    for i, user in enumerate(muted_users, 1):
        user_id = user['telegram_id']
        username = user.get('username') or user.get('first_name', f'ID: {user_id}')
        
        # ИСПРАВЛЕНИЕ: убираем двойной @
        if username and username.startswith('@'):
            username = username[1:]
        
        mute_types = []
        mute_times = []
        mute_reasons = []
        
        if user.get('is_muted_chat') and mute_type in [None, 'chat']:
            mute_types.append("переписка")
            if user['mute_chat_until']:
                mute_until = datetime.fromisoformat(user['mute_chat_until'])
                remaining = mute_until - datetime.now()
                if remaining.total_seconds() > 0:
                    mute_times.append(f"до {mute_until.strftime('%d.%m.%Y %H:%M')}")
                else:
                    mute_times.append("истёк")
            else:
                mute_times.append("навсегда")
            mute_reasons.append(user.get('mute_chat_reason', 'не указана'))
        
        if user.get('is_muted_questions') and mute_type in [None, 'question']:
            mute_types.append("вопросы")
            if user['mute_questions_until']:
                mute_until = datetime.fromisoformat(user['mute_questions_until'])
                remaining = mute_until - datetime.now()
                if remaining.total_seconds() > 0:
                    mute_times.append(f"до {mute_until.strftime('%d.%m.%Y %H:%M')}")
                else:
                    mute_times.append("истёк")
            else:
                mute_times.append("навсегда")
            mute_reasons.append(user.get('mute_questions_reason', 'не указана'))
        
        text += f"{i}. `{user_id}` (@{username if username else 'без_username'})\n"
        
        for j, (mute_type_name, mute_time, mute_reason) in enumerate(zip(mute_types, mute_times, mute_reasons), 1):
            text += f"   {j}. {mute_type_name.capitalize()}: {mute_time}\n"
            text += f"      Причина: {mute_reason}\n"
        
        text += "\n"
    
    if len(text) > 4000:
        parts_text = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts_text:
            bot.send_message(message.chat.id, part, parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, text, parse_mode='Markdown')

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
        bot.send_message(message.chat.id, help_text, parse_mode='Markdown')
        return
    
    full_text = message.text[8:].strip()
    
    match = re.search(r'\[([^\]]+)\]\s*(.+)', full_text)
    if not match:
        bot.send_message(message.chat.id, "❌ Неверный формат. Пример: `/message [123456789] Текст`", parse_mode='Markdown')
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
        bot.send_message(message.chat.id, "❌ Введите текст сообщения.")
        return
    
    if ',' in params:
        parts = [p.strip() for p in params.split(',', 1)]
        user_id_str = parts[0]
        admin_name = parts[1] if len(parts) > 1 else "Модератор"
    else:
        user_id_str = params
        admin_name = "Модератор"
    
    if not user_id_str.isdigit():
        bot.send_message(message.chat.id, "❌ ID должен быть числом")
        return
    
    user_id = int(user_id_str)
    
    user = storage.get_user(user_id)
    if not user:
        bot.send_message(message.chat.id, f"❌ Пользователь с ID `{user_id}` не найден")
        return
    
    if storage.is_banned(user_id):
        bot.send_message(message.chat.id, f"⚠️ Пользователь `{user_id}` забанен")
        return
    
    # Получаем информацию об отправителе (админе)
    sender_admin = storage.get_admin_info(message.from_user.id)
    sender_name = sender_admin.get('first_name', message.from_user.first_name) if sender_admin else message.from_user.first_name
    sender_username = sender_admin.get('username', f'@{message.from_user.username}') if sender_admin else (f'@{message.from_user.username}' if message.from_user.username else 'без username')
    
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
    
    # Если отправляем админу - добавляем информацию об отправителе
    if storage.is_admin(user_id):
        sender_info = (
            f"\n\n👤 *Отправитель:* {sender_name}\n"
            f"🆔 *ID:* `{message.from_user.id}`\n"
            f"📝 *Username:* {sender_username}"
        )
        formatted_message += sender_info
    
    try:
        bot.send_message(user_id, formatted_message, parse_mode='Markdown')
        bot.send_message(message.chat.id, f"✅ Сообщение отправлено пользователю `{user_id}`")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)}")

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
        show_full_question_text(message.chat.id, question_id)
        return
    
    bot.send_message(
        message.chat.id,
        "❌ Используйте команду:\n"
        "• `/full#1` (без пробела)\n"
        "• `/full #1` (с пробелом)\n"
        "• `/full 1` (с пробелом)",
        parse_mode='Markdown'
    )

def show_full_question_text(chat_id, question_id):
    question = storage.get_question(question_id)
    if not question:
        bot.send_message(chat_id, "❌ Вопрос не найден.")
        return
    
    full_text = f"📨 *Полный текст вопроса #{question_id}*\n\n"
    
    user_id_display = f"`{question['user_id']}`"
    if question['username']:
        # ИСПРАВЛЕНИЕ: убираем двойной @
        username = question['username']
        if username.startswith('@'):
            username = username[1:]  # Убираем первый @
        full_text += f"👤 @{username} ({user_id_display})\n"  # Добавляем один @
    else:
        full_text += f"👤 {user_id_display}\n"
    
    full_text += f"⏰ {question['time']} | {question['date']}\n\n"
    full_text += f"💬 {question['text']}"
    
    urls = re.findall(r'(?i)https?://[^\s<>"]+|www\.[^\s<>"]+\.[^\s<>"]+', question['text'])
    
    if urls:
        from collections import defaultdict
        url_counts = defaultdict(int)
        url_examples = {}
        
        for url in urls:
            normalized_url = url.lower()
            url_counts[normalized_url] += 1
            if normalized_url not in url_examples:
                url_examples[normalized_url] = url
        
        full_text += f"\n\n🔗 *Ссылки ({len(urls)}):*\n"
        
        for i, (normalized_url, count) in enumerate(url_counts.items(), 1):
            example_url = url_examples[normalized_url]
            if count > 1:
                full_text += f"{i}. {example_url} (x{count})\n"
            else:
                full_text += f"{i}. {example_url}\n"
    
    bot.send_message(chat_id, full_text, parse_mode='Markdown', disable_web_page_preview=True)

@bot.message_handler(commands=['clients', 'Clients'])
def clients_command(message):
    if not is_admin(message.from_user.id):
        return
    
    parts = message.text.split()
    limit = 20
    
    if len(parts) >= 2:
        param = parts[1].lower()
        if param == 'all':
            limit = None
        elif param.isdigit():
            limit = min(int(param), 100)
        else:
            bot.send_message(message.chat.id, 
                           "Используйте:\n"
                           "`/clients` - 20 пользователей\n"
                           "`/clients 50` - 50 пользователей\n"
                           "`/clients all` - все пользователи",
                           parse_mode='Markdown')
            return
    
    users = storage.get_all_users(limit)
    
    if not users:
        bot.send_message(message.chat.id, "📭 Нет пользователей в базе данных.")
        return
    
    total_users = len(storage.get_all_users())
    
    if limit is None:
        header = f"👥 *Все пользователи ({total_users}):*\n\n"
    else:
        header = f"👥 *Пользователи ({len(users)} из {total_users}):*\n\n"
    
    response = header
    
    for i, user in enumerate(users, 1):
        user_id = user['telegram_id']
        
        # ИСПРАВЛЕНИЕ: убираем двойной @
        display_name = ""
        if user.get('username'):
            username = user['username']
            if username.startswith('@'):
                username = username[1:]  # Убираем первый @
            display_name = f"@{username}"  # Добавляем один @
        elif user.get('first_name'):
            display_name = user['first_name']
        
        if display_name:
            response += f"{i}. `{user_id}` ({display_name})\n"
        else:
            response += f"{i}. `{user_id}`\n"
    
    if len(response) > 4000:
        parts_response = []
        current_part = ""
        
        for line in response.split('\n'):
            if len(current_part) + len(line) + 1 < 4000:
                current_part += line + '\n'
            else:
                parts_response.append(current_part)
                current_part = line + '\n'
        
        if current_part:
            parts_response.append(current_part)
        
        for part in parts_response:
            bot.send_message(message.chat.id, part, parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, response, parse_mode='Markdown')

@bot.message_handler(commands=['stauser', 'statUser', 'StatUser'])
def stauser_command(message):
    if not is_admin(message.from_user.id):
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Используйте: `/stauser ID`", parse_mode='Markdown')
        return
    
    user_id_str = parts[1]
    
    if not user_id_str.isdigit():
        bot.send_message(message.chat.id, "❌ ID должен быть числом")
        return
    
    user_id = int(user_id_str)
    
    stats = storage.get_user_statistics(user_id)
    
    if not stats:
        bot.send_message(message.chat.id, f"❌ Пользователь с ID `{user_id}` не найден")
        return
    
    response = f"👤 *Статистика пользователя:* `{user_id}`\n\n"
    
    # ИСПРАВЛЕНИЕ: убираем двойной @
    display_name = ""
    if stats.get('username'):
        username = stats['username']
        if username.startswith('@'):
            username = username[1:]  # Убираем первый @
        display_name = f"@{username}"  # Добавляем один @
    elif stats.get('first_name'):
        display_name = stats['first_name']
    
    if display_name:
        response += f"📝 *Имя:* {display_name}\n"
    
    if stats.get('joined_date'):
        joined = datetime.fromisoformat(stats['joined_date'])
        response += f"📅 *Зарегистрирован:* {joined.strftime('%d.%m.%Y')}\n"
    
    if stats.get('last_seen'):
        last_seen = datetime.fromisoformat(stats['last_seen'])
        response += f"🕐 *Последняя активность:* {last_seen.strftime('%d.%m.%Y %H:%M')}\n"
    
    response += f"\n📊 *Статистика вопросов:*\n"
    response += f"• Всего задано: {stats.get('total_questions', 0)}\n"
    response += f"• Ожидают ответа: {stats.get('pending_questions', 0)}\n"
    response += f"• Получили ответ: {stats.get('answered_questions', 0)}\n"
    response += f"• Задано сегодня: {stats.get('questions_today', 0)}\n"
    
    response += f"\n🚫 *Статусы:*\n"
    
    if stats['is_banned']:
        if stats['ban_until']:
            ban_until = datetime.fromisoformat(stats['ban_until'])
            remaining = ban_until - datetime.now()
            if remaining.total_seconds() > 0:
                ban_time = f"до {ban_until.strftime('%d.%m.%Y %H:%M')}"
            else:
                ban_time = "истёк"
        else:
            ban_time = "навсегда"
        
        response += f"• Бан: ✅ Да ({ban_time})\n"
        response += f"  Причина: {stats.get('ban_reason', 'не указана')}\n"
    else:
        response += f"• Бан: ❌ Нет\n"
    
    if stats['is_muted_questions']:
        if stats['mute_questions_until']:
            mute_until = datetime.fromisoformat(stats['mute_questions_until'])
            remaining = mute_until - datetime.now()
            if remaining.total_seconds() > 0:
                mute_time = f"до {mute_until.strftime('%d.%m.%Y %H:%M')}"
            else:
                mute_time = "истёк"
        else:
            mute_time = "навсегда"
        
        response += f"• Мут в вопросах: ✅ Да ({mute_time})\n"
        response += f"  Причина: {stats.get('mute_questions_reason', 'не указана')}\n"
    else:
        response += f"• Мут в вопросах: ❌ Нет\n"
    
    if stats['is_muted_chat']:
        if stats['mute_chat_until']:
            mute_until = datetime.fromisoformat(stats['mute_chat_until'])
            remaining = mute_until - datetime.now()
            if remaining.total_seconds() > 0:
                mute_time = f"до {mute_until.strftime('%d.%m.%Y %H:%M')}"
            else:
                mute_time = "истёк"
        else:
            mute_time = "навсегда"
        
        response += f"• Мут в переписке: ✅ Да ({mute_time})\n"
        response += f"  Причина: {stats.get('mute_chat_reason', 'не указана')}\n"
    else:
        response += f"• Мут в переписке: ❌ Нет\n"
    
    if stats.get('in_chat'):
        response += f"\n💬 *В чате сейчас:* ✅ Да\n"
        if stats.get('chat_start_time'):
            start_time = datetime.fromisoformat(stats['chat_start_time'])
            response += f"  Начат: {start_time.strftime('%H:%M')}\n"
    else:
        response += f"\n💬 *В чате сейчас:* ❌ Нет\n"
    
    bot.send_message(message.chat.id, response, parse_mode='Markdown')

@bot.message_handler(commands=['autohello'])
def autohello_command(message):
    """Управление автоприветственными сообщениями"""
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔ У вас нет доступа к этой команде")
        return
    
    text = message.text.strip()
    
    if text == '/autohello':
        show_autohello_help(message)
        return
    
    # Обработка команды /autohello list
    if text == '/autohello list':
        show_autohello_list(message)
        return
    
    # Обработка команды /autohello clear
    if text == '/autohello clear':
        success, result_message = storage.clear_autohello_messages(message.from_user.id)
        bot.send_message(message.chat.id, result_message)
        return
    
    # Обработка команды /autohello {N} текст
    match_set = re.match(r'^/autohello\s+\{(\d+)\}\s+(.+)$', text)
    if match_set:
        message_num = int(match_set.group(1))
        message_text = match_set.group(2).strip()
        
        if not 1 <= message_num <= 10:
            bot.send_message(message.chat.id, "❌ Номер сообщения должен быть от 1 до 10")
            return
        
        if not message_text:
            bot.send_message(message.chat.id, "❌ Текст сообщения не может быть пустым")
            return
        
        success, result_message = storage.set_autohello_message(message.from_user.id, message_num, message_text)
        bot.send_message(message.chat.id, result_message)
        return
    
    # Обработка команды /autohello [off N1,N2,...]
    match_off = re.match(r'^/autohello\s+\[off\s+([\d\s,]+)\]$', text)
    if match_off:
        nums_str = match_off.group(1)
        message_nums = [num.strip() for num in nums_str.split(',')]
        
        success, result_message = storage.disable_autohello_messages(message.from_user.id, message_nums)
        bot.send_message(message.chat.id, result_message)
        return
    
    # Если команда не распознана
    show_autohello_help(message)

def show_autohello_help(message):
    """Показывает справку по команде /autohello"""
    help_text = (
        "🤖 *Управление автоприветственными сообщениями*\n\n"
        "*Использование:*\n"
        "`/autohello {1} Текст` - установить сообщение 1\n"
        "`/autohello {2} Привет!` - установить сообщение 2\n"
        "`/autohello [off 1,2]` - отключить сообщения 1 и 2\n"
        "`/autohello list` - посмотреть все сообщения\n"
        "`/autohello clear` - очистить все сообщения\n\n"
        "*Примеры:*\n"
        "`/autohello {1} Здравствуйте! Чем могу помочь?`\n"
        "`/autohello {2} Опишите вашу проблему.`\n"
        "`/autohello [off 1,2]` - отключить оба сообщения\n\n"
        "*Примечание:*\n"
        "• Можно создать до 10 сообщений\n"
        "• Сообщения отправляются по порядку номеров\n"
        "• Сообщения отправляются автоматически при начале чата"
    )
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

def show_autohello_list(message):
    """Показывает список автоприветственных сообщений"""
    admin_id = message.from_user.id
    all_messages = storage.get_all_autohello_messages(admin_id)
    
    if not all_messages:
        bot.send_message(message.chat.id, "📭 Нет сохраненных автоприветственных сообщений.")
        return
    
    active_messages = storage.get_autohello_messages(admin_id)
    
    text = "📝 *Ваши автоприветственные сообщения:*\n\n"
    
    for num in range(1, 11):
        if num in all_messages:
            msg_data = all_messages[num]
            status = "✅ Активно" if msg_data['active'] else "❌ Отключено"
            preview = msg_data['text'][:50] + "..." if len(msg_data['text']) > 50 else msg_data['text']
            text += f"{num}. {status}\n   {preview}\n\n"
        else:
            text += f"{num}. ⬜ Не установлено\n\n"
    
    text += f"\n*Активных сообщений:* {len(active_messages)}/10"
    
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

# ===== ОБРАБОТКА СООБЩЕНИЙ =====
@bot.message_handler(func=lambda m: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    
    if storage.is_banned(user_id):
        return
    
    if storage.check_spam(user_id):
        storage.ban_user(user_id, 3600, "Спам (более 10 сообщений за 10 секунд)")
        bot.send_message(
            user_id,
            "🚫 Вы были заблокированы за спам на 1 час."
        )
        return
    
    if is_admin(user_id) and message.chat.id == user_id:
        handle_admin_actions(message)
        return
    
    if is_user_in_chat(user_id):
        handle_user_in_chat(message)
        return
    
    if message.text in ['📨 Задать вопрос', '💬 Прямая переписка', 'ℹ️ Помощь']:
        handle_user_menu_buttons(message)

def handle_admin_actions(message):
    stats = storage.get_statistics()
    
    if message.text == f'📋 Вопросы ({stats["pending_questions"]})' or message.text == '📋 Задачи (/tasks)':
        show_tasks(message)
    elif message.text == f'💬 Чаты ({stats["active_chats"]})' or message.text == '💬 Активные чаты':
        show_active_chats(message)
    elif message.text == f'🚫 Баны ({stats["bans"]})' or message.text == '🚫 Бан-лист':
        show_bans(message)
    elif message.text == f'🔇 Муты в вопр. ({stats["mutes_questions"]})':
        show_mutes_questions(message)
    elif message.text == f'🔇 Муты в чате ({stats["mutes_chat"]})':
        show_mutes_chat(message)
    elif message.text == '🔄 Обновить':
        admin_panel(message)
    else:
        handle_admin_to_user(message)

def handle_user_menu_buttons(message):
    user_id = message.from_user.id
    
    if message.text == '📨 Задать вопрос':
        if storage.is_muted_questions(user_id):
            user_data = storage.get_user(user_id)
            if user_data['mute_questions_until']:
                mute_until = datetime.fromisoformat(user_data['mute_questions_until'])
                remaining = mute_until - datetime.now()
                if remaining.total_seconds() > 0:
                    mute_time = f"ещё {format_duration(int(remaining.total_seconds()))}"
                else:
                    mute_time = "истёк"
            else:
                mute_time = "навсегда"
            
            bot.send_message(
                user_id,
                f"🔇 *Вам запрещено задавать вопросы!*\n\n"
                f"Причина: {user_data['mute_questions_reason']}\n"
                f"Мут: {mute_time}\n\n"
                f"Вы можете использовать прямую переписку через раздел 💬 Прямая переписка."
            )
            return
        
        cooldown_check, remaining = storage.check_cooldown(user_id, 'question', QUESTION_COOLDOWN)
        if not cooldown_check:
            bot.send_message(user_id, f"⏳ Следующий вопрос можно задать через {remaining} секунд.")
            return
        
        ask_question_start(user_id)
        
    elif message.text == '💬 Прямая переписка':
        if storage.is_muted_chat(user_id):
            user_data = storage.get_user(user_id)
            if user_data['mute_chat_until']:
                mute_until = datetime.fromisoformat(user_data['mute_chat_until'])
                remaining = mute_until - datetime.now()
                if remaining.total_seconds() > 0:
                    mute_time = f"ещё {format_duration(int(remaining.total_seconds()))}"
                else:
                    mute_time = "истёк"
            else:
                mute_time = "навсегда"
            
            bot.send_message(
                user_id,
                f"🔇 *Вам запрещено использовать прямую переписку!*\n\n"
                f"Причина: {user_data['mute_chat_reason']}\n"
                f"Мут: {mute_time}\n\n"
                f"Вы можете задавать вопросы через раздел 📨 Задать вопрос."
            )
            return
        
        cooldown_check, remaining = storage.check_cooldown(user_id, 'chat_request', CHAT_REQUEST_COOLDOWN)
        if not cooldown_check:
            bot.send_message(user_id, f"⏳ Следующий запрос переписки можно отправить через {remaining} секунд.")
            return
        
        request_chat_flow(message)
        
    elif message.text == 'ℹ️ Помощь':
        show_user_help(message)

# ===== ОБРАБОТКА СООБЩЕНИЙ В ЧАТЕ =====
def handle_user_in_chat(message):
    user_id = message.from_user.id
    chat_data = storage.get_active_chat(user_id)
    
    if not chat_data:
        return
    
    if message.content_type != 'text':
        bot.send_message(user_id, "❌ В чате разрешены только текстовые сообщения.")
        return
    
    chat_limit = chat_data.get('message_limit', 350)
    if len(message.text) > chat_limit:
        bot.send_message(user_id, f"⚠️ Сообщение слишком длинное ({len(message.text)}/{chat_limit} символов)")
        return
    
    allow_links = chat_data.get('allow_links', True)
    sender = chat_data['user_name']
    
    try:
        text = message.text.strip()
        
        urls = find_all_urls(text)
        
        if urls and not allow_links:
            masked_text, url_count = find_and_mask_urls(text)
            
            user_id_display = f"`{user_id}`"
            username_display = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
            
            escaped_sender = escape_markdown(sender)
            escaped_username = escape_markdown(username_display)
            
            admin_message = f"👤 *{escaped_sender}* ({escaped_username}) {user_id_display} отправил ссылку:\n\n{masked_text}"
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_user_{user_id}'),
                types.InlineKeyboardButton('🔇 Замутить в переписке', callback_data=f'mute_chat_{user_id}')
            )
            
            bot.send_message(
                chat_data['admin_id'],
                admin_message,
                parse_mode='Markdown',
                reply_markup=markup,
                disable_web_page_preview=True
            )
            
            end_chat(user_id, "link_sent")
            bot.send_message(user_id, "⏹ Переписка завершена. Отправка ссылок запрещена.")
            
            return
        
        escaped_sender = escape_markdown(sender)
        
        bot.send_message(
            chat_data['admin_id'],
            f"👤 *{escaped_sender}:*\n{text[:500]}",
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        
        storage.update_chat_activity(user_id)
            
    except Exception as e:
        bot.send_message(user_id, f"❌ Ошибка отправки: {str(e)}")

def handle_admin_to_user(message):
    active_user_id = None
    for user_id, chat_data in storage.cache['active_chats'].items():
        if chat_data['admin_id'] == message.from_user.id:
            active_user_id = user_id
            break
    
    if not active_user_id:
        return
    
    chat_data = storage.get_active_chat(active_user_id)
    if not chat_data:
        return
    
    try:
        if message.content_type == 'text':
            escaped_admin_name = escape_markdown(chat_data['admin_name'])
            
            bot.send_message(
                active_user_id,
                f"👨‍💼 *{escaped_admin_name} (Администратор):*\n{message.text}",
                parse_mode='Markdown'
            )
            
            storage.update_chat_activity(active_user_id)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Не удалось отправить: {str(e)}")

# ===== ФУНКЦИИ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =====
def ask_question_start(user_id):
    pending_questions = storage.get_pending_questions()
    user_questions = [q for q in pending_questions if q['user_id'] == user_id]
    
    if len(user_questions) >= 5:
        bot.send_message(
            user_id, 
            f"❌ *Превышен лимит активных вопросов!*\n\n"
            f"У вас уже {len(user_questions)}/5 активных вопросов.\n"
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
    
    storage.set_cooldown(user_id, 'question')
    
    question_text = message.text.strip()
    
    if len(question_text) > QUESTION_LIMIT:
        bot.send_message(user_id, f"❌ Вопрос слишком длинный (макс. {QUESTION_LIMIT} символов).")
        start_command(message)
        return
    
    if len(question_text) < 10:
        bot.send_message(user_id, "❌ Вопрос слишком короткий (минимум 10 символов).")
        start_command(message)
        return
    
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    masked_text, url_count = find_and_mask_urls(question_text)
    
    question_id = storage.add_question(user_id, username, question_text, masked_text, url_count)
    
    if not question_id:
        bot.send_message(user_id, "❌ Ошибка при отправке вопроса.")
        start_command(message)
        return
    
    notify_admin_about_question(question_id, {
        'user_id': user_id,
        'username': username,
        'text': question_text,
        'masked_text': masked_text,
        'url_count': url_count
    })
    
    confirm_text = f"✅ *Вопрос #{question_id} отправлен!*\n\nАдминистратор ответит в ближайшее время."
    
    bot.send_message(user_id, confirm_text, parse_mode='Markdown')
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📨 Задать вопрос'),
        types.KeyboardButton('💬 Прямая переписка'),
        types.KeyboardButton('ℹ️ Помощь')
    )
    bot.send_message(user_id, "Главное меню:", reply_markup=markup)

def request_chat_flow(message):
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    
    storage.set_cooldown(user_id, 'chat_request')
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton('✅ Принять чат', callback_data=f'accept_chat_{user_id}'),
        types.InlineKeyboardButton('❌ Отклонить', callback_data=f'reject_chat_{user_id}')
    )
    
    admins = storage.get_all_admins()
    
    for admin in admins:
        try:
            bot.send_message(
                admin['telegram_id'],
                f"💬 *Запрос на переписку*\n"
                f"От: {username} (`{user_id}`)\n"
                f"Время: {datetime.now().strftime('%H:%M:%S')}",
                parse_mode='Markdown',
                reply_markup=markup,
                disable_web_page_preview=True
            )
        except:
            pass
    
    bot.send_message(user_id, "✅ Запрос на переписку отправлен администратору!")
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📨 Задать вопрос'),
        types.KeyboardButton('💬 Прямая переписка'),
        types.KeyboardButton('ℹ️ Помощь')
    )
    bot.send_message(user_id, "Главное меню:", reply_markup=markup)

# ===== ФУНКЦИИ ДЛЯ АДМИНА =====
def show_tasks(message):
    pending_questions = storage.get_pending_questions()
    
    if not pending_questions:
        bot.send_message(message.chat.id, "✅ *Все вопросы обработаны!*", parse_mode='Markdown')
        return
    
    bot.send_message(message.chat.id, f"📋 *Задачи: {len(pending_questions)}*", parse_mode='Markdown')
    
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
            types.InlineKeyboardButton('🔇 Замутить в вопросах', callback_data=f'mute_questions_{question["id"]}')
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
        
        bot.send_message(message.chat.id, question_text, parse_mode='Markdown', 
                        reply_markup=markup, disable_web_page_preview=True)

def show_active_chats(message):
    active_chats = storage.get_all_active_chats()
    
    if not active_chats:
        bot.send_message(message.chat.id, "💭 Нет активных чатов")
        return
    
    text = "💬 *Активные чаты:*\n\n"
    for telegram_id, chat_data in storage.cache['active_chats'].items():
        if chat_data['admin_id'] == message.from_user.id:
            chat_limit = chat_data.get('message_limit', 350)
            text += f"👤 {chat_data['user_name']}\n"
            text += f"ID: `{telegram_id}`\n"
            text += f"Имя админа: {chat_data['admin_name']}\n"
            text += f"Лимит: {chat_limit} символов\n"
            text += f"Ссылки: {'✅ Разрешены' if chat_data.get('allow_links', True) else '❌ Запрещены'}\n\n"
    
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

def show_bans(message):
    banned_users = storage.get_banned_users()
    
    if not banned_users:
        bot.send_message(message.chat.id, "✅ Нет забаненных пользователей.")
        return
    
    text = f"🚫 *Забаненные пользователи ({len(banned_users)}):*\n\n"
    
    for i, user in enumerate(banned_users, 1):
        user_id = user['telegram_id']
        username = user.get('username') or user.get('first_name', f'ID: {user_id}')
        
        # ИСПРАВЛЕНИЕ: убираем двойной @
        if username and username.startswith('@'):
            username = username[1:]
        
        if user['ban_until']:
            ban_until = datetime.fromisoformat(user['ban_until'])
            remaining = ban_until - datetime.now()
            if remaining.total_seconds() > 0:
                ban_time = f"до {ban_until.strftime('%d.%m.%Y %H:%M')}"
            else:
                ban_time = "истёк"
        else:
            ban_time = "навсегда"
        
        text += f"{i}. `{user_id}` (@{username if username else 'без_username'})\n"
        text += f"   Время: {ban_time}\n"
        text += f"   Причина: {user.get('ban_reason', 'не указана')}\n\n"
    
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            bot.send_message(message.chat.id, part, parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, text, parse_mode='Markdown')

def show_mutes_questions(message):
    muted_users = storage.get_muted_questions_users()
    
    if not muted_users:
        bot.send_message(message.chat.id, "✅ Нет пользователей заглушенных в вопросах.")
        return
    
    text = f"🔇 *Пользователи заглушенные в вопросах ({len(muted_users)}):*\n\n"
    
    for i, user in enumerate(muted_users, 1):
        user_id = user['telegram_id']
        username = user.get('username') or user.get('first_name', f'ID: {user_id}')
        
        # ИСПРАВЛЕНИЕ: убираем двойной @
        if username and username.startswith('@'):
            username = username[1:]
        
        if user['mute_questions_until']:
            mute_until = datetime.fromisoformat(user['mute_questions_until'])
            remaining = mute_until - datetime.now()
            if remaining.total_seconds() > 0:
                mute_time = f"до {mute_until.strftime('%d.%m.%Y %H:%M')}"
            else:
                mute_time = "истёк"
        else:
            mute_time = "навсегда"
        
        text += f"{i}. `{user_id}` (@{username if username else 'без_username'})\n"
        text += f"   Время: {mute_time}\n"
        text += f"   Причина: {user.get('mute_questions_reason', 'не указана')}\n\n"
    
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            bot.send_message(message.chat.id, part, parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, text, parse_mode='Markdown')

def show_mutes_chat(message):
    muted_users = storage.get_muted_chat_users()
    
    if not muted_users:
        bot.send_message(message.chat.id, "✅ Нет пользователей заглушенных в переписке.")
        return
    
    text = f"🔇 *Пользователи заглушенные в переписке ({len(muted_users)}):*\n\n"
    
    for i, user in enumerate(muted_users, 1):
        user_id = user['telegram_id']
        username = user.get('username') or user.get('first_name', f'ID: {user_id}')
        
        # ИСПРАВЛЕНИЕ: убираем двойной @
        if username and username.startswith('@'):
            username = username[1:]
        
        if user['mute_chat_until']:
            mute_until = datetime.fromisoformat(user['mute_chat_until'])
            remaining = mute_until - datetime.now()
            if remaining.total_seconds() > 0:
                mute_time = f"до {mute_until.strftime('%d.%m.%Y %H:%M')}"
            else:
                mute_time = "истёк"
        else:
            mute_time = "навсегда"
        
        text += f"{i}. `{user_id}` (@{username if username else 'без_username'})\n"
        text += f"   Время: {mute_time}\n"
        text += f"   Причина: {user.get('mute_chat_reason', 'не указана')}\n\n"
    
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            bot.send_message(message.chat.id, part, parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, text, parse_mode='Markdown')

def notify_admin_about_question(question_id, question_data):
    display_text = question_data.get('masked_text', question_data['text'])
    text_preview = display_text[:100] + "..." if len(display_text) > 100 else display_text
    
    can_answer, reason = can_answer_question(question_id)
    
    buttons = []
    if can_answer:
        buttons.append(types.InlineKeyboardButton('✏️ Ответить', callback_data=f'answer_{question_id}'))
    else:
        buttons.append(types.InlineKeyboardButton('✏️ Ответить ⏰', callback_data=f'answer_{question_id}'))
    
    buttons.append(types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_{question_id}'))
    buttons.append(types.InlineKeyboardButton('🔇 Замутить в вопросах', callback_data=f'mute_questions_{question_id}'))
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(*buttons)
    
    user_id_display = f"`{question_data['user_id']}`"
    
    escaped_question_text = escape_markdown(text_preview)
    
    notification = (
        f"📨 *Вопрос #{question_id}*\n"
        f"👤 {question_data['username']} ({user_id_display})\n"
        f"⏰ {datetime.now().strftime('%H:%M')} | {datetime.now().strftime('%d.%m.%Y')}"
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
    
    admins = storage.get_all_admins()
    
    for admin in admins:
        try:
            bot.send_message(admin['telegram_id'], notification, parse_mode='Markdown', 
                           reply_markup=markup, disable_web_page_preview=True)
        except:
            pass

def process_admin_answer(message, question_id):
    if not message.content_type == 'text':
        bot.send_message(message.chat.id, "❌ Ответ должен быть текстовым.")
        return
    
    question = storage.get_question(question_id)
    if not question:
        bot.send_message(message.chat.id, "❌ Вопрос не найден")
        return
    
    can_answer, reason = can_answer_question(question_id)
    if not can_answer:
        bot.send_message(message.chat.id, reason)
        return
    
    user_id = question['user_id']
    
    admin_name = None
    answer_text = None
    
    text = message.text
    name_match = re.match(r'^\s*\[([^\]]+)\]\s*(.+)', text)
    if name_match:
        admin_name = name_match.group(1).strip()
        answer_text = name_match.group(2).strip()
    else:
        answer_text = text.strip()
    
    try:
        question_preview = question['text'][:300] + "..." if len(question['text']) > 300 else question['text']
        
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
        
        full_message = f"{header}\n\n{escaped_answer_text}"
        bot.send_message(user_id, full_message, parse_mode='Markdown')
        
        storage.update_question_status(question_id, 'answered', answer_text, admin_name)
        storage.increment_answer_count(question_id)
        
        answer_count = storage.get_answer_count(question_id)
        remaining = MAX_ANSWERS_PER_QUESTION - answer_count
        
        if remaining > 0:
            bot.send_message(message.chat.id, f"✅ Ответ #{question_id} отправлен {question['username']}\n\n"
                                     f"ℹ️ Можно отправить еще {remaining} ответов на этот вопрос.")
        else:
            bot.send_message(message.chat.id, f"✅ Ответ #{question_id} отправлен {question['username']}\n\n"
                                     f"ℹ️ Достигнут лимит ответов на этот вопрос ({MAX_ANSWERS_PER_QUESTION}).")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка отправки: {str(e)}")

# ===== CALLBACK ОБРАБОТЧИК =====
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    if call.data.startswith('accept_chat_'):
        user_id = int(call.data.replace('accept_chat_', ''))
        
        user = storage.get_user(user_id)
        if not user:
            bot.answer_callback_query(call.id, "❌ Пользователь не найден")
            return
        
        if storage.get_active_chat(user_id):
            bot.answer_callback_query(call.id, "❌ Пользователь уже в чате")
            return
        
        msg = bot.send_message(
            call.message.chat.id,
            f"💬 *Принят запрос на переписку*\n\n"
            f"👤 Пользователь: {user['username'] or user['first_name']} (`{user_id}`)\n\n"
            f"📝 *Как вас звать в этой переписке?*\n"
            f"(Напишите /cancel для отмены)",
            parse_mode='Markdown'
        )
        
        bot.register_next_step_handler(msg, ask_admin_name_step, user_id)
        bot.answer_callback_query(call.id, "✅ Запрос принят")
        return
    
    elif call.data.startswith('reject_chat_'):
        user_id = int(call.data.replace('reject_chat_', ''))
        
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
    
    elif call.data.startswith('ban_') or call.data.startswith('ban_user_'):
        if call.data.startswith('ban_'):
            question_id = int(call.data.replace('ban_', ''))
            question = storage.get_question(question_id)
            if not question:
                bot.answer_callback_query(call.id, "❌ Вопрос не найден")
                return
            user_id = question['user_id']
        else:
            user_id = int(call.data.replace('ban_user_', ''))
        
        # Проверяем, не админ ли это
        if storage.is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Нельзя забанить администратора")
            return
        
        msg = bot.send_message(
            call.message.chat.id,
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
    
    elif call.data.startswith('mute_questions_'):
        question_id = int(call.data.replace('mute_questions_', ''))
        question = storage.get_question(question_id)
        if not question:
            bot.answer_callback_query(call.id, "❌ Вопрос не найден")
            return
        user_id = question['user_id']
        
        # Проверяем, не админ ли это
        if storage.is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Нельзя замутить администратора")
            return
        
        msg = bot.send_message(
            call.message.chat.id,
            f"🔇 *Заглушение пользователя в вопросах*\n\n"
            f"ID: `{user_id}`\n"
            f"Пользователь: {question['username']}\n\n"
            f"Введите время и причину мута в вопросах:\n"
            f"Примеры:\n"
            f"• `1h флуд` - на 1 час за флуд\n"
            f"• `2d нарушение правил` - на 2 дня\n"
            f"• `нарушение` - навсегда\n\n"
            f"Или нажмите /cancel для отмены",
            parse_mode='Markdown'
        )
        
        bot.register_next_step_handler(msg, process_mute_questions_with_reason, user_id)
        bot.answer_callback_query(call.id, "📝 Введите данные...")
    
    elif call.data.startswith('mute_chat_'):
        user_id = int(call.data.replace('mute_chat_', ''))
        
        # Проверяем, не админ ли это
        if storage.is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Нельзя замутить администратора")
            return
        
        msg = bot.send_message(
            call.message.chat.id,
            f"🔇 *Заглушение пользователя в переписке*\n\n"
            f"ID: `{user_id}`\n\n"
            f"Введите время и причину мута в переписке:\n"
            f"Примеры:\n"
            f"• `1h флуд` - на 1 час за флуд\n"
            f"• `2d нарушение правил` - на 2 дня\n"
            f"• `нарушение` - навсегда\n\n"
            f"Или нажмите /cancel для отмены",
            parse_mode='Markdown'
        )
        
        bot.register_next_step_handler(msg, process_mute_chat_with_reason, user_id)
        bot.answer_callback_query(call.id, "📝 Введите данные...")
    
    elif call.data.startswith('answer_'):
        question_id = int(call.data.replace('answer_', ''))
        
        question = storage.get_question(question_id)
        if not question:
            bot.answer_callback_query(call.id, "❌ Вопрос не найден")
            return
        
        can_answer, reason = can_answer_question(question_id)
        if not can_answer:
            bot.answer_callback_query(call.id, reason)
            return
        
        msg = bot.send_message(
            call.message.chat.id,
            f"✏️ *Ответ на вопрос #{question_id}*\n\n"
            f"👤 От: {question['username']} (`{question['user_id']}`)\n"
            f"⏰ {question['time']} | {question['date']}\n"
            f"💬 Вопрос: {escape_markdown(question.get('masked_text', question['text'])[:200])}...\n\n"
            f"*Введите ответ (только текст):*\n"
            f"Используйте [Имя Фамилия] в начале для подписи\n"
            f"Пример: `[Алексей Петров] Ответ...`\n\n"
            f"ℹ️ *Если нужно посмотреть полный текст со ссылками, используйте [/full#{question_id}](#full_{question_id})*",
            parse_mode='Markdown'
        )
        
        bot.register_next_step_handler(msg, process_admin_answer, question_id)
        bot.answer_callback_query(call.id, "✏️ Введите ответ...")

def ask_admin_name_step(message, user_id):
    if message.text == '/cancel':
        bot.send_message(message.chat.id, "❌ Создание чата отменено.")
        
        try:
            bot.send_message(
                user_id,
                "❌ *Во время составления правил для переписки, администратор передумал и отклонил ваш запрос.*"
            )
        except:
            pass
        
        return
    
    admin_name = message.text.strip()[:30]
    
    if not admin_name:
        bot.send_message(message.chat.id, "❌ Имя не может быть пустым.")
        return
    
    user = storage.get_user(user_id)
    if not user:
        bot.send_message(message.chat.id, "❌ Пользователь не найден.")
        return
    
    msg = bot.send_message(
        message.chat.id,
        f"✅ Имя сохранено: *{admin_name}*\n\n"
        f"*Разрешить отправку ссылок?*\n\n"
        f"Напишите `Да` или `Нет` (регистр не важен).\n"
        f"Если выбрать 'Нет', чат автоматически завершится при попытке отправить ссылку.\n\n"
        f"⚠️ *Если ввести что-то другое, по умолчанию будет установлено 'Да'*\n"
        f"(Или /cancel для отмены)",
        parse_mode='Markdown'
    )
    
    bot.register_next_step_handler(msg, ask_links_step, user_id, admin_name)

def ask_links_step(message, user_id, admin_name):
    if message.text == '/cancel':
        bot.send_message(message.chat.id, "❌ Создание чата отменено.")
        
        try:
            bot.send_message(
                user_id,
                "❌ *Во время составления правил для переписки, администратор передумал и отклонил ваш запрос.*"
            )
        except:
            pass
        
        return
    
    text = message.text.strip().lower()
    
    if text == 'да':
        allow_links = True
    elif text == 'нет':
        allow_links = False
    else:
        allow_links = True
    
    msg = bot.send_message(
        message.chat.id,
        f"✅ {'Ссылки разрешены' if allow_links else 'Ссылки запрещены'}\n\n"
        f"📝 *Какой лимит символов установим на одно сообщение?*\n\n"
        f"• Минимум: 15 символов\n"
        f"• Максимум: 500 символов\n"
        f"• По умолчанию: 350 символов\n\n"
        f"Введите число (или /cancel для отмены):",
        parse_mode='Markdown'
    )
    
    bot.register_next_step_handler(msg, ask_chat_limit_step, user_id, admin_name, allow_links)

def ask_chat_limit_step(message, user_id, admin_name, allow_links):
    if message.text == '/cancel':
        bot.send_message(message.chat.id, "❌ Создание чата отменено.")
        
        try:
            bot.send_message(
                user_id,
                "❌ *Во время составления правил для переписки, администратор передумал и отклонил ваш запрос.*"
            )
        except:
            pass
        
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
    
    user = storage.get_user(user_id)
    if not user:
        bot.send_message(message.chat.id, "❌ Пользователь не найден.")
        return
    
    username = user['username'] or user['first_name']
    
    chat_id = storage.start_chat(user_id, message.from_user.id, username, admin_name, allow_links, limit)
    
    if not chat_id:
        bot.send_message(message.chat.id, "❌ Ошибка при создании чата.")
        return
    
    escaped_admin_name = escape_markdown(admin_name)
    escaped_username = escape_markdown(username)
    
    # Сначала отправляем сообщение о начале чата
    bot.send_message(
        user_id,
        f"💬 *Переписка начата!*\n\n"
        f"👨‍💼 Администратор: *{escaped_admin_name}*\n"
        f"🔗 Ссылки: {'✅ Разрешены' if allow_links else '❌ Запрещены'}\n"
        f"📝 Лимит сообщений: {limit} символов\n\n"
        f"✨ *Теперь вы можете общаться напрямую!*\n"
        f"⚠️ *Ограничение:* {limit} символов на сообщение\n"
        f"⏹ *Завершить переписку:* /stop\n"
        f"🚫 *Не используйте другие команды в чате*",
        parse_mode='Markdown'
    )
    
    # Затем отправляем автоприветственные сообщения
    storage.send_autohello_messages(user_id, message.from_user.id, admin_name)
    
    bot.send_message(
        message.chat.id,
        f"💬 *Чат начат!*\n\n"
        f"{confirmation}\n"
        f"🔗 Ссылки: {'✅ Разрешены' if allow_links else '❌ Запрещены'}\n\n"
        f"👤 С пользователем: {escaped_username} (`{user_id}`)\n"
        f"👑 Ваше имя в чате: *{escaped_admin_name}*\n\n"
        f"💭 Теперь все ваши сообщения будут пересылаться.\n"
        f"⏹ Используйте /stop для завершения.",
        parse_mode='Markdown'
    )

def process_ban_with_reason(message, user_id):
    if message.text == '/cancel':
        bot.send_message(message.chat.id, "❌ Блокировка отменена.")
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
    
    success, result_message = storage.ban_user(user_id, duration_seconds, reason, message.from_user.id)
    
    if success:
        duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
        user = storage.get_user(user_id)
        username = user['username'] if user else f'ID: {user_id}'
        
        bot.send_message(message.chat.id, f"🚫 Пользователь `{user_id}` ({username}) забанен на {duration_text}.\nПричина: {reason}")
        
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
    else:
        bot.send_message(message.chat.id, f"❌ {result_message}")

def process_mute_questions_with_reason(message, user_id):
    if message.text == '/cancel':
        bot.send_message(message.chat.id, "❌ Заглушение отменено.")
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
    
    success, result_message = storage.mute_user_questions(user_id, duration_seconds, reason, message.from_user.id)
    
    if success:
        duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
        user = storage.get_user(user_id)
        username = user['username'] if user else f'ID: {user_id}'
        
        bot.send_message(message.chat.id, f"🔇 Пользователь `{user_id}` ({username}) заглушен в вопросах на {duration_text}.\nПричина: {reason}")
        
        try:
            if duration_seconds == 0:
                mute_time = "навсегда"
            else:
                mute_time = format_duration(duration_seconds)
            
            bot.send_message(
                user_id,
                f"🔇 Вы были заглушены в вопросах администратором.\n\n"
                f"⚠️ *Вам запрещено задавать вопросы.*\n\n"
                f"Причина: {reason}\n"
                f"Срок: {mute_time}\n\n"
                f"Вы по-прежнему можете использовать прямую переписку через раздел 💬 Прямая переписка."
            )
        except:
            pass
    else:
        bot.send_message(message.chat.id, f"❌ {result_message}")

def process_mute_chat_with_reason(message, user_id):
    if message.text == '/cancel':
        bot.send_message(message.chat.id, "❌ Заглушение отменено.")
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
    
    success, result_message = storage.mute_user_chat(user_id, duration_seconds, reason, message.from_user.id)
    
    if success:
        duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
        user = storage.get_user(user_id)
        username = user['username'] if user else f'ID: {user_id}'
        
        bot.send_message(message.chat.id, f"🔇 Пользователь `{user_id}` ({username}) заглушен в переписке на {duration_text}.\nПричина: {reason}")
        
        try:
            if duration_seconds == 0:
                mute_time = "навсегда"
            else:
                mute_time = format_duration(duration_seconds)
            
            bot.send_message(
                user_id,
                f"🔇 Вы были заглушены в переписке администратором.\n\n"
                f"⚠️ *Вам запрещено использовать прямую переписку.*\n\n"
                f"Причина: {reason}\n"
                f"Срок: {mute_time}\n\n"
                f"Вы по-прежнему можете задавать вопросы через раздел 📨 Задать вопрос."
            )
        except:
            pass
    else:
        bot.send_message(message.chat.id, f"❌ {result_message}")

# ===== ЗАПУСК =====
if __name__ == '__main__':
    print("=" * 50)
    print(f"🤖 Бот запущен | Главный админ: {MAIN_ADMIN_ID}")
    
    stats = storage.get_statistics()
    admins = storage.get_all_admins()
    
    print(f"👥 Пользователей в БД: {stats['total_users']}")
    print(f"📨 Вопросов в БД: {stats['pending_questions'] + stats['questions_today']}")
    print(f"🚫 Активных банов: {stats['bans']}")
    print(f"🔇 Муты в вопросах: {stats['mutes_questions']}")
    print(f"🔇 Муты в переписке: {stats['mutes_chat']}")
    print(f"💬 Активных чатов: {stats['active_chats']}")
    print(f"👑 Администраторов: {len(admins)}")
    print(f"📝 Автоочистка вопросов: каждые 24 часа")
    print("=" * 50)
    
    expiration_check_thread = threading.Thread(target=check_ban_expirations, daemon=True)
    cleanup_thread = threading.Thread(target=cleanup_old_questions, daemon=True)
    
    expiration_check_thread.start()
    cleanup_thread.start()
    
    try:
        bot.polling(none_stop=True, interval=0)
    except Exception as e:
        print(f"Ошибка при запуске бота: {e}")
