import os
import telebot
from deep_translator import GoogleTranslator
from dotenv import load_dotenv  # опционально, для локальной разработки

# Загружаем переменные окружения (для локальной разработки)
load_dotenv()

# Получаем токен бота из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения!")

# Создаем экземпляр бота
bot = telebot.TeleBot(BOT_TOKEN)

# Команда /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user = message.from_user
    welcome_text = (
        f"Привет, {user.first_name}! 👋\n\n"
        "Я бот-переводчик. Просто напиши текст на русском, "
        "и я переведу его на английский!\n\n"
        "Команды:\n"
        "/start - начать работу\n"
        "/help - помощь\n"
        "/lang - изменить язык перевода"
    )
    bot.send_message(message.chat.id, welcome_text)

# Команда /help
@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = """
📚 **Как пользоваться ботом:**

1. Просто отправь мне текст на русском языке
2. Я автоматически переведу его на английский
3. Отправлю перевод обратно

Пример:
Ты пишешь: "Привет, как дела?"
Я отвечаю: "Hello, how are you?"

**Команды:**
/start - перезапустить бота
/help - показать это сообщение
/lang - изменить язык перевода

📌 **Примечание:** По умолчанию я перевожу с русского на английский.
"""
    bot.send_message(message.chat.id, help_text)

# Команда для смены языка перевода
@bot.message_handler(commands=['lang'])
def change_language(message):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    
    # Кнопки для выбора направления перевода
    btn1 = telebot.types.InlineKeyboardButton("🇷🇺 → 🇬🇧 Русский → Английский", callback_data="lang_ru_en")
    btn2 = telebot.types.InlineKeyboardButton("🇬🇧 → 🇷🇺 Английский → Русский", callback_data="lang_en_ru")
    btn3 = telebot.types.InlineKeyboardButton("🇷🇺 → 🇩🇪 Русский → Немецкий", callback_data="lang_ru_de")
    btn4 = telebot.types.InlineKeyboardButton("🇷🇺 → 🇫🇷 Русский → Французский", callback_data="lang_ru_fr")
    
    markup.add(btn1, btn2, btn3, btn4)
    
    bot.send_message(
        message.chat.id,
        "🌍 **Выберите направление перевода:**\n"
        "По умолчанию: Русский → Английский",
        reply_markup=markup
    )

# Обработчик callback-кнопок для выбора языка
@bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
def handle_language_selection(call):
    # Здесь можно сохранить выбор пользователя в базе данных или словаре
    # Для простоты просто отправляем сообщение
    lang_map = {
        'lang_ru_en': 'Русский → Английский',
        'lang_en_ru': 'Английский → Русский',
        'lang_ru_de': 'Русский → Немецкий',
        'lang_ru_fr': 'Русский → Французский'
    }
    
    selected_lang = lang_map.get(call.data, 'Русский → Английский')
    
    bot.answer_callback_query(call.id, f"Выбрано: {selected_lang}")
    bot.edit_message_text(
        f"✅ **Направление перевода изменено:**\n{selected_lang}\n\n"
        "Теперь отправьте текст для перевода.",
        call.message.chat.id,
        call.message.message_id
    )

# Функция для перевода текста
def translate_text(text: str, source_lang: str = 'ru', target_lang: str = 'en') -> str:
    try:
        translator = GoogleTranslator(source=source_lang, target=target_lang)
        translated = translator.translate(text)
        return translated
    except Exception as e:
        print(f"Translation error: {e}")
        return "❌ Ошибка перевода. Пожалуйста, попробуйте еще раз."

# Обработчик всех текстовых сообщений
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    # Пропускаем команды
    if message.text.startswith('/'):
        return
    
    # Показываем статус "печатает..."
    bot.send_chat_action(message.chat.id, 'typing')
    
    try:
        # Переводим текст (по умолчанию с русского на английский)
        translated_text = translate_text(message.text)
        
        # Формируем ответ
        response = (
            f"🇷🇺 **Оригинал:** {message.text}\n\n"
            f"🇬🇧 **Перевод:** {translated_text}\n\n"
            f"📝 Для смены языка используй /lang"
        )
        
        bot.send_message(message.chat.id, response)
    
    except Exception as e:
        print(f"Error: {e}")
        bot.send_message(
            message.chat.id,
            "❌ Произошла ошибка при переводе. Пожалуйста, попробуйте позже."
        )

# Запуск бота
if __name__ == '__main__':
    print("🤖 Бот запущен...")
    
    # Бесконечный polling
    while True:
        try:
            bot.polling(none_stop=True, interval=2, timeout=20)
        except Exception as e:
            print(f"Ошибка подключения: {e}")
            print("Повторная попытка через 5 секунд...")
            import time
            time.sleep(5)
