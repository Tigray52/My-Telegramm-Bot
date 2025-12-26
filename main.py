import telebot
import os
import json
from datetime import datetime
from telebot import types

bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))
ADMIN_ID = 6337781618

# Хранилище данных
questions = {}  # Активные вопросы: {номер: {данные}}
answered = []   # Отвеченные вопросы: [{данные}]
question_counter = 1

# Файл для сохранения истории
DATA_FILE = "bot_history.json"

# ===== ЗАГРУЗКА/СОХРАНЕНИЕ =====
def load_data():
    global questions, answered, question_counter
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            questions = data.get("questions", {})
            answered = data.get("answered", [])
            question_counter = data.get("counter", 1)
    except:
        pass

def save_data():
    data = {
        "questions": questions,
        "answered": answered,
        "counter": question_counter
    }
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

load_data()

# ===== ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =====
@bot.message_handler(commands=['start'])
def start(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📨 Задать вопрос', callback_data='ask'))
    bot.send_message(
        message.chat.id,
        f"Привет! Нажми кнопку ниже, чтобы задать вопрос.",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == 'ask')
def ask_question(call):
    msg = bot.send_message(call.message.chat.id, "Напишите ваш вопрос:")
    bot.register_next_step_handler(msg, save_question)

def save_question(message):
    global question_counter
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    
    # Сохраняем с временем
    question_data = {
        'number': question_counter,
        'user_id': message.chat.id,
        'username': username,
        'text': message.text,
        'asked_time': datetime.now().strftime("%d.%m %H:%M"),
        'answered': False,
        'answer_text': None,
        'answered_time': None
    }
    
    questions[question_counter] = question_data
    
    # Уведомление админу
    bot.send_message(
        ADMIN_ID,
        f"📨 *Новый вопрос #{question_counter}*\n"
        f"От: {username} (`{message.chat.id}`)\n"
        f"Время: {question_data['asked_time']}\n"
        f"Текст: {message.text}\n\n"
        f"Ответить: `{question_counter}. ответ`",
        parse_mode='Markdown'
    )
    
    bot.send_message(message.chat.id, f"✅ Вопрос #{question_counter} отправлен!")
    question_counter += 1
    save_data()

# ===== АДМИН-МЕНЮ =====
@bot.message_handler(commands=['admin'])
def admin_menu(message):
    if message.chat.id != ADMIN_ID:
        return
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('📋 Активные вопросы'),
        types.KeyboardButton('📊 История ответов'),
        types.KeyboardButton('🔄 Обновить')
    )
    bot.send_message(
        ADMIN_ID,
        "🛠 *Панель администратора*\nВыберите действие:",
        parse_mode='Markdown',
        reply_markup=markup
    )

@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.text in ['📋 Активные вопросы', '📊 История ответов', '🔄 Обновить'])
def handle_admin_buttons(message):
    if message.text == '📋 Активные вопросы':
        show_active_questions(message)
    elif message.text == '📊 История ответов':
        show_answered_history(message)
    elif message.text == '🔄 Обновить':
        admin_menu(message)

def show_active_questions(message):
    if not questions:
        bot.send_message(ADMIN_ID, "📭 Активных вопросов нет")
        return
    
    text = "📋 *Активные вопросы:*\n\n"
    for num, q in sorted(questions.items()):
        text += f"*{num}.* {q['username']}\n"
        text += f"   Время: {q['asked_time']}\n"
        text += f"   Текст: {q['text'][:50]}...\n"
        text += f"   Ответить: `{num}. ваш ответ`\n\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

def show_answered_history(message):
    if not answered:
        bot.send_message(ADMIN_ID, "📭 История ответов пуста")
        return
    
    text = "📊 *История ответов:*\n\n"
    for i, q in enumerate(reversed(answered[-20:]), 1):  # Последние 20
        status = "✅" if q['answered'] else "❌"
        answer_time = q['answered_time'] if q['answered_time'] else "—"
        answer_text = q['answer_text'][:50] + "..." if q['answer_text'] else "Нет ответа"
        
        text += f"{status} *Вопрос #{q['number']}*\n"
        text += f"От: {q['username']}\n"
        text += f"Задан: {q['asked_time']}\n"
        text += f"Ответ: {answer_time}\n"
        text += f"Текст: {q['text'][:50]}...\n"
        text += f"Ответил: {answer_text}\n"
        text += "━━━━━━━━━━━━━━\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

# ===== ОТВЕТЫ АДМИНА =====
@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.text and '.' in m.text)
def handle_admin_answer(message):
    text = message.text.strip()
    
    # Проверяем формат: "1. ответ"
    if text[0].isdigit() and '.' in text:
        parts = text.split('.', 1)
        
        if len(parts) == 2 and parts[0].strip().isdigit():
            num = int(parts[0].strip())
            answer_text = parts[1].strip()
            
            if num in questions:
                q = questions[num]
                answer_time = datetime.now().strftime("%d.%m %H:%M")
                
                # Обновляем данные вопроса
                q['answered'] = True
                q['answer_text'] = answer_text
                q['answered_time'] = answer_time
                
                # Перемещаем в историю
                answered.append(q.copy())
                del questions[num]
                save_data()
                
                # Отправляем ответ пользователю
                try:
                    bot.send_message(
                        q['user_id'],
                        f"📩 *Ответ администратора*\n\n"
                        f"Ваш вопрос: {q['text']}\n\n"
                        f"Ответ: {answer_text}\n"
                        f"Время ответа: {answer_time}",
                        parse_mode='Markdown'
                    )
                    user_msg = f"✅ Ответ #{num} отправлен {q['username']}"
                except:
                    user_msg = f"⚠️ Ответ #{num} сохранен, но не отправлен (пользователь заблокировал бота)"
                
                # Уведомляем админа
                bot.reply_to(message, user_msg)
                
                # Показываем обновленный список
                show_active_questions(message)
            else:
                bot.reply_to(message, f"❌ Вопрос #{num} не найден")

# ===== КОМАНДА /LIST =====
@bot.message_handler(commands=['list'])
def quick_list(message):
    if message.chat.id != ADMIN_ID:
        return
    
    if not questions:
        bot.send_message(ADMIN_ID, "📭 Активных вопросов нет")
        return
    
    text = "📋 *Быстрый список:*\n\n"
    for num, q in sorted(questions.items()):
        text += f"`{num}. ` — {q['username']}: {q['text'][:40]}...\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

# ===== ЗАПУСК =====
if __name__ == '__main__':
    print(f"🤖 Бот запущен. Админ: {ADMIN_ID}")
    print(f"📊 Активных вопросов: {len(questions)}")
    print(f"📈 Отвеченных: {len(answered)}")
    bot.polling(none_stop=True)
