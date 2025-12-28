import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler, 
    ContextTypes, 
    filters
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
API_TOKEN = 'BOT_TOKEN''

# Структуры данных
waiting_queue = []
active_connections = {}

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    
    # Проверяем, не в диалоге ли уже пользователь
    if user_id in active_connections:
        keyboard = [
            [InlineKeyboardButton("❌ Завершить диалог", callback_data='stop')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Вы уже в диалоге! Используйте кнопку ниже для завершения.",
            reply_markup=reply_markup
        )
        return
    
    keyboard = [
        [InlineKeyboardButton("🔍 Найти собеседника", callback_data='search')],
        [InlineKeyboardButton("❌ Завершить диалог", callback_data='stop')],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👋 Привет! Я бот для анонимного общения.\n\n"
        "Нажми 'Найти собеседника', чтобы начать общение со случайным пользователем.\n"
        "Все сообщения полностью анонимны!",
        reply_markup=reply_markup
    )

# Обработка нажатий на кнопки
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий на inline-кнопки"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'search':
        await find_partner(update, context)
    elif query.data == 'stop':
        await stop_chat(update, context)
    elif query.data == 'help':
        await help_command(update, context)

# Поиск собеседника
async def find_partner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Поиск случайного собеседника"""
    user_id = update.effective_user.id
    
    # Проверяем, не в диалоге ли уже
    if user_id in active_connections:
        await update.callback_query.message.reply_text(
            "Вы уже в диалоге! Завершите текущий, чтобы найти нового собеседника."
        )
        return
    
    # Проверяем, не в очереди ли уже
    if user_id in waiting_queue:
        await update.callback_query.message.reply_text(
            "⏳ Вы уже в очереди поиска. Пожалуйста, подождите..."
        )
        return
    
    # Добавляем в очередь
    waiting_queue.append(user_id)
    await update.callback_query.message.reply_text(
        "🔎 Ищем собеседника... Пожалуйста, подождите."
    )
    
    # Проверяем, есть ли пара
    if len(waiting_queue) >= 2:
        user1 = waiting_queue.pop(0)
        user2 = waiting_queue.pop(0)
        
        # Создаем соединение
        active_connections[user1] = user2
        active_connections[user2] = user1
        
        # Отправляем уведомления
        await context.bot.send_message(
            user1,
            "✅ Собеседник найден! Вы можете начать общение.\n\n"
            "💡 Сообщения отправляются анонимно.\n"
            "🚫 Не передавайте личную информацию!\n"
            "❌ Нажмите 'Завершить диалог', чтобы закончить."
        )
        
        await context.bot.send_message(
            user2,
            "✅ Собеседник найден! Вы можете начать общение.\n\n"
            "💡 Сообщения отправляются анонимно.\n"
            "🚫 Не передавайте личную информацию!\n"
            "❌ Нажмите 'Завершить диалог', чтобы закончить."
        )

# Завершение диалога
async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Завершение текущего диалога"""
    user_id = update.effective_user.id
    
    # Если не в диалоге
    if user_id not in active_connections:
        # Проверяем, может быть в очереди
        if user_id in waiting_queue:
            waiting_queue.remove(user_id)
            await update.callback_query.message.reply_text(
                "🗑️ Вы удалены из очереди поиска."
            )
        else:
            await update.callback_query.message.reply_text(
                "ℹ️ Вы не в диалоге и не в очереди поиска."
            )
        return
    
    # Получаем ID собеседника
    partner_id = active_connections[user_id]
    
    # Удаляем соединение
    del active_connections[user_id]
    if partner_id in active_connections:
        del active_connections[partner_id]
    
    # Уведомляем пользователей
    await context.bot.send_message(
        user_id,
        "👋 Диалог завершен. Чтобы начать новый, нажмите 'Найти собеседника'."
    )
    
    try:
        await context.bot.send_message(
            partner_id,
            "⚠️ Ваш собеседник завершил диалог.\n\n"
            "Чтобы начать новый, нажмите 'Найти собеседника'."
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {partner_id}: {e}")

# Пересылка текстовых сообщений
async def forward_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пересылка текстовых сообщений"""
    await forward_message(update, context)

# Пересылка медиа-сообщений
async def forward_media_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пересылка медиа-сообщений (фото, видео, документы, голосовые)"""
    await forward_message(update, context)

# Основная логика пересылки
async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Основная функция пересылки сообщений"""
    user_id = update.effective_user.id
    
    # Проверяем, есть ли активный диалог
    if user_id not in active_connections:
        # Показываем меню, если пользователь не в диалоге
        keyboard = [
            [InlineKeyboardButton("🔍 Найти собеседника", callback_data='search')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "Вы не в диалоге. Нажмите кнопку ниже, чтобы найти собеседника.",
            reply_markup=reply_markup
        )
        return
    
    # Получаем ID собеседника
    partner_id = active_connections[user_id]
    
    # Пересылаем сообщение
    try:
        if update.message.text:
            # Текстовое сообщение
            await context.bot.send_message(
                partner_id,
                f"💬 {update.message.text}"
            )
        elif update.message.photo:
            # Фото
            await context.bot.send_photo(
                partner_id,
                update.message.photo[-1].file_id,
                caption=update.message.caption
            )
        elif update.message.video:
            # Видео
            await context.bot.send_video(
                partner_id,
                update.message.video.file_id,
                caption=update.message.caption
            )
        elif update.message.document:
            # Документы
            await context.bot.send_document(
                partner_id,
                update.message.document.file_id,
                caption=update.message.caption
            )
        elif update.message.voice:
            # Голосовые сообщения
            await context.bot.send_voice(
                partner_id,
                update.message.voice.file_id
            )
        elif update.message.sticker:
            # Стикеры
            await context.bot.send_sticker(
                partner_id,
                update.message.sticker.file_id
            )
        else:
            # Неподдерживаемый тип сообщения
            await update.message.reply_text(
                "❌ Этот тип сообщения не поддерживается для пересылки."
            )
            
    except Exception as e:
        logger.error(f"Ошибка при пересылке сообщения: {e}")
        await update.message.reply_text(
            "⚠️ Не удалось отправить сообщение. Возможно, собеседник заблокировал бота."
        )
        
        # Если сообщение не доставлено, завершаем диалог
        if user_id in active_connections:
            del active_connections[user_id]
        if partner_id in active_connections:
            del active_connections[partner_id]

# Команда помощи
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показ справки"""
    help_text = """
📚 *Справка по использованию бота*

*Основные функции:*
• 🔍 *Найти собеседника* – поиск случайного пользователя для общения
• 💬 *Общение* – все сообщения пересылаются анонимно
• ❌ *Завершить диалог* – закончить текущий разговор

*Поддерживаемые типы сообщений:*
✓ Текстовые сообщения
✓ Фотографии
✓ Видео
✓ Документы
✓ Голосовые сообщения
✓ Стикеры

*Важные правила:*
🚫 Не передавайте личную информацию
🚫 Не нарушайте правила Telegram
🚫 Будьте вежливы с собеседниками

*Команды:*
/start – Главное меню
/stop – Завершить диалог
/help – Эта справка

💡 Все сообщения *полностью анонимны* – мы не передаем ваши данные.
    """
    
    # Проверяем, откуда пришел запрос
    if update.callback_query:
        await update.callback_query.message.reply_text(help_text, parse_mode='Markdown')
    else:
        await update.message.reply_text(help_text, parse_mode='Markdown')

# Обработка ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик ошибок"""
    logger.error(f"Ошибка при обработке {update}: {context.error}")

def main() -> None:
    """Основная функция запуска бота"""
    # Создаем приложение
    application = Application.builder().token(API_TOKEN).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop_chat))
    application.add_handler(CommandHandler("help", help_command))
    
    # Обработчик inline-кнопок
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Обработчик текстовых сообщений (исключая команды)
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            forward_text_message
        )
    )
    
    # Обработчик медиа-сообщений
    application.add_handler(
        MessageHandler(
            filters.PHOTO | 
            filters.VIDEO | 
            filters.DOCUMENT | 
            filters.VOICE | 
            filters.Sticker.ALL,
            forward_media_message
        )
    )
    
    # Обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Запуск бота
    print("🤖 Бот запущен и готов к работе...")
    print("📱 Используйте Ctrl+C для остановки")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
