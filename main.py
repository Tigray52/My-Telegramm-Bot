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

bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))
ADMIN_ID = 6337781618

# ===== БАЗА ДАННЫХ =====
class Database:
    def __init__(self, db_name='bot_database.db'):
        self.db_name = db_name
        self.lock = threading.Lock()
        self.init_database()
    
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
            
            conn.commit()
            conn.close()
    
    # ===== ПОЛЬЗОВАТЕЛИ =====
    def get_or_create_user(self, telegram_id, username, first_name):
        """Получает или создает пользователя"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Пытаемся найти пользователя
            cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
            user = cursor.fetchone()
            
            if not user:
                # Создаем нового пользователя
                cursor.execute('''
                    INSERT INTO users (telegram_id, username, first_name, joined_date, last_seen)
                    VALUES (?, ?, ?, ?, ?)
                ''', (telegram_id, username, first_name, datetime.now(), datetime.now()))
                
                user_id = cursor.lastrowid
                cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
                user = cursor.fetchone()
            else:
                # Обновляем last_seen
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
            
            # Получаем внутренний ID пользователя
            cursor.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            user_row = cursor.fetchone()
            
            if not user_row:
                conn.close()
                return None
            
            user_id = user_row[0]
            
            # Добавляем вопрос
            cursor.execute('''
                INSERT INTO questions 
                (user_id, telegram_id, question_text, masked_text, url_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, telegram_id, question_text, masked_text, url_count, datetime.now()))
            
            question_id = cursor.lastrowid
            
            # Обновляем счетчик вопросов пользователя
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
                # Форматируем даты
                if question_dict['created_at']:
                    created = datetime.fromisoformat(question_dict['created_at']) 
                    question_dict['date'] = created.strftime('%d.%m.%Y')
                    question_dict['time'] = created.strftime('%H:%M')
                return question_dict
            
            return None
    
    def get_pending_questions(self):
        """Получает все ожидающие вопросы"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT q.*, u.username, u.telegram_id as user_telegram_id
                FROM questions q
                JOIN users u ON q.user_id = u.id
                WHERE q.status = 'pending'
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
    
    def cleanup_old_questions(self):
        """Очищает вопросы старше 24 часов"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            # Находим вопросы для уведомлений
            cursor.execute('''
                SELECT q.id, u.telegram_id, u.username
                FROM questions q
                JOIN users u ON q.user_id = u.id
                WHERE q.status = 'pending'
                AND q.created_at < datetime('now', '-24 hours')
            ''')
            
            old_questions = cursor.fetchall()
            
            # Обновляем статус
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
            
            # Получаем внутренний ID пользователя
            cursor.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            user_row = cursor.fetchone()
            
            if not user_row:
                conn.close()
                return None
            
            user_id = user_row[0]
            
            # Удаляем старый чат если есть
            cursor.execute('DELETE FROM active_chats WHERE user_id = ?', (user_id,))
            
            # Создаем новый чат
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
            
            # Получаем внутренний ID пользователя
            cursor.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            user_row = cursor.fetchone()
            
            if not user_row:
                conn.close()
                return
            
            user_id = user_row[0]
            
            # Обновляем или вставляем запись
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
            
            # Общее количество пользователей
            cursor.execute('SELECT COUNT(*) FROM users')
            stats['total_users'] = cursor.fetchone()[0]
            
            # Пользователи за сегодня
            cursor.execute('''
                SELECT COUNT(*) FROM users 
                WHERE DATE(last_seen) = DATE('now')
            ''')
            stats['active_today'] = cursor.fetchone()[0]
            
            # Ожидающие вопросы
            cursor.execute('SELECT COUNT(*) FROM questions WHERE status = "pending"')
            stats['pending_questions'] = cursor.fetchone()[0]
            
            # Активные чаты
            cursor.execute('SELECT COUNT(*) FROM active_chats')
            stats['active_chats'] = cursor.fetchone()[0]
            
            # Вопросы за сегодня
            cursor.execute('''
                SELECT COUNT(*) FROM questions 
                WHERE DATE(created_at) = DATE('now')
            ''')
            stats['questions_today'] = cursor.fetchone()[0]
            
            # Баны
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_banned = TRUE')
            stats['bans'] = cursor.fetchone()[0]
            
            # Муты в вопросах
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_muted_questions = TRUE')
            stats['mutes_questions'] = cursor.fetchone()[0]
            
            # Муты в чате
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_muted_chat = TRUE')
            stats['mutes_chat'] = cursor.fetchone()[0]
            
            conn.close()
            return stats

# ===== ХРАНИЛИЩЕ =====
class Storage:
    def __init__(self):
        self.db = Database()
        self.cache = {
            'questions': {},  # Кэш для быстрого доступа
            'active_chats': {}
        }
    
    # ===== ПОЛЬЗОВАТЕЛИ =====
    def get_or_create_user(self, telegram_id, username, first_name):
        return self.db.get_or_create_user(telegram_id, username, first_name)
    
    def get_user(self, telegram_id):
        return self.db.get_user_by_telegram_id(telegram_id)
    
    def is_banned(self, telegram_id):
        user = self.get_user(telegram_id)
        if not user:
            return False
        
        if not user['is_banned']:
            return False
        
        if user['ban_until']:
            ban_until = datetime.fromisoformat(user['ban_until'])
            if datetime.now() > ban_until:
                # Бан истек
                self.db.update_user_ban(user['id'], False)
                return False
        
        return True
    
    def ban_user(self, telegram_id, duration_seconds=0, reason="Нарушение правил"):
        user = self.get_user(telegram_id)
        if not user:
            return False
        
        ban_until = None
        if duration_seconds > 0:
            ban_until = datetime.fromtimestamp(time.time() + duration_seconds)
        
        self.db.update_user_ban(user['id'], True, reason, ban_until)
        
        # Завершаем активный чат если есть
        self.db.end_chat(telegram_id)
        
        return True
    
    def unban_user(self, telegram_id):
        user = self.get_user(telegram_id)
        if not user:
            return False
        
        self.db.update_user_ban(user['id'], False)
        return True
    
    def is_muted_questions(self, telegram_id):
        """Проверяет, заглушен ли пользователь в вопросах"""
        user = self.get_user(telegram_id)
        if not user:
            return False
        
        if not user['is_muted_questions']:
            return False
        
        if user['mute_questions_until']:
            mute_until = datetime.fromisoformat(user['mute_questions_until'])
            if datetime.now() > mute_until:
                # Мут истек
                self.db.update_user_mute_questions(user['id'], False)
                return False
        
        return True
    
    def is_muted_chat(self, telegram_id):
        """Проверяет, заглушен ли пользователь в чате"""
        user = self.get_user(telegram_id)
        if not user:
            return False
        
        if not user['is_muted_chat']:
            return False
        
        if user['mute_chat_until']:
            mute_until = datetime.fromisoformat(user['mute_chat_until'])
            if datetime.now() > mute_until:
                # Мут истек
                self.db.update_user_mute_chat(user['id'], False)
                return False
        
        return True
    
    def mute_user_questions(self, telegram_id, duration_seconds=0, reason="Нарушение правил"):
        """Заглушает пользователя в вопросах"""
        user = self.get_user(telegram_id)
        if not user:
            return False
        
        mute_until = None
        if duration_seconds > 0:
            mute_until = datetime.fromtimestamp(time.time() + duration_seconds)
        
        self.db.update_user_mute_questions(user['id'], True, reason, mute_until)
        return True
    
    def unmute_user_questions(self, telegram_id):
        """Снимает мут с вопросов"""
        user = self.get_user(telegram_id)
        if not user:
            return False
        
        self.db.update_user_mute_questions(user['id'], False)
        return True
    
    def mute_user_chat(self, telegram_id, duration_seconds=0, reason="Нарушение правил"):
        """Заглушает пользователя в чате"""
        user = self.get_user(telegram_id)
        if not user:
            return False
        
        mute_until = None
        if duration_seconds > 0:
            mute_until = datetime.fromtimestamp(time.time() + duration_seconds)
        
        self.db.update_user_mute_chat(user['id'], True, reason, mute_until)
        
        # Завершаем активный чат если есть
        self.db.end_chat(telegram_id)
        
        return True
    
    def unmute_user_chat(self, telegram_id):
        """Снимает мут с чата"""
        user = self.get_user(telegram_id)
        if not user:
            return False
        
        self.db.update_user_mute_chat(user['id'], False)
        return True
    
    # ===== ВОПРОСЫ =====
    def add_question(self, telegram_id, username, question_text, masked_text, url_count):
        question_id = self.db.add_question(telegram_id, question_text, masked_text, url_count)
        
        if question_id:
            # Кэшируем вопрос
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
                'created_at': datetime.now().isoformat()
            }
        
        return question_id
    
    def get_question(self, question_id):
        # Пробуем из кэша
        if question_id in self.cache['questions']:
            return self.cache['questions'][question_id]
        
        # Пробуем из БД
        question = self.db.get_question(question_id)
        if question:
            # Форматируем для совместимости
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
                'created_at': question['created_at']
            }
            
            # Кэшируем
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
                'created_at': question['created_at']
            }
            result.append(formatted)
            
            # Обновляем кэш
            self.cache['questions'][question['id']] = formatted
        
        return result
    
    def update_question_status(self, question_id, status, admin_response=None, admin_name=None):
        self.db.update_question_status(question_id, status, admin_response, admin_name)
        
        # Обновляем кэш
        if question_id in self.cache['questions']:
            self.cache['questions'][question_id]['status'] = status
            if admin_response:
                self.cache['questions'][question_id]['admin_response'] = admin_response
            if admin_name:
                self.cache['questions'][question_id]['admin_name'] = admin_name
    
    def increment_answer_count(self, question_id):
        self.db.increment_answer_count(question_id)
    
    def get_answer_count(self, question_id):
        question = self.get_question(question_id)
        if question:
            return question.get('answer_count', 0)
        return 0
    
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
        # Простая реализация - проверяем частоту сообщений
        # В реальном проекте нужно хранить историю сообщений
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
            # Проверяем баны
            users = storage.db.get_all_users()
            for user_data in users:
                if user_data['is_banned'] and user_data['ban_until']:
                    ban_until = datetime.fromisoformat(user_data['ban_until'])
                    if datetime.now() > ban_until:
                        storage.db.update_user_ban(user_data['id'], False)
                        
                        try:
                            bot.send_message(
                                user_data['telegram_id'],
                                f"✅ *Ваш бан истек!*\n\n"
                                f"Вы снова можете пользоваться ботом.\n"
                                f"Причина бана: {user_data['ban_reason']}"
                            )
                        except:
                            pass
            
            # Проверяем муты в вопросах
            for user_data in users:
                if user_data['is_muted_questions'] and user_data['mute_questions_until']:
                    mute_until = datetime.fromisoformat(user_data['mute_questions_until'])
                    if datetime.now() > mute_until:
                        storage.db.update_user_mute_questions(user_data['id'], False)
                        
                        try:
                            bot.send_message(
                                user_data['telegram_id'],
                                f"✅ *Ваш мут в вопросах истек!*\n\n"
                                f"Вы снова можете задавать вопросы.\n"
                                f"Причина мута: {user_data['mute_questions_reason']}"
                            )
                        except:
                            pass
            
            # Проверяем муты в чате
            for user_data in users:
                if user_data['is_muted_chat'] and user_data['mute_chat_until']:
                    mute_until = datetime.fromisoformat(user_data['mute_chat_until'])
                    if datetime.now() > mute_until:
                        storage.db.update_user_mute_chat(user_data['id'], False)
                        
                        try:
                            bot.send_message(
                                user_data['telegram_id'],
                                f"✅ *Ваш мут в переписке истек!*\n\n"
                                f"Вы снова можете запрашивать прямую переписку.\n"
                                f"Причина мута: {user_data['mute_chat_reason']}"
                            )
                        except:
                            pass
            
            time.sleep(60)
        except Exception as e:
            print(f"Ошибка в check_ban_expirations: {e}")
            time.sleep(60)

def cleanup_old_questions():
    """Очищает вопросы старше 24 часов"""
    while True:
        try:
            old_questions = storage.db.cleanup_old_questions()
            
            # Отправляем уведомления
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
                
                # Уведомляем админа
                try:
                    bot.send_message(
                        ADMIN_ID,
                        f"⏰ Вопрос #{question_id} от {username} автоматически закрыт (24 часа)"
                    )
                except:
                    pass
            
            time.sleep(3600)  # Проверяем каждый час
        except Exception as e:
            print(f"Ошибка в cleanup_old_questions: {e}")
            time.sleep(300)

def is_admin(user_id):
    return user_id == ADMIN_ID

def is_user_in_chat(user_id):
    return storage.get_active_chat(user_id) is not None

def can_answer_question(question_id):
    """Проверяет, можно ли отвечать на вопрос"""
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
    
    # Получаем или создаем пользователя
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    user = storage.get_or_create_user(user_id, username, message.from_user.first_name)
    
    if not user:
        bot.send_message(user_id, "❌ Ошибка при создании пользователя.")
        return
    
    # Проверяем бан
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
    
    # Проверка на спам
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
        "• /admin - Панель управления\n"
        "• /tasks - Список вопросов\n"
        "• /ban [ID] [время] [причина] - Забанить\n"
        "• /unban [ID] - Разбанить\n"
        "• /off [ID] [время] [причина] - Заглушить в вопросах\n"
        "• /on [ID] - Разглушить в вопросах\n"
        "• /stop [причина] - Завершить текущий чат с причиной\n"
        "• /message [ID] текст - Отправить сообщение\n"
        "• /full - Раскрыть ссылку в вопросе\n"
        "• /stats - Статистика бота\n\n"
        
        "*Бан с указанием времени:*\n"
        "`/ban 123456789` - навсегда\n"
        "`/ban 123456789 1d` - на 1 день\n"
        "`/ban 123456789 1w3d5h спам` - на 1 неделю 3 дня 5 часов\n\n"
        
        "*Мут в вопросах (/off):*\n"
        "`/off 123456789` - навсегда\n"
        "`/off 123456789 1h` - на 1 час\n"
        "`/off 123456789 2d5m флуд` - на 2 дня 5 минут за флуд\n\n"
        
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
    
    if user_id == ADMIN_ID:
        # Отмена ответа на вопрос
        pass
    
    bot.send_message(user_id, "✅ Действие отменено.")
    start_command(message)

@bot.message_handler(commands=['stop'])
def stop_command(message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        # Для обычных пользователей
        if storage.is_banned(user_id):
            return
        
        if is_user_in_chat(user_id):
            end_chat(user_id, "user_stop")
            bot.send_message(user_id, "⏹ Вы завершили переписку.")
            return
        
        bot.send_message(user_id, "❌ Вы не находитесь в активной переписке.")
        return
    
    # Для админа
    active_user_id = None
    for uid, chat_data in storage.cache['active_chats'].items():
        if chat_data['admin_id'] == ADMIN_ID:
            active_user_id = uid
            break
    
    if not active_user_id:
        bot.send_message(ADMIN_ID, "❌ Нет активных чатов")
        return
    
    # Извлекаем причину
    parts = message.text.split(maxsplit=1)
    reason = parts[1] if len(parts) > 1 else None
    
    if reason:
        end_chat_with_reason(active_user_id, reason)
        bot.send_message(ADMIN_ID, f"✅ Чат завершен с причиной: {reason}")
    else:
        end_chat(active_user_id, "admin_stop")
        bot.send_message(ADMIN_ID, "✅ Чат завершен")

def end_chat(user_id, reason="normal"):
    """Завершает чат без указания причины"""
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
        bot.send_message(admin_id, f"{message_text} с {user_name}")
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
    """Завершает чат с указанием причины"""
    chat_data = storage.get_active_chat(user_id)
    if not chat_data:
        return
    
    admin_id = chat_data['admin_id']
    user_name = chat_data['user_name']
    
    # Уведомляем админа
    try:
        bot.send_message(admin_id, f"⏹ Чат завершен с {user_name}\nПричина: {reason}")
    except:
        pass
    
    # Уведомляем пользователя
    if not storage.is_banned(user_id):
        try:
            bot.send_message(user_id, f"⏹ Администратор завершил переписку.\nПричина: {reason}")
        except:
            pass
    
    storage.end_chat(user_id)

@bot.message_handler(commands=['admin'])
def admin_command(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔ У вас нет доступа к этой команде")
        return
    
    admin_panel(message)

def admin_panel(message):
    stats = storage.get_statistics()
    
    text = (
        f"👑 *Панель администратора*\n\n"
        f"📊 Статистика:\n"
        f"• Вопросов: {stats['pending_questions']}\n"
        f"• Чатов: {stats['active_chats']}\n"
        f"• Пользователей: {stats['total_users']}\n"
        f"• Активных сегодня: {stats['active_today']}\n"
        f"• Активных банов: {stats['bans']}\n"
        f"• Муты в вопросах: {stats['mutes_questions']}\n"
        f"• Муты в переписке: {stats['mutes_chat']}\n"
        f"• Вопросов сегодня: {stats['questions_today']}\n\n"
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
        f"🔇 Муты в переписке: {stats['mutes_chat']}\n\n"
        f"🔄 Бот запущен: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
    )
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

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
        bot.send_message(ADMIN_ID, f"❌ Пользователь `{user_id}` не найден или не забанен.")

@bot.message_handler(commands=['off'])
def off_command(message):
    """Заглушает пользователя в вопросах"""
    if not is_admin(message.from_user.id):
        return
    
    parts = message.text.split(maxsplit=3)
    if len(parts) < 2:
        bot.send_message(ADMIN_ID, 
                        "Используйте: /off ID [время] [причина]\n"
                        "Примеры:\n"
                        "`/off 123456789` - навсегда\n"
                        "`/off 123456789 1h` - на 1 час\n"
                        "`/off 123456789 2d5m флуд`\n"
                        "`/off 123456789 1w нарушение правил`",
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
    
    storage.mute_user_questions(user_id, duration_seconds, reason)
    
    duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
    bot.send_message(ADMIN_ID, f"✅ Пользователь `{user_id}` заглушен в вопросах на {duration_text}.\nПричина: {reason}")
    
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

@bot.message_handler(commands=['on'])
def on_command(message):
    """Снимает мут с вопросов"""
    if not is_admin(message.from_user.id):
        return
    
    if len(message.text.split()) < 2:
        bot.send_message(ADMIN_ID, "Используйте: /on ID")
        return
    
    target = message.text.split(maxsplit=1)[1]
    
    if not target.isdigit():
        bot.send_message(ADMIN_ID, "❌ ID должен быть числом")
        return
    
    user_id = int(target)
    
    if storage.unmute_user_questions(user_id):
        bot.send_message(ADMIN_ID, f"✅ Пользователь `{user_id}` разглушен в вопросах.")
        
        try:
            bot.send_message(
                user_id,
                "✅ Вы были разглушены в вопросах администратором.\n\n"
                "Теперь вы снова можете задавать вопросы."
            )
        except:
            pass
    else:
        bot.send_message(ADMIN_ID, f"❌ Пользователь `{user_id}` не найден или не заглушен в вопросах.")

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
    
    user = storage.get_user(user_id)
    if not user:
        bot.send_message(ADMIN_ID, f"❌ Пользователь с ID `{user_id}` не найден")
        return
    
    if storage.is_banned(user_id):
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
    
    bot.send_message(
        ADMIN_ID,
        "❌ Используйте команду:\n"
        "• `/full#1` (без пробела)\n"
        "• `/full #1` (с пробелом)\n"
        "• `/full 1` (с пробелом)",
        parse_mode='Markdown'
    )

def show_full_question_text(admin_id, question_id):
    question = storage.get_question(question_id)
    if not question:
        bot.send_message(admin_id, "❌ Вопрос не найден.")
        return
    
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

# ===== ОБРАБОТКА СООБЩЕНИЙ =====
@bot.message_handler(func=lambda m: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    
    if storage.is_banned(user_id):
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
        # Проверяем, не заглушен ли пользователь в вопросах
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
        # Проверяем, не заглушен ли пользователь в чате
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
    
    # Разрешаем ТОЛЬКО текстовые сообщения в чате
    if message.content_type != 'text':
        bot.send_message(user_id, "❌ В чате разрешены только текстовые сообщения.")
        return
    
    # Проверяем лимит символов для чата
    chat_limit = chat_data.get('message_limit', 350)
    if len(message.text) > chat_limit:
        bot.send_message(user_id, f"⚠️ Сообщение слишком длинное ({len(message.text)}/{chat_limit} символов)")
        return
    
    # Проверяем настройки чата
    allow_links = chat_data.get('allow_links', True)
    sender = chat_data['user_name']
    
    try:
        text = message.text.strip()
        
        # Проверяем есть ли ссылки
        urls = find_all_urls(text)
        
        if urls and not allow_links:
            # Ссылки запрещены - маскируем и завершаем чат
            masked_text, url_count = find_and_mask_urls(text)
            
            # Форматируем ID для копирования
            user_id_display = f"`{user_id}`"
            username_display = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
            
            # Экранируем имя отправителя
            escaped_sender = escape_markdown(sender)
            escaped_username = escape_markdown(username_display)
            
            # Отправляем админу с кнопкой для мута в переписке
            admin_message = f"👤 *{escaped_sender}* ({escaped_username}) {user_id_display} отправил ссылку:\n\n{masked_text}"
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_user_{user_id}'),
                types.InlineKeyboardButton('🔇 Замутить в переписке', callback_data=f'mute_chat_{user_id}')
            )
            
            sent_msg = bot.send_message(
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
        escaped_sender = escape_markdown(sender)
        escaped_message_text = escape_markdown(text[:500])
        
        sent_msg = bot.send_message(
            ADMIN_ID,
            f"👤 *{escaped_sender}:*\n{escaped_message_text}",
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        
        storage.update_chat_activity(user_id)
            
    except Exception as e:
        bot.send_message(user_id, f"❌ Ошибка отправки: {str(e)}")

def handle_admin_to_user(message):
    # Находим активный чат с этим админом
    active_user_id = None
    for user_id, chat_data in storage.cache['active_chats'].items():
        if chat_data['admin_id'] == ADMIN_ID:
            active_user_id = user_id
            break
    
    if not active_user_id:
        return
    
    chat_data = storage.get_active_chat(active_user_id)
    if not chat_data:
        return
    
    try:
        if message.content_type == 'text':
            # Экранируем имя админа и текст сообщения
            escaped_admin_name = escape_markdown(chat_data['admin_name'])
            escaped_message_text = escape_markdown(message.text)
            
            bot.send_message(
                active_user_id,
                f"👨‍💼 *{escaped_admin_name} (Администратор):*\n{escaped_message_text}",
                parse_mode='Markdown'
            )
            
            storage.update_chat_activity(active_user_id)
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Не удалось отправить: {str(e)}")

# ===== ФУНКЦИИ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =====
def ask_question_start(user_id):
    # Проверяем количество активных вопросов
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
    """Обработка запроса на прямую переписку (ИСПРАВЛЕНО)"""
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    
    storage.set_cooldown(user_id, 'chat_request')
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton('✅ Принять чат', callback_data=f'accept_chat_{user_id}'),
        types.InlineKeyboardButton('❌ Отклонить', callback_data=f'reject_chat_{user_id}')
    )
    
    bot.send_message(
        ADMIN_ID,
        f"💬 *Запрос на переписку*\n"
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

# ===== ФУНКЦИИ ДЛЯ АДМИНА =====
def show_tasks(message):
    pending_questions = storage.get_pending_questions()
    
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
        
        bot.send_message(ADMIN_ID, question_text, parse_mode='Markdown', 
                        reply_markup=markup, disable_web_page_preview=True)

def show_active_chats(message):
    active_chats = storage.get_all_active_chats()
    
    if not active_chats:
        bot.send_message(ADMIN_ID, "💭 Нет активных чатов")
        return
    
    text = "💬 *Активные чаты:*\n\n"
    for telegram_id, chat_data in storage.cache['active_chats'].items():
        if chat_data['admin_id'] == ADMIN_ID:
            chat_limit = chat_data.get('message_limit', 350)
            text += f"👤 {chat_data['user_name']}\n"
            text += f"ID: `{telegram_id}`\n"
            text += f"Имя админа: {chat_data['admin_name']}\n"
            text += f"Лимит: {chat_limit} символов\n"
            text += f"Ссылки: {'✅ Разрешены' if chat_data.get('allow_links', True) else '❌ Запрещены'}\n\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

def show_bans(message):
    # В реальном проекте нужно сделать метод для получения забаненных пользователей
    bot.send_message(ADMIN_ID, "⚠️ Функция в разработке. Используйте команду /admin для статистики.")

def show_mutes(message):
    # В реальном проекте нужно сделать метод для получения заглушенных пользователей
    bot.send_message(ADMIN_ID, "⚠️ Функция в разработке. Используйте команду /admin для статистики.")

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
    
    # Экранируем текст вопроса
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
    
    bot.send_message(ADMIN_ID, notification, parse_mode='Markdown', 
                     reply_markup=markup, disable_web_page_preview=True)

def process_admin_answer(message, question_id):
    if not message.content_type == 'text':
        bot.send_message(ADMIN_ID, "❌ Ответ должен быть текстовым.")
        return
    
    question = storage.get_question(question_id)
    if not question:
        bot.send_message(ADMIN_ID, "❌ Вопрос не найден")
        return
    
    can_answer, reason = can_answer_question(question_id)
    if not can_answer:
        bot.send_message(ADMIN_ID, reason)
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
        
        full_message = f"{header}\n\n{escaped_answer_text}"
        bot.send_message(user_id, full_message, parse_mode='Markdown')
        
        # Обновляем статус вопроса
        storage.update_question_status(question_id, 'answered', answer_text, admin_name)
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

# ===== CALLBACK ОБРАБОТЧИК =====
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    if call.data.startswith('accept_chat_'):
        user_id = int(call.data.replace('accept_chat_', ''))
        
        user = storage.get_user(user_id)
        if not user:
            bot.answer_callback_query(call.id, "❌ Пользователь не найден")
            return
        
        # Проверяем, не в чате ли уже пользователь
        if storage.get_active_chat(user_id):
            bot.answer_callback_query(call.id, "❌ Пользователь уже в чате")
            return
        
        msg = bot.send_message(
            ADMIN_ID,
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
    
    elif call.data.startswith('mute_questions_'):
        question_id = int(call.data.replace('mute_questions_', ''))
        question = storage.get_question(question_id)
        if not question:
            bot.answer_callback_query(call.id, "❌ Вопрос не найден")
            return
        user_id = question['user_id']
        
        msg = bot.send_message(
            ADMIN_ID,
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
        
        msg = bot.send_message(
            ADMIN_ID,
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
            ADMIN_ID,
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
        bot.send_message(ADMIN_ID, "❌ Создание чата отменено.")
        
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
        bot.send_message(ADMIN_ID, "❌ Имя не может быть пустым.")
        return
    
    user = storage.get_user(user_id)
    if not user:
        bot.send_message(ADMIN_ID, "❌ Пользователь не найден.")
        return
    
    msg = bot.send_message(
        ADMIN_ID,
        f"✅ Имя сохранено: *{admin_name}*\n\n"
        f"*Разрешить отправку ссылок?*\n\n"
        f"Напишите `Да` или `Нет` (регистр не важен).\n"
        f"Если выбрать 'Нет', чат автоматически завершится при попытке отправить ссылку.\n\n"
        f"⚠️ *Если ввести что-то другое, по умолчанию будет установлено 'Да'*\n"
        f"(Или /cancel для отмена)",
        parse_mode='Markdown'
    )
    
    bot.register_next_step_handler(msg, ask_links_step, user_id, admin_name)

def ask_links_step(message, user_id, admin_name):
    if message.text == '/cancel':
        bot.send_message(ADMIN_ID, "❌ Создание чата отменено.")
        
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
        ADMIN_ID,
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
        bot.send_message(ADMIN_ID, "❌ Создание чата отменено.")
        
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
        bot.send_message(ADMIN_ID, "❌ Пользователь не найден.")
        return
    
    username = user['username'] or user['first_name']
    
    # Начинаем чат
    storage.start_chat(user_id, ADMIN_ID, username, admin_name, allow_links, limit)
    
    # Экранируем все переменные для безопасного использования в Markdown
    escaped_admin_name = escape_markdown(admin_name)
    escaped_username = escape_markdown(username)
    
    # Сообщение пользователю
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
    
    # Сообщение админу
    bot.send_message(
        ADMIN_ID,
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
    
    duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
    user = storage.get_user(user_id)
    username = user['username'] if user else f'ID: {user_id}'
    
    bot.send_message(ADMIN_ID, f"🚫 Пользователь `{user_id}` ({username}) забанен на {duration_text}.\nПричина: {reason}")
    
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

def process_mute_questions_with_reason(message, user_id):
    """Обработка мута в вопросах"""
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
    
    storage.mute_user_questions(user_id, duration_seconds, reason)
    
    duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
    user = storage.get_user(user_id)
    username = user['username'] if user else f'ID: {user_id}'
    
    bot.send_message(ADMIN_ID, f"🔇 Пользователь `{user_id}` ({username}) заглушен в вопросах на {duration_text}.\nПричина: {reason}")
    
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

def process_mute_chat_with_reason(message, user_id):
    """Обработка мута в переписке"""
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
    
    storage.mute_user_chat(user_id, duration_seconds, reason)
    
    duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
    user = storage.get_user(user_id)
    username = user['username'] if user else f'ID: {user_id}'
    
    bot.send_message(ADMIN_ID, f"🔇 Пользователь `{user_id}` ({username}) заглушен в переписке на {duration_text}.\nПричина: {reason}")
    
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

# ===== ЗАПУСК =====
if __name__ == '__main__':
    print("=" * 50)
    print(f"🤖 Бот запущен | Админ: {ADMIN_ID}")
    
    stats = storage.get_statistics()
    print(f"👥 Пользователей в БД: {stats['total_users']}")
    print(f"📨 Вопросов в БД: {stats['pending_questions'] + stats['questions_today']}")
    print(f"🚫 Активных банов: {stats['bans']}")
    print(f"🔇 Муты в вопросах: {stats['mutes_questions']}")
    print(f"🔇 Муты в переписке: {stats['mutes_chat']}")
    print(f"💬 Активных чатов: {stats['active_chats']}")
    print(f"📝 Автоочистка вопросов: каждые 24 часа")
    print("=" * 50)
    
    # Запускаем потоки
    expiration_check_thread = threading.Thread(target=check_ban_expirations, daemon=True)
    cleanup_thread = threading.Thread(target=cleanup_old_questions, daemon=True)
    
    expiration_check_thread.start()
    cleanup_thread.start()
    
    try:
        bot.polling(none_stop=True, interval=0)
    except Exception as e:
        print(f"Ошибка при запуске бота: {e}")
