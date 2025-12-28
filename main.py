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
    def __init__(self, db_name='bot_data.db'):
        self.db_name = db_name
        self.lock = threading.Lock()
        self.init_database()
    
    def init_database(self):
        """Инициализация базы данных"""
        with self.lock:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            # Пользователи
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE,
                    username TEXT,
                    first_name TEXT,
                    joined_date TIMESTAMP,
                    last_seen TIMESTAMP,
                    questions_sent INTEGER DEFAULT 0,
                    warnings INTEGER DEFAULT 0,
                    is_banned BOOLEAN DEFAULT FALSE,
                    ban_reason TEXT,
                    ban_until TIMESTAMP,
                    is_muted BOOLEAN DEFAULT FALSE,
                    mute_reason TEXT,
                    mute_until TIMESTAMP
                )
            ''')
            
            # Вопросы
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS questions (
                    question_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    question_text TEXT,
                    masked_text TEXT,
                    url_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    admin_response TEXT,
                    admin_name TEXT,
                    created_at TIMESTAMP,
                    answered_at TIMESTAMP,
                    answer_count INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Активные чаты
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS active_chats (
                    chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER UNIQUE,
                    admin_id INTEGER,
                    user_name TEXT,
                    admin_name TEXT,
                    allow_links BOOLEAN DEFAULT TRUE,
                    message_limit INTEGER DEFAULT 350,
                    start_time TIMESTAMP,
                    last_activity TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Нарушения
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS violations (
                    violation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    message_text TEXT,
                    urls_json TEXT,
                    created_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            conn.commit()
            conn.close()
    
    # ===== ПОЛЬЗОВАТЕЛИ =====
    def get_user_by_telegram_id(self, telegram_id):
        """Получает пользователя по Telegram ID"""
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
        row = cursor.fetchone()
        
        conn.close()
        return dict(row) if row else None
    
    def create_user(self, telegram_id, username, first_name):
        """Создает нового пользователя"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        now = datetime.now()
        cursor.execute('''
            INSERT INTO users (telegram_id, username, first_name, joined_date, last_seen)
            VALUES (?, ?, ?, ?, ?)
        ''', (telegram_id, username, first_name, now, now))
        
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return user_id
    
    def update_user_last_seen(self, telegram_id):
        """Обновляет время последнего входа"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('UPDATE users SET last_seen = ? WHERE telegram_id = ?', 
                      (datetime.now(), telegram_id))
        conn.commit()
        conn.close()
    
    def increment_user_questions(self, user_id):
        """Увеличивает счетчик вопросов пользователя"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('UPDATE users SET questions_sent = questions_sent + 1 WHERE user_id = ?', 
                      (user_id,))
        conn.commit()
        conn.close()
    
    def update_user_ban(self, telegram_id, is_banned, reason=None, ban_until=None):
        """Обновляет статус бана пользователя"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE users 
            SET is_banned = ?, ban_reason = ?, ban_until = ?
            WHERE telegram_id = ?
        ''', (is_banned, reason, ban_until, telegram_id))
        
        conn.commit()
        conn.close()
    
    def update_user_mute(self, telegram_id, is_muted, reason=None, mute_until=None):
        """Обновляет статус мута пользователя"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE users 
            SET is_muted = ?, mute_reason = ?, mute_until = ?
            WHERE telegram_id = ?
        ''', (is_muted, reason, mute_until, telegram_id))
        
        conn.commit()
        conn.close()
    
    def get_all_users(self):
        """Получает всех пользователей"""
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users ORDER BY joined_date DESC')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    # ===== ВОПРОСЫ =====
    def add_question(self, user_id, question_text, masked_text, url_count):
        """Добавляет новый вопрос"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO questions (user_id, question_text, masked_text, url_count, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, question_text, masked_text, url_count, datetime.now()))
        
        question_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return question_id
    
    def get_question(self, question_id):
        """Получает вопрос по ID"""
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT q.*, u.username, u.telegram_id
            FROM questions q
            JOIN users u ON q.user_id = u.user_id
            WHERE q.question_id = ?
        ''', (question_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return self._format_question(dict(row))
        return None
    
    def get_pending_questions(self):
        """Получает все ожидающие вопросы"""
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT q.*, u.username, u.telegram_id
            FROM questions q
            JOIN users u ON q.user_id = u.user_id
            WHERE q.status = 'pending'
            ORDER BY q.created_at
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        return [self._format_question(dict(row)) for row in rows]
    
    def get_questions_table(self, limit=50):
        """Получает вопросы для табличного отображения"""
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                q.question_id,
                u.username,
                u.telegram_id,
                q.question_text,
                q.masked_text,
                q.url_count,
                q.status,
                q.created_at,
                q.answered_at,
                q.answer_count
            FROM questions q
            JOIN users u ON q.user_id = u.user_id
            ORDER BY q.created_at DESC
            LIMIT ?
        ''', (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        questions = []
        for row in rows:
            row_dict = dict(row)
            questions.append({
                'id': row_dict['question_id'],
                'username': row_dict['username'],
                'user_id': row_dict['telegram_id'],
                'text_preview': (row_dict['question_text'][:50] + '...') if len(row_dict['question_text']) > 50 else row_dict['question_text'],
                'full_text': row_dict['question_text'],
                'masked_text': row_dict['masked_text'],
                'url_count': row_dict['url_count'],
                'status': row_dict['status'],
                'created_at': row_dict['created_at'].strftime('%d.%m.%Y %H:%M') if row_dict['created_at'] else '',
                'answered_at': row_dict['answered_at'].strftime('%d.%m.%Y %H:%M') if row_dict['answered_at'] else '',
                'answer_count': row_dict['answer_count']
            })
        
        return questions
    
    def update_question_status(self, question_id, status, admin_response=None, admin_name=None):
        """Обновляет статус вопроса"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        update_data = {'status': status}
        if admin_response:
            update_data['admin_response'] = admin_response
        if admin_name:
            update_data['admin_name'] = admin_name
        if status == 'answered':
            update_data['answered_at'] = datetime.now()
        
        cursor.execute('''
            UPDATE questions 
            SET status = ?, admin_response = ?, admin_name = ?, answered_at = ?
            WHERE question_id = ?
        ''', (status, admin_response, admin_name, 
              datetime.now() if status == 'answered' else None, 
              question_id))
        
        conn.commit()
        conn.close()
    
    def increment_answer_count(self, question_id):
        """Увеличивает счетчик ответов на вопрос"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('UPDATE questions SET answer_count = answer_count + 1 WHERE question_id = ?', 
                      (question_id,))
        conn.commit()
        conn.close()
    
    def delete_questions_by_ids(self, question_ids):
        """Удаляет вопросы по списку ID"""
        if not question_ids:
            return 0
        
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        placeholders = ','.join('?' for _ in question_ids)
        cursor.execute(f'DELETE FROM questions WHERE question_id IN ({placeholders})', question_ids)
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        return deleted_count
    
    def archive_questions_by_ids(self, question_ids):
        """Архивирует вопросы"""
        if not question_ids:
            return 0
        
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        placeholders = ','.join('?' for _ in question_ids)
        cursor.execute(f'''
            UPDATE questions 
            SET status = 'archived'
            WHERE question_id IN ({placeholders})
        ''', question_ids)
        
        archived_count = cursor.rowcount
        conn.commit()
        conn.close()
        return archived_count
    
    def cleanup_old_questions(self, hours=24):
        """Очищает вопросы старше указанного времени"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        # Получаем старые вопросы для уведомлений
        cursor.execute('''
            SELECT q.question_id, u.telegram_id, u.username
            FROM questions q
            JOIN users u ON q.user_id = u.user_id
            WHERE q.status = 'pending'
            AND q.created_at < datetime('now', ?)
        ''', (f'-{hours} hours',))
        
        old_questions = cursor.fetchall()
        
        # Обновляем статус
        cursor.execute('''
            UPDATE questions 
            SET status = 'expired'
            WHERE status = 'pending'
            AND created_at < datetime('now', ?)
        ''', (f'-{hours} hours',))
        
        conn.commit()
        conn.close()
        return old_questions
    
    def _format_question(self, question_data):
        """Форматирует вопрос для совместимости"""
        return {
            'id': question_data['question_id'],
            'user_id': question_data['telegram_id'],
            'username': question_data['username'],
            'text': question_data['question_text'],
            'masked_text': question_data['masked_text'],
            'url_count': question_data['url_count'],
            'status': question_data['status'],
            'admin_response': question_data['admin_response'],
            'admin_name': question_data['admin_name'],
            'created_at': question_data['created_at'].isoformat() if question_data['created_at'] else '',
            'date': question_data['created_at'].strftime('%d.%m.%Y') if question_data['created_at'] else '',
            'time': question_data['created_at'].strftime('%H:%M') if question_data['created_at'] else '',
            'answer_count': question_data['answer_count']
        }
    
    # ===== АКТИВНЫЕ ЧАТЫ =====
    def start_chat(self, user_id, admin_id, user_name, admin_name, allow_links=True, message_limit=350):
        """Начинает новый чат"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        # Удаляем старый чат если есть
        cursor.execute('DELETE FROM active_chats WHERE user_id = ?', (user_id,))
        
        cursor.execute('''
            INSERT INTO active_chats 
            (user_id, admin_id, user_name, admin_name, allow_links, message_limit, start_time, last_activity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, admin_id, user_name, admin_name, allow_links, message_limit, 
              datetime.now(), datetime.now()))
        
        conn.commit()
        conn.close()
    
    def end_chat(self, user_id):
        """Завершает чат"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM active_chats WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
    
    def get_active_chat(self, user_id):
        """Получает активный чат пользователя"""
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM active_chats WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def get_all_active_chats(self):
        """Получает все активные чаты"""
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM active_chats')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def update_chat_activity(self, user_id):
        """Обновляет время последней активности в чате"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('UPDATE active_chats SET last_activity = ? WHERE user_id = ?', 
                      (datetime.now(), user_id))
        conn.commit()
        conn.close()
    
    # ===== НАРУШЕНИЯ =====
    def add_violation(self, user_id, message_text, urls):
        """Добавляет нарушение"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO violations (user_id, message_text, urls_json, created_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, message_text, json.dumps(urls), datetime.now()))
        
        conn.commit()
        conn.close()
    
    def get_violation(self, user_id):
        """Получает последнее нарушение пользователя"""
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT v.*, u.username
            FROM violations v
            JOIN users u ON v.user_id = u.user_id
            WHERE v.user_id = ?
            ORDER BY v.created_at DESC
            LIMIT 1
        ''', (user_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            row_dict = dict(row)
            return {
                'text': row_dict['message_text'],
                'urls': json.loads(row_dict['urls_json']) if row_dict['urls_json'] else [],
                'time': row_dict['created_at'].strftime('%H:%M') if row_dict['created_at'] else '',
                'date': row_dict['created_at'].strftime('%d.%m.%Y') if row_dict['created_at'] else '',
                'username': row_dict['username']
            }
        return None
    
    def clear_violation(self, user_id):
        """Очищает нарушения пользователя"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM violations WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
    
    # ===== СТАТИСТИКА =====
    def get_statistics(self):
        """Получает статистику"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        stats = {}
        
        # Общее количество пользователей
        cursor.execute('SELECT COUNT(*) FROM users')
        stats['total_users'] = cursor.fetchone()[0]
        
        # Активные сегодня
        cursor.execute('SELECT COUNT(*) FROM users WHERE last_seen > datetime("now", "-1 day")')
        stats['active_users_today'] = cursor.fetchone()[0]
        
        # Ожидающие вопросы
        cursor.execute('SELECT COUNT(*) FROM questions WHERE status = "pending"')
        stats['pending_questions'] = cursor.fetchone()[0]
        
        # Вопросов сегодня
        cursor.execute('SELECT COUNT(*) FROM questions WHERE created_at > datetime("now", "-1 day")')
        stats['questions_today'] = cursor.fetchone()[0]
        
        # Забаненные
        cursor.execute('SELECT COUNT(*) FROM users WHERE is_banned = 1')
        stats['banned_users'] = cursor.fetchone()[0]
        
        # Заглушенные
        cursor.execute('SELECT COUNT(*) FROM users WHERE is_muted = 1')
        stats['muted_users'] = cursor.fetchone()[0]
        
        conn.close()
        return stats

# ===== ХРАНИЛИЩЕ =====
class Storage:
    def __init__(self):
        self.db = Database()
        self.cache = {
            'questions': {},
            'active_chats': {},
            'user_cooldowns': {},
            'user_message_counts': {},
            'admin_pending_answers': {}
        }
    
    # ===== ПОЛЬЗОВАТЕЛИ =====
    def get_or_create_user(self, telegram_id, username, first_name):
        """Получает или создает пользователя"""
        user = self.db.get_user_by_telegram_id(telegram_id)
        
        if not user:
            user_id = self.db.create_user(telegram_id, username, first_name)
            user = self.db.get_user_by_telegram_id(telegram_id)
        else:
            self.db.update_user_last_seen(telegram_id)
        
        return user
    
    def is_banned(self, telegram_id):
        """Проверяет, забанен ли пользователь"""
        user = self.db.get_user_by_telegram_id(telegram_id)
        if not user or not user['is_banned']:
            return False
        
        if user['ban_until'] and user['ban_until'] < datetime.now():
            self.db.update_user_ban(telegram_id, False)
            return False
        
        return True
    
    def is_muted(self, telegram_id):
        """Проверяет, заглушен ли пользователь"""
        user = self.db.get_user_by_telegram_id(telegram_id)
        if not user or not user['is_muted']:
            return False
        
        if user['mute_until'] and user['mute_until'] < datetime.now():
            self.db.update_user_mute(telegram_id, False)
            return False
        
        return True
    
    def ban_user(self, telegram_id, duration_seconds=0, reason="Нарушение правил"):
        """Банит пользователя"""
        ban_until = None
        if duration_seconds > 0:
            ban_until = datetime.fromtimestamp(time.time() + duration_seconds)
        
        self.db.update_user_ban(telegram_id, True, reason, ban_until)
        
        # Завершаем активный чат если есть
        if self.is_user_in_chat(telegram_id):
            self.end_chat(telegram_id)
    
    def unban_user(self, telegram_id):
        """Разбанивает пользователя"""
        self.db.update_user_ban(telegram_id, False)
    
    def mute_user(self, telegram_id, duration_seconds=0, reason="Нарушение правил"):
        """Мутит пользователя"""
        mute_until = None
        if duration_seconds > 0:
            mute_until = datetime.fromtimestamp(time.time() + duration_seconds)
        
        self.db.update_user_mute(telegram_id, True, reason, mute_until)
    
    def unmute_user(self, telegram_id):
        """Размучивает пользователя"""
        self.db.update_user_mute(telegram_id, False)
    
    # ===== ВОПРОСЫ =====
    def add_question(self, telegram_id, question_text, masked_text, url_count, username):
        """Добавляет вопрос"""
        user = self.get_or_create_user(telegram_id, username, "")
        
        question_id = self.db.add_question(
            user['user_id'], 
            question_text, 
            masked_text, 
            url_count
        )
        
        self.db.increment_user_questions(user['user_id'])
        
        # Кэшируем
        self.cache['questions'][question_id] = {
            'id': question_id,
            'user_id': telegram_id,
            'username': username,
            'text': question_text,
            'masked_text': masked_text,
            'url_count': url_count,
            'status': 'pending',
            'created_at': datetime.now().isoformat(),
            'date': datetime.now().strftime('%d.%m.%Y'),
            'time': datetime.now().strftime('%H:%M')
        }
        
        return question_id
    
    def get_question(self, question_id):
        """Получает вопрос"""
        if question_id in self.cache['questions']:
            return self.cache['questions'][question_id]
        
        question = self.db.get_question(question_id)
        if question:
            self.cache['questions'][question_id] = question
        return question
    
    def get_pending_questions(self):
        """Получает ожидающие вопросы"""
        return self.db.get_pending_questions()
    
    def get_questions_table(self, limit=50):
        """Получает таблицу вопросов"""
        return self.db.get_questions_table(limit)
    
    def update_question_status(self, question_id, status, admin_response=None, admin_name=None):
        """Обновляет статус вопроса"""
        self.db.update_question_status(question_id, status, admin_response, admin_name)
        
        if question_id in self.cache['questions']:
            self.cache['questions'][question_id]['status'] = status
            if admin_response:
                self.cache['questions'][question_id]['admin_response'] = admin_response
    
    def increment_answer_count(self, question_id):
        """Увеличивает счетчик ответов"""
        self.db.increment_answer_count(question_id)
        
        if question_id in self.cache['questions']:
            if 'answer_count' not in self.cache['questions'][question_id]:
                self.cache['questions'][question_id]['answer_count'] = 0
            self.cache['questions'][question_id]['answer_count'] += 1
    
    def get_answer_count(self, question_id):
        """Получает количество ответов на вопрос"""
        question = self.get_question(question_id)
        return question.get('answer_count', 0) if question else 0
    
    def delete_questions(self, question_ids):
        """Удаляет вопросы"""
        deleted = self.db.delete_questions_by_ids(question_ids)
        
        # Очищаем кэш
        for qid in question_ids:
            if qid in self.cache['questions']:
                del self.cache['questions'][qid]
        
        return deleted
    
    def archive_questions(self, question_ids):
        """Архивирует вопросы"""
        archived = self.db.archive_questions_by_ids(question_ids)
        
        # Обновляем кэш
        for qid in question_ids:
            if qid in self.cache['questions']:
                self.cache['questions'][qid]['status'] = 'archived'
        
        return archived
    
    def can_ask_question(self, telegram_id):
        """Проверяет, может ли пользователь задать вопрос"""
        user = self.get_or_create_user(telegram_id, "", "")
        if not user:
            return False, 0
        
        # Получаем активные вопросы пользователя
        pending_questions = self.get_pending_questions()
        user_pending = [q for q in pending_questions if q['user_id'] == telegram_id]
        
        max_questions = 5
        return len(user_pending) < max_questions, len(user_pending)
    
    # ===== АКТИВНЫЕ ЧАТЫ =====
    def start_chat(self, telegram_id, chat_data):
        """Начинает чат"""
        user = self.get_or_create_user(telegram_id, chat_data['user_name'], "")
        
        self.db.start_chat(
            user['user_id'],
            chat_data['admin_id'],
            chat_data['user_name'],
            chat_data['admin_name'],
            chat_data.get('allow_links', True),
            chat_data.get('message_limit', 350)
        )
        
        self.cache['active_chats'][telegram_id] = chat_data
    
    def end_chat(self, telegram_id):
        """Завершает чат"""
        user = self.get_or_create_user(telegram_id, "", "")
        if user:
            self.db.end_chat(user['user_id'])
        
        if telegram_id in self.cache['active_chats']:
            del self.cache['active_chats'][telegram_id]
    
    def is_user_in_chat(self, telegram_id):
        """Проверяет, находится ли пользователь в чате"""
        if telegram_id in self.cache['active_chats']:
            return True
        
        user = self.get_or_create_user(telegram_id, "", "")
        if user:
            chat = self.db.get_active_chat(user['user_id'])
            if chat:
                # Восстанавливаем в кэш
                self.cache['active_chats'][telegram_id] = {
                    'admin_id': chat['admin_id'],
                    'user_name': chat['user_name'],
                    'admin_name': chat['admin_name'],
                    'allow_links': bool(chat['allow_links']),
                    'message_limit': chat['message_limit']
                }
                return True
        
        return False
    
    def get_chat_data(self, telegram_id):
        """Получает данные чата"""
        if telegram_id in self.cache['active_chats']:
            return self.cache['active_chats'][telegram_id]
        
        user = self.get_or_create_user(telegram_id, "", "")
        if user:
            chat = self.db.get_active_chat(user['user_id'])
            if chat:
                chat_data = {
                    'admin_id': chat['admin_id'],
                    'user_name': chat['user_name'],
                    'admin_name': chat['admin_name'],
                    'allow_links': bool(chat['allow_links']),
                    'message_limit': chat['message_limit']
                }
                self.cache['active_chats'][telegram_id] = chat_data
                return chat_data
        
        return None
    
    def get_all_active_chats(self):
        """Получает все активные чаты"""
        db_chats = self.db.get_all_active_chats()
        
        chats = []
        for chat in db_chats:
            user = self.db.get_user_by_telegram_id(chat['user_id'])
            if user:
                chats.append({
                    'user_id': user['telegram_id'],
                    'user_name': chat['user_name'],
                    'admin_name': chat['admin_name'],
                    'allow_links': bool(chat['allow_links']),
                    'message_limit': chat['message_limit'],
                    'start_time': chat['start_time'].strftime('%H:%M') if chat['start_time'] else ''
                })
        
        return chats
    
    # ===== НАРУШЕНИЯ =====
    def save_violation_message(self, telegram_id, text, urls):
        """Сохраняет нарушение"""
        user = self.get_or_create_user(telegram_id, "", "")
        if user:
            self.db.add_violation(user['user_id'], text, urls)
    
    def get_violation_message(self, telegram_id):
        """Получает нарушение"""
        user = self.get_or_create_user(telegram_id, "", "")
        if user:
            return self.db.get_violation(user['user_id'])
        return None
    
    def clear_violation_message(self, telegram_id):
        """Очищает нарушение"""
        user = self.get_or_create_user(telegram_id, "", "")
        if user:
            self.db.clear_violation(user['user_id'])
    
    # ===== СТАТИСТИКА =====
    def get_statistics(self):
        """Получает статистику"""
        return self.db.get_statistics()
    
    # ===== COOLDOWN =====
    def check_spam(self, telegram_id):
        """Проверяет на спам"""
        now = time.time()
        
        if telegram_id not in self.cache['user_message_counts']:
            self.cache['user_message_counts'][telegram_id] = {
                'count': 1,
                'reset_time': now + 10
            }
            return False
        
        user_data = self.cache['user_message_counts'][telegram_id]
        
        if now > user_data['reset_time']:
            user_data['count'] = 1
            user_data['reset_time'] = now + 10
            return False
        
        user_data['count'] += 1
        
        if user_data['count'] > 10:
            return True
        
        return False
    
    def check_cooldown(self, telegram_id, action_type):
        """Проверяет кд"""
        now = time.time()
        
        if telegram_id not in self.cache['user_cooldowns']:
            self.cache['user_cooldowns'][telegram_id] = {}
            return True, 0
        
        last_action = self.cache['user_cooldowns'][telegram_id].get(action_type, 0)
        
        cooldown_time = 30 if action_type == 'question' else 60
        
        if now - last_action < cooldown_time:
            remaining = int(cooldown_time - (now - last_action))
            return False, remaining
        
        return True, 0
    
    def set_cooldown(self, telegram_id, action_type):
        """Устанавливает кд"""
        if telegram_id not in self.cache['user_cooldowns']:
            self.cache['user_cooldowns'][telegram_id] = {}
        
        self.cache['user_cooldowns'][telegram_id][action_type] = time.time()
    
    # ===== АВТООЧИСТКА =====
    def cleanup_old_questions(self, hours=24):
        """Очищает старые вопросы"""
        return self.db.cleanup_old_questions(hours)

# Инициализация хранилища
storage = Storage()

# Константы
QUESTION_LIMIT = 400
MAX_ANSWERS_PER_QUESTION = 2
ANSWER_TIME_LIMIT_HOURS = 24
SPAM_LIMIT_MESSAGES = 10
SPAM_LIMIT_SECONDS = 10

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def escape_markdown(text):
    """Экранирует спецсимволы Markdown"""
    if not text:
        return text
    
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def mask_url(url):
    """Маскирует URL"""
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
        
        return original_protocol + masked_domain + path
        
    except Exception as e:
        print(f"Ошибка маскировки URL: {e}")
        return url

def find_and_mask_urls(text):
    """Находит и маскирует URL"""
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
    """Находит все URL"""
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
    """Парсит длительность"""
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
    """Форматирует длительность"""
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
    """Проверяет истекшие баны/муты"""
    while True:
        try:
            current_time = datetime.now()
            
            # Проверяем пользователей с истекшими банами
            users = storage.db.get_all_users()
            for user in users:
                if user['is_banned'] and user['ban_until'] and user['ban_until'] < current_time:
                    storage.db.update_user_ban(user['telegram_id'], False)
                    try:
                        bot.send_message(
                            user['telegram_id'],
                            f"✅ *Ваш бан истек!*\n\nВы снова можете пользоваться ботом."
                        )
                    except:
                        pass
                
                if user['is_muted'] and user['mute_until'] and user['mute_until'] < current_time:
                    storage.db.update_user_mute(user['telegram_id'], False)
                    try:
                        bot.send_message(
                            user['telegram_id'],
                            f"✅ *Ваш мут истек!*\n\nВы снова можете использовать прямую переписку."
                        )
                    except:
                        pass
            
            time.sleep(60)
        except Exception as e:
            print(f"Ошибка в check_ban_expirations: {e}")
            time.sleep(60)

def cleanup_scheduler():
    """Очищает старые вопросы и отправляет уведомления"""
    while True:
        try:
            old_questions = storage.cleanup_old_questions(24)
            
            for question_id, telegram_id, username in old_questions:
                try:
                    bot.send_message(
                        telegram_id,
                        f"⏰ *Вопрос #{question_id} не получил ответа*\n\n"
                        f"К сожалению, администратор не ответил на ваш вопрос в течение 24 часов.\n"
                        f"Вы можете задать новый вопрос через меню 📨 Задать вопрос."
                    )
                    
                    bot.send_message(
                        ADMIN_ID,
                        f"⏰ Вопрос #{question_id} от {username} автоматически закрыт (24 часа)"
                    )
                except Exception as e:
                    print(f"Ошибка уведомления: {e}")
            
            time.sleep(3600)  # Каждый час
        except Exception as e:
            print(f"Ошибка в cleanup_scheduler: {e}")
            time.sleep(300)

def is_admin(user_id):
    return user_id == ADMIN_ID

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

def parse_question_ids(ids_input):
    """Парсит строку с ID вопросов"""
    try:
        ids_input = ids_input.strip()
        
        # Специальные команды
        if ids_input == 'all-pending':
            questions = storage.get_pending_questions()
            return [q['id'] for q in questions]
        elif ids_input == 'all-answered':
            questions = storage.get_questions_table(limit=1000)
            return [q['id'] for q in questions if q['status'] == 'answered']
        elif ids_input == 'all-archived':
            questions = storage.get_questions_table(limit=1000)
            return [q['id'] for q in questions if q['status'] == 'archived']
        elif ids_input == 'all-expired':
            questions = storage.get_questions_table(limit=1000)
            return [q['id'] for q in questions if q['status'] == 'expired']
        
        # Парсинг диапазонов
        result = []
        parts = ids_input.split(',')
        
        for part in parts:
            part = part.strip()
            if '-' in part:
                start_str, end_str = part.split('-', 1)
                start = int(start_str.strip())
                end = int(end_str.strip())
                result.extend(range(start, end + 1))
            else:
                result.append(int(part))
        
        return sorted(set(result))
        
    except (ValueError, AttributeError):
        return []

# ===== КОМАНДЫ =====
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    
    # Проверка бана
    if storage.is_banned(user_id):
        user = storage.db.get_user_by_telegram_id(user_id)
        if user and user['ban_until']:
            remaining = user['ban_until'] - datetime.now()
            if remaining.total_seconds() > 0:
                ban_time = f"ещё {format_duration(int(remaining.total_seconds()))}"
            else:
                ban_time = "истёк"
        else:
            ban_time = "навсегда"
        
        bot.send_message(
            user_id, 
            f"🚫 Вы заблокированы администратором.\n"
            f"Причина: {user['ban_reason'] if user else 'Нарушение правил'}\n"
            f"Бан: {ban_time}"
        )
        return
    
    if is_admin(user_id):
        admin_panel(message)
        return
    
    # Проверка спама
    if storage.check_spam(user_id):
        storage.ban_user(user_id, 3600, "Спам (более 10 сообщений за 10 секунд)")
        bot.send_message(user_id, "🚫 Вы были заблокированы за спам на 1 час.")
        return
    
    # Создаем/обновляем пользователя
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    storage.get_or_create_user(user_id, username, message.from_user.first_name)
    
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
        "• Только текст\n"
        "• Cooldown: 30 секунд\n"
        "• Максимум 5 активных вопросов\n"
        "• /cancel - отмена\n\n"
        "*💬 Прямая переписка:*\n"
        "• Cooldown: 60 секунд\n"
        "• Админ может принять или отклонить\n"
        "• Используйте /stop в чате для завершения\n\n"
        "*💬 В чате:*\n"
        "• Только текстовые сообщения\n"
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
        "• /table - Таблица всех вопросов\n"
        "• /stats - Статистика\n\n"
        
        "*Управление вопросами:*\n"
        "• /delete [ID] - Удалить вопросы\n"
        "• /archive [ID] - Архивировать вопросы\n"
        "• /cleanup - Очистка старых вопросов\n"
        "• /full#[ID] - Показать полный текст\n\n"
        
        "*Управление пользователями:*\n"
        "• /ban [ID] [время] [причина]\n"
        "• /unban [ID]\n"
        "• /mute [ID] [время] [причина]\n"
        "• /unmute [ID]\n"
        "• /userinfo [ID] - Информация о пользователе\n\n"
        
        "*Формат /delete:*\n"
        "`/delete 1,2,3` - удалить 1,2,3\n"
        "`/delete 5-10` - удалить с 5 по 10\n"
        "`/delete all-pending` - все ожидающие\n"
        "`/delete all-answered` - все отвеченные\n\n"
        
        "*Другие команды:*\n"
        "• /stop [причина] - Завершить чат\n"
        "• /message [ID] текст - Отправить сообщение"
    )
    bot.send_message(ADMIN_ID, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    user_id = message.from_user.id
    
    if storage.is_user_in_chat(user_id):
        end_chat(user_id, "user_used_command")
        bot.send_message(user_id, "❌ Диалог завершен, так как вы использовали команду.")
        return
    
    if user_id == ADMIN_ID and user_id in storage.cache['admin_pending_answers']:
        del storage.cache['admin_pending_answers'][user_id]
        bot.send_message(ADMIN_ID, "✅ Ответ отменен.")
    
    bot.send_message(user_id, "✅ Действие отменено.")
    start_command(message)

@bot.message_handler(commands=['stop'])
def stop_command(message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        if storage.is_banned(user_id):
            return
        
        if storage.is_user_in_chat(user_id):
            end_chat(user_id, "user_stop")
            bot.send_message(user_id, "⏹ Вы завершили переписку.")
            return
        
        bot.send_message(user_id, "❌ Вы не находитесь в активной переписке.")
        return
    
    # Для админа
    active_chats = storage.get_all_active_chats()
    active_user_id = None
    for chat in active_chats:
        if chat['user_id']:
            active_user_id = chat['user_id']
            break
    
    if not active_user_id:
        bot.send_message(ADMIN_ID, "❌ Нет активных чатов")
        return
    
    parts = message.text.split(maxsplit=1)
    reason = parts[1] if len(parts) > 1 else None
    
    if reason:
        end_chat_with_reason(active_user_id, reason)
        bot.send_message(ADMIN_ID, f"✅ Чат завершен с причиной: {reason}")
    else:
        end_chat(active_user_id, "admin_stop")
        bot.send_message(ADMIN_ID, "✅ Чат завершен")

def end_chat(user_id, reason="normal"):
    """Завершает чат"""
    if storage.is_user_in_chat(user_id):
        chat_data = storage.get_chat_data(user_id)
        user_name = chat_data['user_name'] if chat_data else "Пользователь"
        
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
            bot.send_message(ADMIN_ID, f"{message_text} с {user_name}")
        except:
            pass
        
        if reason not in ["ban", "mute"] and not storage.is_banned(user_id):
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
    """Завершает чат с причиной"""
    if storage.is_user_in_chat(user_id):
        chat_data = storage.get_chat_data(user_id)
        user_name = chat_data['user_name'] if chat_data else "Пользователь"
        
        try:
            bot.send_message(ADMIN_ID, f"⏹ Чат завершен с {user_name}\nПричина: {reason}")
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
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔ У вас нет доступа к этой команде")
        return
    
    admin_panel(message)

def admin_panel(message):
    stats = storage.get_statistics()
    
    text = (
        f"👑 *Панель администратора*\n\n"
        f"📊 Статистика:\n"
        f"• Пользователей: {stats['total_users']}\n"
        f"• Активных сегодня: {stats['active_users_today']}\n"
        f"• Вопросов: {stats['pending_questions']}\n"
        f"• Чатов: {len(storage.get_all_active_chats())}\n"
        f"• Забаненных: {stats['banned_users']}\n"
        f"• Заглушенных: {stats['muted_users']}\n\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}"
    )
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📋 Задачи (/tasks)'),
        types.KeyboardButton('💬 Активные чаты'),
        types.KeyboardButton('📊 Статистика (/stats)'),
        types.KeyboardButton('📋 Таблица (/table)'),
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
        f"🟢 Активных сегодня: {stats['active_users_today']}\n"
        f"📨 Вопросов сегодня: {stats['questions_today']}\n"
        f"⏳ Ожидающих ответа: {stats['pending_questions']}\n"
        f"💬 Активных чатов: {len(storage.get_all_active_chats())}\n"
        f"🚫 Забаненных: {stats['banned_users']}\n"
        f"🔇 Заглушенных: {stats['muted_users']}\n\n"
        f"🔄 Бот запущен: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
    )
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

@bot.message_handler(commands=['table'])
def table_command(message):
    """Показывает таблицу вопросов"""
    if not is_admin(message.from_user.id):
        return
    
    questions = storage.get_questions_table(limit=30)
    
    if not questions:
        bot.send_message(ADMIN_ID, "📭 Таблица вопросов пуста")
        return
    
    text = "📋 *Таблица вопросов (последние 30):*\n\n"
    
    for i, q in enumerate(questions, 1):
        status_icons = {
            'pending': '⏳',
            'answered': '✅',
            'archived': '📁',
            'expired': '⏰'
        }
        
        icon = status_icons.get(q['status'], '❓')
        text += f"{i}. `#{q['id']}` {icon} {q['status']}\n"
        text += f"   👤 {q['username']} (`{q['user_id']}`)\n"
        text += f"   📅 {q['created_at']}\n"
        text += f"   💬 {q['text_preview']}\n"
        
        if q['url_count'] > 0:
            text += f"   🔗 {q['url_count']} ссылок\n"
        
        if q['status'] == 'answered' and q['answered_at']:
            text += f"   ⏱️ Ответ: {q['answered_at']}\n"
        
        text += "\n"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('🗑️ Удалить вопросы', callback_data='delete_questions_menu'),
        types.InlineKeyboardButton('📁 Архивировать', callback_data='archive_questions_menu'),
        types.InlineKeyboardButton('🔄 Обновить', callback_data='refresh_table')
    )
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['delete'])
def delete_command(message):
    """Удаляет вопросы"""
    if not is_admin(message.from_user.id):
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(
            ADMIN_ID,
            "🗑️ *Удаление вопросов*\n\n"
            "Используйте: `/delete 1,3,5-7,10`\n\n"
            "*Примеры:*\n"
            "• `/delete 1,2,3` - удалить 1,2,3\n"
            "• `/delete 5-10` - удалить с 5 по 10\n"
            "• `/delete 1,3,5-7` - комбинированный\n"
            "• `/delete all-pending` - все ожидающие\n"
            "• `/delete all-answered` - все отвеченные",
            parse_mode='Markdown'
        )
        return
    
    ids_input = parts[1]
    question_ids = parse_question_ids(ids_input)
    
    if not question_ids:
        bot.send_message(ADMIN_ID, "❌ Неверный формат ID")
        return
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton('✅ Да, удалить', callback_data=f'confirm_delete_{ids_input}'),
        types.InlineKeyboardButton('❌ Отмена', callback_data='cancel_delete')
    )
    
    bot.send_message(
        ADMIN_ID,
        f"⚠️ *Подтвердите удаление*\n\n"
        f"Будут удалены вопросы: `{ids_input}`\n"
        f"Всего: {len(question_ids)} вопросов\n\n"
        f"*Это действие нельзя отменить!*",
        parse_mode='Markdown',
        reply_markup=markup
    )

@bot.message_handler(commands=['archive'])
def archive_command(message):
    """Архивирует вопросы"""
    if not is_admin(message.from_user.id):
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(
            ADMIN_ID,
            "📁 *Архивация вопросов*\n\n"
            "Используйте: `/archive 1,3,5-7`\n"
            "Вопросы будут помечены как 'archived'",
            parse_mode='Markdown'
        )
        return
    
    ids_input = parts[1]
    question_ids = parse_question_ids(ids_input)
    
    if not question_ids:
        bot.send_message(ADMIN_ID, "❌ Неверный формат ID")
        return
    
    archived_count = storage.archive_questions(question_ids)
    bot.send_message(ADMIN_ID, f"✅ Заархивировано {archived_count} вопросов")

@bot.message_handler(commands=['cleanup'])
def cleanup_command(message):
    """Очистка старых вопросов"""
    if not is_admin(message.from_user.id):
        return
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton('🗑️ Удалить все отвеченные', callback_data='cleanup_answered'),
        types.InlineKeyboardButton('🗑️ Удалить все архивированные', callback_data='cleanup_archived'),
        types.InlineKeyboardButton('🗑️ Удалить все просроченные', callback_data='cleanup_expired'),
        types.InlineKeyboardButton('🗑️ Удалить все старше 7 дней', callback_data='cleanup_old'),
        types.InlineKeyboardButton('❌ Отмена', callback_data='cancel_cleanup')
    )
    
    bot.send_message(
        ADMIN_ID,
        "🧹 *Очистка базы данных*\n\n"
        "Выберите что удалить:\n\n"
        "⚠️ *Внимание:* Это действие нельзя отменить!",
        parse_mode='Markdown',
        reply_markup=markup
    )

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
    
    if storage.get_violation_message(user_id):
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
    
    storage.unban_user(user_id)
    bot.send_message(ADMIN_ID, f"✅ Пользователь `{user_id}` разбанен.")
    
    try:
        bot.send_message(user_id, "✅ Вы были разблокированы администратором.")
    except:
        pass

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
    
    storage.unmute_user(user_id)
    bot.send_message(ADMIN_ID, f"✅ Пользователь `{user_id}` разглушен.")
    
    try:
        bot.send_message(
            user_id,
            "✅ Вы были разглушены администратором.\n\n"
            "Теперь вы снова можете использовать прямую переписку."
        )
    except:
        pass

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
    
    user = storage.db.get_user_by_telegram_id(user_id)
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
    
    if ADMIN_ID in storage.cache['admin_pending_answers']:
        question_id = storage.cache['admin_pending_answers'][ADMIN_ID]
        show_full_question_text(ADMIN_ID, question_id)
        return
    
    if message.reply_to_message:
        reply_msg = message.reply_to_message
        question_id = None
        
        match = re.search(r'#(\d+)', reply_msg.text or reply_msg.caption or '')
        if match:
            question_id = int(match.group(1))
        else:
            for qid in list(storage.cache['questions'].keys()):
                question = storage.cache['questions'][qid]
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
        "• Или как ответ на вопрос",
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
    
    if admin_id in storage.cache['admin_pending_answers']:
        msg = bot.send_message(
            admin_id,
            f"Теперь введите ответ на вопрос #{question_id}:\n"
            f"Используйте [Имя Фамилия] в начале для подписи",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_admin_answer, question_id)

def show_full_violation_message(admin_id, user_id):
    violation = storage.get_violation_message(user_id)
    if not violation:
        bot.send_message(admin_id, "❌ Данные о нарушении не найдены.")
        return
    
    message_text = (
        f"👤 {violation['username']} (`{user_id}`)\n"
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
    
    if storage.is_banned(user_id):
        return
    
    if storage.check_spam(user_id):
        storage.ban_user(user_id, 3600, "Спам (более 10 сообщений за 10 секунд)")
        bot.send_message(user_id, "🚫 Вы были заблокированы за спам на 1 час.")
        return
    
    if is_admin(user_id) and message.chat.id == ADMIN_ID:
        handle_admin_actions(message)
        return
    
    if storage.is_user_in_chat(user_id):
        handle_user_in_chat(message)
        return
    
    if message.text in ['📨 Задать вопрос', '💬 Прямая переписка', 'ℹ️ Помощь']:
        handle_user_menu_buttons(message)

def handle_admin_actions(message):
    if ADMIN_ID in storage.cache['admin_pending_answers']:
        if message.content_type == 'text' and message.text.strip().lower().startswith('/full'):
            question_id = storage.cache['admin_pending_answers'][ADMIN_ID]
            show_full_question_text(ADMIN_ID, question_id)
            return
        
        question_id = storage.cache['admin_pending_answers'][ADMIN_ID]
        del storage.cache['admin_pending_answers'][ADMIN_ID]
        process_admin_answer(message, question_id)
        return
    
    if message.text in ['📋 Задачи (/tasks)', '💬 Активные чаты', '📊 Статистика (/stats)', '📋 Таблица (/table)', '🔄 Обновить']:
        if message.text == '📋 Задачи (/tasks)':
            show_tasks(message)
        elif message.text == '💬 Активные чаты':
            show_active_chats(message)
        elif message.text == '📊 Статистика (/stats)':
            stats_command(message)
        elif message.text == '📋 Таблица (/table)':
            table_command(message)
        elif message.text == '🔄 Обновить':
            admin_panel(message)
    else:
        handle_admin_to_user(message)

def handle_user_menu_buttons(message):
    user_id = message.from_user.id
    
    if message.text == '📨 Задать вопрос':
        cooldown_check, remaining = storage.check_cooldown(user_id, 'question')
        if not cooldown_check:
            bot.send_message(user_id, f"⏳ Следующий вопрос можно задать через {remaining} секунд.")
            return
        
        ask_question_start(user_id)
        
    elif message.text == '💬 Прямая переписка':
        if storage.is_muted(user_id):
            user = storage.db.get_user_by_telegram_id(user_id)
            if user and user['mute_until']:
                remaining = user['mute_until'] - datetime.now()
                if remaining.total_seconds() > 0:
                    mute_time = f"ещё {format_duration(int(remaining.total_seconds()))}"
                else:
                    mute_time = "истёк"
            else:
                mute_time = "навсегда"
            
            bot.send_message(
                user_id,
                f"🔇 *Вам запрещено использовать прямую переписку!*\n\n"
                f"Причина: {user['mute_reason'] if user else 'Нарушение правил'}\n"
                f"Мут: {mute_time}\n\n"
                f"Вы можете задавать вопросы через раздел 📨 Задать вопрос."
            )
            return
        
        cooldown_check, remaining = storage.check_cooldown(user_id, 'chat_request')
        if not cooldown_check:
            bot.send_message(user_id, f"⏳ Следующий запрос переписки можно отправить через {remaining} секунд.")
            return
        
        request_chat_flow(user_id)
        
    elif message.text == 'ℹ️ Помощь':
        show_user_help(message)

# ===== ОБРАБОТКА СООБЩЕНИЙ В ЧАТЕ =====
def handle_user_in_chat(message):
    user_id = message.from_user.id
    chat_data = storage.get_chat_data(user_id)
    
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
            storage.save_violation_message(user_id, text, urls)
            
            user_id_display = f"`{user_id}`"
            username_display = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
            
            escaped_sender = escape_markdown(sender)
            escaped_username = escape_markdown(username_display)
            
            admin_message = f"👤 *{escaped_sender}* ({escaped_username}) {user_id_display} отправил ссылку:\n\n{masked_text}"
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_user_{user_id}'),
                types.InlineKeyboardButton('🔇 Заглушить', callback_data=f'mute_user_{user_id}'),
                types.InlineKeyboardButton('*Полностью*', callback_data=f'view_violation_{user_id}')
            )
            
            bot.send_message(
                ADMIN_ID,
                admin_message,
                parse_mode='Markdown',
                reply_markup=markup,
                disable_web_page_preview=True
            )
            
            end_chat(user_id, "link_sent")
            bot.send_message(user_id, "⏹ Переписка завершена. Отправка ссылок запрещена.")
            return
        
        escaped_sender = escape_markdown(sender)
        escaped_message_text = escape_markdown(text[:500])
        
        bot.send_message(
            ADMIN_ID,
            f"👤 *{escaped_sender}:*\n{escaped_message_text}",
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
            
    except Exception as e:
        bot.send_message(user_id, f"❌ Ошибка отправки: {str(e)}")

def handle_admin_to_user(message):
    active_chats = storage.get_all_active_chats()
    active_user_id = None
    for chat in active_chats:
        if chat['user_id']:
            active_user_id = chat['user_id']
            break
    
    if not active_user_id:
        return
    
    chat_data = storage.get_chat_data(active_user_id)
    if not chat_data:
        return
    
    try:
        if message.content_type == 'text':
            escaped_admin_name = escape_markdown(chat_data['admin_name'])
            escaped_message_text = escape_markdown(message.text)
            
            bot.send_message(
                active_user_id,
                f"👨‍💼 *{escaped_admin_name} (Администратор):*\n{escaped_message_text}",
                parse_mode='Markdown'
            )
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Не удалось отправить: {str(e)}")

# ===== ФУНКЦИИ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =====
def ask_question_start(user_id):
    can_ask, active_count = storage.can_ask_question(user_id)
    if not can_ask:
        bot.send_message(
            user_id, 
            f"❌ *Превышен лимит активных вопросов!*\n\n"
            f"У вас уже {active_count}/5 активных вопросов.\n"
            f"Дождитесь ответа администратора.",
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
    
    question_id = storage.add_question(user_id, question_text, masked_text, url_count, username)
    
    confirm_text = f"✅ *Вопрос #{question_id} отправлен!*\n\nАдминистратор ответит в ближайшее время."
    bot.send_message(user_id, confirm_text, parse_mode='Markdown')
    
    notify_admin_about_question(question_id)
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📨 Задать вопрос'),
        types.KeyboardButton('💬 Прямая переписка'),
        types.KeyboardButton('ℹ️ Помощь')
    )
    bot.send_message(user_id, "Главное меню:", reply_markup=markup)

def request_chat_flow(user_id):
    user = storage.get_or_create_user(user_id, "", "")
    username = user.get('username', f"ID: {user_id}")
    
    storage.set_cooldown(user_id, 'chat_request')
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton('✅ Принять чат', callback_data=f'accept_chat_{user_id}_{username}'),
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
    active_chats = storage.get_all_active_chats()
    
    if not active_chats:
        bot.send_message(ADMIN_ID, "💭 Нет активных чатов")
        return
    
    text = "💬 *Активные чаты:*\n\n"
    for chat in active_chats:
        escaped_user_name = escape_markdown(chat['user_name'])
        escaped_admin_name = escape_markdown(chat['admin_name'])
        
        text += f"👤 {escaped_user_name}\n"
        text += f"ID: `{chat['user_id']}`\n"
        text += f"Имя админа: {escaped_admin_name}\n"
        text += f"Лимит: {chat['message_limit']} символов\n"
        text += f"Ссылки: {'✅ Разрешены' if chat['allow_links'] else '❌ Запрещены'}\n"
        text += f"Начало: {chat['start_time']}\n\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

def notify_admin_about_question(question_id):
    question = storage.get_question(question_id)
    if not question:
        return
    
    display_text = question.get('masked_text', question['text'])
    text_preview = display_text[:100] + "..." if len(display_text) > 100 else display_text
    
    can_answer, reason = can_answer_question(question_id)
    
    buttons = []
    if can_answer:
        buttons.append(types.InlineKeyboardButton('✏️ Ответить', callback_data=f'answer_{question_id}'))
    else:
        buttons.append(types.InlineKeyboardButton('✏️ Ответить ⏰', callback_data=f'answer_{question_id}'))
    
    buttons.append(types.InlineKeyboardButton('🚫 Забанить', callback_data=f'ban_{question_id}'))
    buttons.append(types.InlineKeyboardButton('🔇 Заглушить', callback_data=f'mute_{question_id}'))
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(*buttons)
    
    user_id_display = f"`{question['user_id']}`"
    escaped_question_text = escape_markdown(text_preview)
    
    notification = (
        f"📨 *Вопрос #{question_id}*\n"
        f"👤 {question['username']} ({user_id_display})\n"
        f"⏰ {question['time']} | {question['date']}"
    )
    
    if not can_answer:
        escaped_reason = escape_markdown(reason)
        notification += f"\n\n⚠️ {escaped_reason}"
    
    if question.get('url_count', 0) > 0:
        url_word = "ссылка" if question['url_count'] == 1 else "ссылки"
        notification += f"\n⚠️ *Внимание:* в сообщении присутствует {question['url_count']} {url_word}"
    
    notification += f"\n\n💬 {escaped_question_text}"
    
    if question.get('url_count', 0) > 0:
        notification += f"\n\n🔗 *Важно:* для просмотра полного текста со ссылками используйте [/full#{question_id}](#full_{question_id})"
    
    bot.send_message(ADMIN_ID, notification, parse_mode='Markdown', 
                     reply_markup=markup, disable_web_page_preview=True)

def process_admin_answer(message, question_id):
    if not storage.get_question(question_id):
        bot.send_message(ADMIN_ID, "❌ Вопрос не найден")
        return
    
    can_answer, reason = can_answer_question(question_id)
    if not can_answer:
        bot.send_message(ADMIN_ID, reason)
        return
    
    question = storage.get_question(question_id)
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
    if call.data.startswith('view_violation_'):
        user_id = int(call.data.replace('view_violation_', ''))
        show_full_violation_message(ADMIN_ID, user_id)
        bot.answer_callback_query(call.id, "Показываю полное сообщение...")
        return
    
    elif call.data.startswith('accept_chat_'):
        parts = call.data.replace('accept_chat_', '').split('_', 1)
        if len(parts) == 2:
            user_id_str = parts[0]
            username = parts[1].replace('_', ' ')
            
            if user_id_str.isdigit():
                user_id = int(user_id_str)
                
                msg = bot.send_message(
                    ADMIN_ID,
                    f"💬 *Принят запрос на переписку*\n\n"
                    f"👤 Пользователь: {username} (`{user_id}`)\n\n"
                    f"📝 *Как вас звать в этой переписке?*\n"
                    f"(Напишите /cancel для отмены)",
                    parse_mode='Markdown'
                )
                
                bot.register_next_step_handler(msg, ask_admin_name_step, user_id, username)
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
            user_id = question['user_id'] if question else None
        else:
            user_id = int(call.data.replace('ban_user_', ''))
        
        if not user_id:
            bot.answer_callback_query(call.id, "❌ Пользователь не найден")
            return
        
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
            question = storage.get_question(question_id)
            user_id = question['user_id'] if question else None
        else:
            user_id = int(call.data.replace('mute_user_', ''))
        
        if not user_id:
            bot.answer_callback_query(call.id, "❌ Пользователь не найден")
            return
        
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
        
        can_answer, reason = can_answer_question(question_id)
        if not can_answer:
            bot.answer_callback_query(call.id, reason)
            return
        
        question = storage.get_question(question_id)
        if not question:
            bot.answer_callback_query(call.id, "❌ Вопрос не найден")
            return
        
        storage.cache['admin_pending_answers'][ADMIN_ID] = question_id
        
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
    
    elif call.data == 'delete_questions_menu':
        bot.send_message(
            ADMIN_ID,
            "🗑️ *Удаление вопросов*\n\n"
            "Введите команду:\n"
            "`/delete 1,3,5` - удалить вопросы 1,3,5\n"
            "`/delete 5-10` - удалить вопросы с 5 по 10\n"
            "`/delete all-pending` - все ожидающие",
            parse_mode='Markdown'
        )
        bot.answer_callback_query(call.id)
    
    elif call.data == 'archive_questions_menu':
        bot.send_message(
            ADMIN_ID,
            "📁 *Архивация вопросов*\n\n"
            "Введите команду:\n"
            "`/archive 1,3,5` - заархивировать вопросы",
            parse_mode='Markdown'
        )
        bot.answer_callback_query(call.id)
    
    elif call.data == 'refresh_table':
        table_command(call.message)
        bot.answer_callback_query(call.id, "🔄 Таблица обновлена")
    
    elif call.data.startswith('confirm_delete_'):
        ids_input = call.data.replace('confirm_delete_', '')
        question_ids = parse_question_ids(ids_input)
        
        if not question_ids:
            bot.send_message(ADMIN_ID, "❌ Неверный формат ID")
            bot.answer_callback_query(call.id)
            return
        
        deleted_count = storage.delete_questions(question_ids)
        
        bot.send_message(
            ADMIN_ID,
            f"✅ Удалено {deleted_count} вопросов\n"
            f"ID: {ids_input}"
        )
        bot.answer_callback_query(call.id, "🗑️ Удалено!")
    
    elif call.data == 'cancel_delete':
        bot.send_message(ADMIN_ID, "❌ Удаление отменено")
        bot.answer_callback_query(call.id)
    
    elif call.data == 'cleanup_answered':
        questions = storage.get_questions_table(limit=1000)
        answered_ids = [q['id'] for q in questions if q['status'] == 'answered']
        
        if answered_ids:
            deleted = storage.delete_questions(answered_ids)
            bot.send_message(ADMIN_ID, f"✅ Удалено {deleted} отвеченных вопросов")
        else:
            bot.send_message(ADMIN_ID, "📭 Нет отвеченных вопросов для удаления")
        
        bot.answer_callback_query(call.id)
    
    elif call.data == 'cleanup_archived':
        questions = storage.get_questions_table(limit=1000)
        archived_ids = [q['id'] for q in questions if q['status'] == 'archived']
        
        if archived_ids:
            deleted = storage.delete_questions(archived_ids)
            bot.send_message(ADMIN_ID, f"✅ Удалено {deleted} архивированных вопросов")
        else:
            bot.send_message(ADMIN_ID, "📭 Нет архивированных вопросов для удаления")
        
        bot.answer_callback_query(call.id)
    
    elif call.data == 'cleanup_expired':
        questions = storage.get_questions_table(limit=1000)
        expired_ids = [q['id'] for q in questions if q['status'] == 'expired']
        
        if expired_ids:
            deleted = storage.delete_questions(expired_ids)
            bot.send_message(ADMIN_ID, f"✅ Удалено {deleted} просроченных вопросов")
        else:
            bot.send_message(ADMIN_ID, "📭 Нет просроченных вопросов для удаления")
        
        bot.answer_callback_query(call.id)
    
    elif call.data == 'cleanup_old':
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM questions 
            WHERE created_at < datetime('now', '-7 days')
        ''')
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        storage.cache['questions'] = {}
        
        bot.send_message(ADMIN_ID, f"✅ Удалено {deleted_count} вопросов старше 7 дней")
        bot.answer_callback_query(call.id)
    
    elif call.data == 'cancel_cleanup':
        bot.send_message(ADMIN_ID, "❌ Очистка отменена")
        bot.answer_callback_query(call.id)

def ask_admin_name_step(message, user_id, username):
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
    
    bot.register_next_step_handler(msg, ask_links_step, user_id, username, admin_name)

def ask_links_step(message, user_id, username, admin_name):
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
    
    bot.register_next_step_handler(msg, ask_chat_limit_step, user_id, username, admin_name, allow_links)

def ask_chat_limit_step(message, user_id, username, admin_name, allow_links):
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
    
    complete_chat_setup(user_id, username, admin_name, allow_links, limit, confirmation)

def complete_chat_setup(user_id, username, admin_name, allow_links, limit, confirmation):
    chat_data = {
        'admin_id': ADMIN_ID,
        'user_name': username,
        'admin_name': admin_name,
        'allow_links': allow_links,
        'message_limit': limit
    }
    
    storage.start_chat(user_id, chat_data)
    
    escaped_admin_name = escape_markdown(admin_name)
    escaped_username = escape_markdown(username)
    
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
    
    if storage.get_violation_message(user_id):
        storage.clear_violation_message(user_id)
    
    duration_text = "навсегда" if duration_seconds == 0 else format_duration(duration_seconds)
    user = storage.db.get_user_by_telegram_id(user_id)
    username = user['username'] if user else f'ID: {user_id}'
    
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

def process_mute_with_reason(message, user_id):
    if message.text == '/cancel':
        bot.send_message(ADMIN_ID, "❌ Заглушение отменена.")
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
    user = storage.db.get_user_by_telegram_id(user_id)
    username = user['username'] if user else f'ID: {user_id}'
    
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

# ===== ЗАПУСК =====
if __name__ == '__main__':
    print("=" * 50)
    print(f"🤖 Бот запущен | Админ: {ADMIN_ID}")
    
    stats = storage.get_statistics()
    print(f"👥 Пользователей: {stats['total_users']}")
    print(f"📨 Вопросов: {stats['pending_questions']}")
    print(f"🚫 Забаненных: {stats['banned_users']}")
    print(f"🔇 Заглушенных: {stats['muted_users']}")
    print(f"💬 Активных чатов: {len(storage.get_all_active_chats())}")
    
    # Запускаем потоки
    expiration_thread = threading.Thread(target=check_ban_expirations, daemon=True)
    cleanup_thread = threading.Thread(target=cleanup_scheduler, daemon=True)
    
    expiration_thread.start()
    cleanup_thread.start()
    
    try:
        bot.polling(none_stop=True, interval=0)
    except Exception as e:
        print(f"Ошибка при запуске бота: {e}")
