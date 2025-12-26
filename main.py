import telebot
import os
from telebot import types
import json

bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))
ADMIN_ID = 6337781618

# Хранение вопросов: {номер: {"user_id": id, "text": текст, "username": имя}}
questions = {}
question_counter = 1

# Сохранение в файл для перезагрузки
DATA_FILE = "questions_data.json"

# --- Загрузка/сохранение данных ---
def load_data():
    global questions, question_counter
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            questions = data.get("questions", {})
            # Преобразуем ключи обратно в int (json сохраняет как строки)
            questions = {int(k): v for k, v in questions.items()}
            question_counter = data.get("counter", 1)
    except FileNotFoundError:
        pass

def save_data():
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            "questions": questions,
            "counter": question_counter
        }, f, ensure_ascii=False, indent=2)

load_data()

# --- 1. Интерфейс для пользователей ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup()
    btn_contact = types.InlineKeyboardButton('📨 Написать админу', callback_data='contact')
    markup.add(btn_contact)
    
    bot.send_message(
        message.chat.id,
        f"Привет, {message.from_user.first_name}!\nНапиши свой вопрос админу:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == 'contact')
def ask_question(call):
    msg = bot.send_message(call.message.chat.id, "Напишите ваш вопрос:")
    bot.register_next_step_handler(msg, process_question)

def process_question(message):
    global question_counter
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    
    # Сохраняем вопрос
    questions[question_counter] = {
        "user_id": message.chat.id,
        "text": message.text,
        "username": username,
        "message_id": message.message_id
    }
    
    # Отправляем админу
    admin_text = (
        f"📨 *Вопрос #{question_counter}*\n"
        f"От: {username} (`{message.chat.id}`)\n"
        f"Текст: {message.text}\n\n"
        f"Ответить: `/{question_counter}. ваш ответ`"
    )
    
    bot.send_message(ADMIN_ID, admin_text, parse_mode='Markdown')
    save_data()
    
    bot.send_message(message.chat.id, f"✅ Ваш вопрос #{question_counter} отправлен!")
    question_counter += 1

# --- 2. Админская панель ---
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.chat.id != ADMIN_ID:
        return
    
    if not questions:
        bot.send_message(ADMIN_ID, "📭 Нет активных вопросов")
        return
    
    # Создаем клавиатуру с вопросами
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    
    text = "📋 *Активные вопросы:*\n\n"
    for num, q in sorted(questions.items()):
        text += f"*{num}.* {q['username']}: {q['text'][:30]}...\n"
        
        # Кнопки для каждого вопроса
        btn_reply = types.InlineKeyboardButton(f'{num} ✉️', callback_data=f'admin_reply_{num}')
        btn_del = types.InlineKeyboardButton(f'{num} ❌', callback_data=f'admin_del_{num}')
        buttons.extend([btn_reply, btn_del])
    
    # Добавляем кнопки построчно
    for i in range(0, len(buttons), 4):
        markup.add(*buttons[i:i+4])
    
    markup.add(types.InlineKeyboardButton('🔄 Обновить', callback_data='admin_refresh'))
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown', reply_markup=markup)

# --- 3. Обработка админских действий ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def handle_admin_actions(call):
    if call.data == 'admin_refresh':
        bot.delete_message(call.message.chat.id, call.message.message_id)
        admin_panel(call.message)
        return
    
    elif call.data.startswith('admin_reply_'):
        num = int(call.data.split('_')[2])
        if num in questions:
            q = questions[num]
            bot.send_message(
                ADMIN_ID,
                f"✏️ *Ответ на вопрос #{num}*\n\n"
                f"От: {q['username']}\n"
                f"Вопрос: {q['text']}\n\n"
                f"*Отправьте ответ в формате:*\n`/{num}. ваш текст ответа`",
                parse_mode='Markdown'
            )
            bot.answer_callback_query(call.id, f"Готово к ответу на вопрос #{num}")
    
    elif call.data.startswith('admin_del_'):
        num = int(call.data.split('_')[2])
        if num in questions:
            del questions[num]
            save_data()
            bot.edit_message_text(
                f"❌ Вопрос #{num} удален",
                call.message.chat.id,
                call.message.message_id,
                parse_mode='Markdown'
            )
            bot.answer_callback_query(call.id, f"Вопрос #{num} удален")
        else:
            bot.answer_callback_query(call.id, "Вопрос не найден")

# --- 4. Ответы через команды (1. текст) ---
@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.text and m.text[0].isdigit())
def handle_admin_reply(message):
    if '.' not in message.text:
        return
    
    # Парсим "1. ответ" или "/1. ответ"
    text = message.text.lstrip('/')
    if text[0].isdigit():
        parts = text.split('.', 1)
        if len(parts) == 2:
            try:
                num = int(parts[0].strip())
                reply_text = parts[1].strip()
                
                if num in questions:
                    q = questions[num]
                    
                    # Отправляем пользователю
                    user_msg = (
                        f"📩 *Ответ на ваш вопрос #{num}*\n\n"
                        f"*Ваш вопрос:* {q['text']}\n\n"
                        f"*Ответ администратора:* {reply_text}"
                    )
                    
                    try:
                        bot.send_message(q['user_id'], user_msg, parse_mode='Markdown')
                        
                        # Удаляем из списка
                        del questions[num]
                        save_data()
                        
                        # Подтверждение админу
                        bot.send_message(ADMIN_ID, f"✅ Ответ #{num} отправлен пользователю {q['username']}")
                        
                        # Обновляем панель
                        admin_panel(message)
                        
                    except Exception as e:
                        bot.send_message(ADMIN_ID, f"❌ Ошибка: не удалось отправить ответ. {str(e)}")
                else:
                    bot.send_message(ADMIN_ID, f"❌ Вопрос #{num} не найден")
                    
            except ValueError:
                bot.send_message(ADMIN_ID, "❌ Формат: `1. ваш ответ` или `/1. ваш ответ`")

# --- 5. Команда /list для быстрого просмотра ---
@bot.message_handler(commands=['list'])
def quick_list(message):
    if message.chat.id != ADMIN_ID:
        return
    
    if not questions:
        bot.send_message(ADMIN_ID, "📭 Нет активных вопросов")
        return
    
    text = "📋 *Номера активных вопросов:*\n\n"
    for num, q in sorted(questions.items()):
        text += f"`/{num}. ` — {q['username']}: {q['text'][:40]}...\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

# --- 6. Запуск ---
if __name__ == '__main__':
    print("Бот запущен! Используйте /admin для панели управления")
    bot.polling(none_stop=True)
