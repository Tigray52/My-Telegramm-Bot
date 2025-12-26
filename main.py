import telebot
import os
from telebot import types

bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))
ADMIN_ID = 6337781618

# Хранилище вопросов в памяти (при перезапуске очищается)
questions = {}
question_counter = 1

# ======== ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ========
@bot.message_handler(commands=['start'])
def start(message):
    """Простое меню с одной кнопкой"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📨 Задать вопрос', callback_data='ask'))
    bot.send_message(
        message.chat.id,
        f"Привет! Нажми кнопку ниже, чтобы задать вопрос администратору.",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == 'ask')
def ask_question(call):
    """Просим ввести вопрос"""
    msg = bot.send_message(call.message.chat.id, "Напишите ваш вопрос:")
    bot.register_next_step_handler(msg, save_question)

def save_question(message):
    """Сохраняем вопрос и уведомляем админа"""
    global question_counter
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    
    # Сохраняем
    questions[question_counter] = {
        'user_id': message.chat.id,
        'username': username,
        'text': message.text
    }
    
    # Отправляем админу уведомление
    bot.send_message(
        ADMIN_ID,
        f"📨 *Новый вопрос #{question_counter}*\n"
        f"От: {username} (`{message.chat.id}`)\n"
        f"Текст: {message.text}\n\n"
        f"Ответить: `{question_counter}. ваш ответ`",
        parse_mode='Markdown'
    )
    
    # Подтверждение пользователю
    bot.send_message(message.chat.id, f"✅ Вопрос #{question_counter} отправлен!")
    question_counter += 1

# ======== АДМИН-МЕНЮ ========
@bot.message_handler(commands=['admin'])
def admin_menu(message):
    """Главное меню админа с двумя кнопками"""
    if message.chat.id != ADMIN_ID:
        return
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton('📋 Список вопросов', callback_data='list_questions'),
        types.InlineKeyboardButton('🔄 Обновить', callback_data='refresh')
    )
    bot.send_message(
        ADMIN_ID,
        "🛠 *Панель администратора*\nВыберите действие:",
        parse_mode='Markdown',
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data in ['list_questions', 'refresh'])
def handle_admin_buttons(call):
    """Обработка кнопок админ-меню"""
    if call.data == 'list_questions':
        show_questions_list(call.message)
    elif call.data == 'refresh':
        bot.delete_message(call.message.chat.id, call.message.message_id)
        admin_menu(call.message)
    bot.answer_callback_query(call.id)

def show_questions_list(message):
    """Показываем все вопросы в виде пронумерованного списка"""
    if not questions:
        bot.send_message(ADMIN_ID, "📭 Вопросов нет")
        return
    
    text = "📋 *Список вопросов:*\n\n"
    for num, q in sorted(questions.items()):
        text += f"*{num}.* {q['username']}: {q['text'][:40]}...\n"
    
    text += "\n✏️ *Ответить:*\n`1. ваш ответ`\n`2. ваш ответ`"
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

# ======== ОТВЕТЫ АДМИНА ========
@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.text)
def handle_admin_answer(message):
    """Админ пишет '1. ответ' или '1.ответ'"""
    text = message.text.strip()
    
    # Проверяем формат: "1. ответ"
    if '.' in text and text[0].isdigit():
        parts = text.split('.', 1)
        
        if len(parts) == 2 and parts[0].strip().isdigit():
            num = int(parts[0].strip())
            answer = parts[1].strip()
            
            if num in questions:
                q = questions[num]
                
                # Пытаемся отправить ответ
                try:
                    bot.send_message(
                        q['user_id'],
                        f"📩 *Ответ администратора на ваш вопрос #{num}:*\n{answer}",
                        parse_mode='Markdown'
                    )
                    
                    # Уведомляем админа об успехе
                    bot.reply_to(
                        message,
                        f"✅ Ответ #{num} отправлен {q['username']}"
                    )
                    
                    # Удаляем вопрос из списка
                    del questions[num]
                    
                except:
                    bot.reply_to(message, f"❌ Не удалось отправить {q['username']}")
            else:
                bot.reply_to(message, f"❌ Вопрос #{num} не найден")

# ======== ЗАПУСК ========
if __name__ == '__main__':
    print(f"🤖 Бот запущен. Админ: {ADMIN_ID}")
    bot.polling(none_stop=True)
