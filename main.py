import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import random

# Включим логирование
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен вашего бота
API_TOKEN = 'BOT_TOKEN'

# Структуры для хранения данных (в памяти)
# Очередь ожидания (user_id)
waiting_queue = []
# Пары собеседников {user1_id: user2_id, user2_id: user1_id}
active_connections = {}
# Для хранения истории или дополнительных данных (можно заменить на БД)
user_data = {}

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [
        [InlineKeyboardButton("🔍 Найти собеседника", callback_data='search')],
        [InlineKeyboardButton("❌ Завершить диалог", callback_data='stop')],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Если пользователь уже в диалоге, сообщим ему
    if user_id in active_connections:
        partner_id = active_connections[user_id]
        await update.message.reply_text(f"Вы уже в диалоге. Используйте кнопку 'Завершить', чтобы начать поиск заново.", reply_markup=reply_markup)
        return

    await update.message.reply_text(
        "Привет! Я бот для анонимного общения.\n"
        "Нажми 'Найти собеседника', чтобы начать.", 
        reply_markup=reply_markup
    )

# Обработка нажатий на кнопки
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if query.data == 'search':
        await find_partner(update, context)
    elif query.data == 'stop':
        await stop_chat(update, context)
    elif query.data == 'help':
        await help_command(update, context)

# Поиск собеседника
async def find_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Проверяем, не в диалоге ли уже пользователь
    if user_id in active_connections:
        await update.callback_query.message.reply_text("Вы уже в диалоге. Завершите его, чтобы найти нового собеседника.")
        return

    # Проверяем, не в очереди ли уже пользователь
    if user_id in waiting_queue:
        await update.callback_query.message.reply_text("Вы уже в очереди поиска. Пожалуйста, подождите.")
        return

    # Добавляем пользователя в очередь
    waiting_queue.append(user_id)
    await update.callback_query.message.reply_text("Ищем собеседника... Пожалуйста, подождите.")

    # Если в очереди больше 1 человека, создаём пару
    if len(waiting_queue) >= 2:
        user1 = waiting_queue.pop(0)
        user2 = waiting_queue.pop(0)

        # Создаём связь
        active_connections[user1] = user2
        active_connections[user2] = user1

        # Отправляем сообщения обоим пользователям
        await context.bot.send_message(user1, "✅ Собеседник найден! Общайтесь анонимно. Чтобы закончить, нажмите 'Завершить диалог'.")
        await context.bot.send_message(user2, "✅ Собеседник найден! Общайтесь анонимно. Чтобы закончить, нажмите 'Завершить диалог'.")

# Завершение диалога
async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in active_connections:
        # Если пользователь не в диалоге, но возможно в очереди
        if user_id in waiting_queue:
            waiting_queue.remove(user_id)
            await update.callback_query.message.reply_text("Вы удалены из очереди поиска.")
        else:
            await update.callback_query.message.reply_text("Вы не в диалоге и не в очереди.")
        return

    partner_id = active_connections[user_id]

    # Удаляем связь
    del active_connections[user_id]
    if partner_id in active_connections:
        del active_connections[partner_id]

    # Уведомляем обоих пользователей
    await context.bot.send_message(user_id, "Диалог завершён. Чтобы начать новый, нажмите 'Найти собеседника'.")
    await context.bot.send_message(partner_id, "Ваш собеседник завершил диалог. Чтобы начать новый, нажмите 'Найти собеседника'.")

# Пересылка сообщений между пользователями
async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message

    # Если пользователь в активном диалоге, пересылаем сообщение
    if user_id in active_connections:
        partner_id = active_connections[user_id]
        
        # Пересылаем текст
        if message.text:
            await context.bot.send_message(partner_id, f"👤: {message.text}")
        # Пересылаем фото (можно добавить и другие типы контента)
        elif message.photo:
            await context.bot.send_photo(partner_id, message.photo[-1].file_id, caption=message.caption)
        # Пересылаем стикеры
        elif message.sticker:
            await context.bot.send_sticker(partner_id, message.sticker.file_id)
        # Можно добавить голосовые, видео, документы и т.д.
        else:
            await context.bot.send_message(user_id, "Извините, этот тип сообщения не поддерживается для пересылки.")
    else:
        # Если пользователь не в диалоге, предлагаем найти собеседника
        await message.reply_text("Вы не в диалоге. Нажмите 'Найти собеседника', чтобы начать общение.")

# Команда помощи
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
    🤖 *Как пользоваться ботом*:
    1. Нажмите *"Найти собеседника"* для поиска случайного собеседника.
    2. После соединения пишите сообщения — они будут анонимно пересылаться.
    3. Чтобы завершить диалог, нажмите *"Завершить диалог"*.
    4. Все сообщения анонимны — не передавайте личную информацию!

    *Команды*:
    /start — Главное меню
    /stop — Завершить диалог
    /help — Эта справка
    """
    await update.callback_query.message.reply_text(help_text, parse_mode='Markdown')

# Обработка ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.warning(f"Ошибка {context.error} вызвана {update}")

def main():
    # Создаём приложение
    application = Application.builder().token(API_TOKEN).build()

    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stop", stop_chat))
    
    # Обработчик кнопок
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, forward_message))
    
    # Обработчик медиа (фото, стикеры и т.д.)
    application.add_handler(MessageHandler(filters.PHOTO | filters.STICKER, forward_message))
    
    # Обработчик ошибок
    application.add_error_handler(error_handler)

    # Запускаем бота
    print("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
