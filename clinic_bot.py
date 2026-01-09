import logging
import sys
import os

# Настройка кодировки для Windows
if sys.platform == 'win32':
    os.system('chcp 65001 >nul 2>&1')
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass  # Для старых версий Python

from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
import mysql.connector
from mysql.connector import Error
import asyncio
from wordpress_api import WordPressAPI, calculate_available_slots, generate_day_slots
from config import WORDPRESS_CONFIG, WORKING_HOURS, APPOINTMENT_DURATION, ADMIN_IDS, PINNED_NUMBERS_FILE
import json
from functools import wraps

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('clinic_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Константы для ConversationHandler
SELECT_DOCTOR, SELECT_DATE, SELECT_TIME, CONFIRM_BOOKING = range(4)

# РЕАЛЬНЫЕ РАБОЧИЕ ДАННЫЕ
DB_CONFIG = {
    'host': 'localhost',
    'database': 's1143023_da5on46',
    'user': 's1143023_da5on46',
    'password': 'BZ64^A1Tw*&n',
    'port': 3306,
    'charset': 'utf8mb4'
}

# РЕАЛЬНЫЙ ПРЕФИКС ТАБЛИЦ
TABLE_PREFIX = 'wp_'

BOT_TOKEN = '7376506390:AAHCIbXDPvthv7rPNcS_Lkd7CNkofRTdCv4'

# Глобальные переменные
db = None
wp_api = None

class ClinicDatabase:
    """Рабочий класс для бота клиники"""
    
    def __init__(self, config, table_prefix):
        self.config = config
        self.table_prefix = table_prefix
        self.wp_api = None # Инициализация wp_api
        
    def get_connection(self):
        """Подключение к БД"""
        try:
            connection = mysql.connector.connect(**self.config)
            return connection
        except Error as e:
            logger.error(f"Ошибка подключения: {e}")
            return None
    
    def get_doctors(self):
        """Получение списка врачей"""
        # FORCED FALLBACK: Return hardcoded list directly
        return [
                {"id": 10, "name": "Имомов Сабир", "specialty": "Лаборант", "description": ""},
                {"id": 6, "name": "Зеберг Дмитрий", "specialty": "Уролог", "description": "Врач высшей категории"},
                {"id": 8, "name": "Стасюк Лариса", "specialty": "Невролог", "description": ""},
                {"id": 7, "name": "Гафурова Нигора", "specialty": "УЗИ", "description": ""},
                {"id": 9, "name": "Адилова Надира", "specialty": "Лаборант", "description": ""},
                {"id": 2, "name": "Диярова Лола", "specialty": "Гинеколог", "description": ""}
        ]

        connection = self.get_connection()
        if not connection:
            return []
        
        try:
            cursor = connection.cursor(dictionary=True)
            
            # Используем реальную таблицу врачей
            query = f"""
                SELECT id, name, specialty, description 
                FROM {self.table_prefix}doctors 
                WHERE is_active = 1 
                ORDER BY name
            """
            
            cursor.execute(query)
            doctors = cursor.fetchall()
            
            logger.info(f"Получено {len(doctors)} врачей")
            return doctors
            
        except Error as e:
            logger.error(f"Ошибка получения врачей: {e}")
            return []
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()


    
    def create_appointment(self, user_id, doctor_id, appointment_date, appointment_time, user_name, user_phone):
        """Создание записи"""
        connection = self.get_connection()
        if not connection:
            return False
        
        try:
            cursor = connection.cursor()
            
            # Форматируем время
            if len(appointment_time) == 5:
                appointment_time = appointment_time + ":00"
            
            query = f"""
                INSERT INTO {self.table_prefix}appointments 
                (user_telegram_id, doctor_id, appointment_date, appointment_time, 
                 user_name, user_phone, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'confirmed', NOW())
            """
            
            cursor.execute(query, (user_id, doctor_id, appointment_date, 
                                  appointment_time, user_name, user_phone))
            connection.commit()
            
            logger.info(f"Запись создана: врач={doctor_id}, дата={appointment_date}")
            return True
            
        except Error as e:
            logger.error(f"Ошибка создания записи: {e}")
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    def get_all_appointments(self, limit=50):
        """Получение всех записей (для админов)"""
        connection = self.get_connection()
        if not connection:
            return []
        
        try:
            cursor = connection.cursor(dictionary=True)
            
            query = f"""
                SELECT 
                    a.id, a.user_telegram_id, a.doctor_id, a.appointment_date, a.appointment_time, 
                    a.user_name, a.user_phone, a.status, a.created_at,
                    d.name as doctor_name
                FROM {self.table_prefix}appointments a
                LEFT JOIN {self.table_prefix}doctors d ON a.doctor_id = d.id
                ORDER BY a.appointment_date DESC, a.appointment_time DESC
                LIMIT %s
            """
            
            cursor.execute(query, (limit,))
            appointments = cursor.fetchall()
            return appointments
            
        except Error as e:
            logger.error(f"Ошибка получения всех записей: {e}")
            return []
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

# Инициализация
db = ClinicDatabase(DB_CONFIG, TABLE_PREFIX)

# Инициализация WordPress API
wp_api = None
if WORDPRESS_CONFIG.get('enabled', False):
    try:
        wp_api = WordPressAPI(
            site_url=WORDPRESS_CONFIG['site_url'],
            username=WORDPRESS_CONFIG.get('username'),
            password=WORDPRESS_CONFIG.get('password'),
            api_key=WORDPRESS_CONFIG.get('api_key'),
            verify_ssl=WORDPRESS_CONFIG.get('verify_ssl', True),
            timeout=WORDPRESS_CONFIG.get('timeout', 10) # Добавлен таймаут
        )
        success, message = wp_api.test_connection()
        if success:
            logger.info(f"✅ WordPress API подключен: {message}")
        else:
            logger.warning(f"⚠️ WordPress API недоступен: {message}")
            wp_api = None
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации WordPress API: {e}")
        wp_api = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    
    # Проверяем подключение
    try:
        doctors = db.get_doctors()
        doctors_count = len(doctors)
        db_status = f"✅ База подключена ({doctors_count} врачей)"
    except Exception as e:
        logger.error(f"Ошибка при проверке подключения: {e}")
        doctors_count = 0
        db_status = "⚠️ Проблема с подключением к базе"
    
    welcome_text = (
        f"👋 Здравствуйте, {user.first_name}!\n\n"
        f"🏥 Добро пожаловать в медицинский центр Diason!\n\n"
        f"{db_status}\n\n"
        f"📋 Основные команды:\n"
        f"• /book - Запись на прием\n"
        f"• /my - Мои записи\n"
        f"• /doctors - Наши врачи\n"
        f"• /info - О клинике\n"
        f"• /help - Помощь\n"
        f"• /status - Проверка системы\n\n"
        f"📍 Мы работаем для вашего здоровья!"
    )
    
    await update.message.reply_text(welcome_text)

async def doctors_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /doctors"""
    await update.message.reply_text("👨‍⚕️ Получаю список врачей...")
    
    doctors = db.get_doctors()
    
    if not doctors:
        await update.message.reply_text(
            "❌ Не удалось получить список врачей.\n"
            "Возможно, база данных временно недоступна."
        )
        return
    
    response = "👨‍⚕️ НАШИ ВРАЧИ:\n\n"
    
    for i, doctor in enumerate(doctors, 1):
        response += f"{i}. <b>{doctor['name']}</b>\n"
        if doctor.get('specialty'):
            response += f"   📍 Специальность: {doctor['specialty']}\n"
        if doctor.get('description'):
            desc = doctor['description'][:80] + "..." if len(doctor['description']) > 80 else doctor['description']
            response += f"   📝 {desc}\n"
        response += "\n"
    
    # Если ответ слишком длинный, разбиваем на части
    if len(response) > 4096:
        parts = [response[i:i+4096] for i in range(0, len(response), 4096)]
        for part in parts:
            await update.message.reply_text(part, parse_mode='HTML')
    else:
        await update.message.reply_text(response, parse_mode='HTML')

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /info - информация о клинике"""
    info_text = (
        "🏥 <b>Медицинский центр Diason</b>\n\n"
        "Мы предлагаем полный спектр медицинских услуг:\n\n"
        "✅ Консультации специалистов\n"
        "✅ Диагностика и анализы\n"
        "✅ Ультразвуковые исследования\n"
        "✅ Физиотерапия и массаж\n"
        "✅ Профилактические осмотры\n\n"
        "<b>Контактная информация:</b>\n"
        "📍 Адрес: г. Ташкент, ул. Мирабад, 12\n"
        "📞 Телефон: +998(71) 123-45-67\n"
        "🕒 Часы работы: 9:00-18:00 (без выходных)\n"
        "📧 Email: info@diason.uz\n\n"
        "Мы заботимся о вашем здоровье!"
    )
    
    await update.message.reply_text(info_text, parse_mode='HTML')

async def my_appointments_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /my - просмотр и отмена записей (для админов - все записи)"""
    user_id = update.effective_user.id
    
    # === ЛОГИКА ДЛЯ АДМИНОВ ===
    if user_id in ADMIN_IDS:
        await update.message.reply_text("👮‍♂️ <b>Режим администратора</b>: Загружаю последние записи...", parse_mode='HTML')
        
        # Получаем записи через API плагина (все)
        appointments = wp_api.get_all_appointments(limit=20) # Limit to 20 to avoid spamming too much
        
        if not appointments:
            await update.message.reply_text("📋 Записей не найдено.")
            return

        await update.message.reply_text(f"📋 <b>Найдено {len(appointments)} записей:</b>")
        
        for apt in appointments:
            # Форматирование
            dt_str = str(apt.get('appointment_date', 'N/A'))
            tm_str = str(apt.get('appointment_time', 'N/A'))
            
            status_icon = "✅" if apt.get('status') == 'confirmed' else "❓"
            
            # Логика определения источника
            src = apt.get('source')
            if src == 'bot':
                source_display = "🤖 Бот"
            elif src == 'site':
                source_display = "🌐 Сайт"
            else:
                source_display = "🤖 Бот" if apt.get('user_telegram_id') else "🌐 Сайт"
            
            text = (
                f"{status_icon} <b>{apt.get('user_name', 'Неизвестно')}</b>\n"
                f"📞 {apt.get('user_phone', 'Нет телефона')}\n"
                f"👨‍⚕️ {apt.get('doctor_name', 'Врач удален')}\n"
                f"📅 {dt_str} в {tm_str}\n"
                f"Источник: {source_display}\n"
            )
            
            # Кнопки действий (Посетил / Не пришел)
            apt_id = apt.get('id')
            # Используем telegram_id, который вернул API (или 0)
            user_tg_id = apt.get('telegram_id') or 0
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Посетил", callback_data=f"adm_v_{apt_id}_{user_tg_id}"),
                    InlineKeyboardButton("❌ Не пришел", callback_data=f"adm_n_{apt_id}_{user_tg_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

        return

    # === ЛОГИКА ДЛЯ ОБЫЧНЫХ ПОЛЬЗОВАТЕЛЕЙ ===
    if not wp_api:
        await update.message.reply_text("❌ Система управления записями временно недоступна.")
        return

    message = await update.message.reply_text("⏳ Ищу ваши записи...")
    
    appointments = wp_api.get_patient_appointments(user_id)
    
    # Удаляем сообщение о поиске
    try:
        await message.delete()
    except Exception:
        pass
    
    
    if not appointments:
        await update.message.reply_text("📋 У вас пока нет активных записей.")
        return
        
    for apt in appointments:
        # Форматируем дату
        try:
            date_obj = datetime.strptime(apt['date'], '%Y-%m-%d')
            date_str = date_obj.strftime('%d.%m.%Y')
        except:
            date_str = apt['date']
            
        text = (
            f"🩺 <b>Запись к врачу: {apt['doctor']}</b>\n"
            f"📅 Дата: {date_str}\n"
            f"🕐 Время: {apt['time']}\n"
        )
        
        # Кнопка отмены
        keyboard = [[InlineKeyboardButton("❌ Отменить запись", callback_data=f"cancel_apt_{apt['id']}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)

async def cancel_appointment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия на кнопку отмены"""
    query = update.callback_query
    await query.answer()
    
    apt_id = query.data.split('_')[2]
    
    # Пытаемся отменить
    if wp_api and wp_api.cancel_appointment(apt_id):
        await query.edit_message_text(
            f"{query.message.text_html}\n\n"
            f"✅ <b>ЗАПИСЬ ОТМЕНЕНА</b>",
            parse_mode='HTML'
        )
    else:
        await query.answer("❌ Не удалось отменить запись. Возможно, она уже отменена или слишком поздно.", show_alert=True)

async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка кнопок админа (Посетил/Не пришел)"""
    query = update.callback_query
    await query.answer()

    if not wp_api:
        await query.edit_message_text("❌ Ошибка: API отключен.")
        return

    data = query.data
    # data format: adm_v_{id}_{tg_id} or adm_n_{id}_{tg_id}
    parts = data.split('_')
    if len(parts) < 4:
        return
        
    action_type = parts[1] # 'v' or 'n'
    apt_id = parts[2]
    user_tg_id = int(parts[3])

    if action_type == 'v':
        # Посетил -> Status 4
        success = wp_api.update_appointment_status(apt_id, 4)
        new_text = "✅ Отмечено: Посетил"
        user_msg = "🏥 <b>Спасибо за посещение нашего медицинского центра!</b>\nБудем рады видеть вас снова! Желаем крепкого здоровья! 🌟"
    else:
        # Не пришел -> Status 0 (Cancelled / No Show)
        success = wp_api.update_appointment_status(apt_id, 0)
        new_text = "❌ Отмечено: Не пришел"
        user_msg = "⚠️ <b>Вы пропустили запись.</b>\nМы отметили, что вы не пришли на прием. Если вы хотите записаться снова, используйте команду /book."

    if success:
        # Edit admin message to remove buttons and show status
        original_text = query.message.text_html
        # simple append
        await query.edit_message_text(f"{original_text}\n\n<b>{new_text}</b>", parse_mode='HTML')
        
        # Notify user if tg_id exists
        if user_tg_id > 0:
            try:
                await context.bot.send_message(chat_id=user_tg_id, text=user_msg, parse_mode='HTML')
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление пользователю {user_tg_id}: {e}")
    else:
        await query.edit_message_text(f"{query.message.text_html}\n\n❌ Ошибка обновления статуса", parse_mode='HTML')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    help_text = (
        "🆘 <b>Помощь по использованию бота</b>\n\n"
        "<b>Основные команды:</b>\n"
        "• /start - Начало работы с ботом\n"
        "• /book - Запись на прием к врачу\n"
        "• /my - Мои записи (отмена)\n"
        "• /doctors - Список наших специалистов\n"
        "• /info - Информация о клинике\n"
        "• /status - Проверка состояния системы\n"
        "• /help - Эта справка\n\n"
        "<b>Процесс записи:</b>\n"
        "1. Нажмите /book\n"
        "2. Выберите врача из списка\n"
        "3. Выберите удобную дату\n"
        "4. Выберите время приема\n"
        "5. Введите ваши данные\n\n"
        "<b>Формат данных:</b>\n"
        "ФИО: Иванов Иван Иванович\n"
        "Телефон: +998901234567\n\n"
        "<b>Техническая поддержка:</b>\n"
        "При возникновении проблем обращайтесь по телефону:\n"
        "📞 +998(71) 123-45-67"
    )
    
    await update.message.reply_text(help_text, parse_mode='HTML')


# ============================================
# АДМИНСКИЕ ФУНКЦИИ
# ============================================

def admin_required(func):
    """Декоратор для проверки прав админа"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            # Тихо игнорируем или говорим что нет прав
            await update.message.reply_text("⛔️ У вас нет прав для выполнения этой команды.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def load_pinned_numbers():
    """Загрузка закрепленных номеров"""
    if not os.path.exists(PINNED_NUMBERS_FILE):
        return []
    try:
        with open(PINNED_NUMBERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка чтения файла закрепленных номеров: {e}")
        return []

def save_pinned_numbers(numbers):
    """Сохранение закрепленных номеров"""
    try:
        os.makedirs(os.path.dirname(PINNED_NUMBERS_FILE), exist_ok=True)
        with open(PINNED_NUMBERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(numbers, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения файла закрепленных номеров: {e}")
        return False

@admin_required
async def add_pin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /add_pin <номер>"""
    if not context.args:
        await update.message.reply_text("⚠️ Использование: /add_pin +998901234567")
        return

    phone = context.args[0]
    # Простейшая очистка
    clean_phone = phone.strip()
    
    numbers = load_pinned_numbers()
    if clean_phone in numbers:
        await update.message.reply_text(f"ℹ️ Номер {clean_phone} уже в списке.")
        return
        
    numbers.append(clean_phone)
    if save_pinned_numbers(numbers):
        await update.message.reply_text(f"✅ Номер {clean_phone} успешно закреплен.")
    else:
        await update.message.reply_text("❌ Ошибка при сохранении.")

@admin_required
async def del_pin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /del_pin <номер>"""
    if not context.args:
        await update.message.reply_text("⚠️ Использование: /del_pin +998901234567")
        return

    phone = context.args[0]
    numbers = load_pinned_numbers()
    
    if phone not in numbers:
        await update.message.reply_text(f"ℹ️ Номер {phone} не найден в списке.")
        return
        
    numbers.remove(phone)
    if save_pinned_numbers(numbers):
        await update.message.reply_text(f"✅ Номер {phone} удален из закрепленных.")
    else:
        await update.message.reply_text("❌ Ошибка при сохранении.")

@admin_required
async def pinned_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /pinned - список закрепленных номеров"""
    numbers = load_pinned_numbers()
    
    if not numbers:
        await update.message.reply_text("📋 Список закрепленных номеров пуст.")
        return
        
    text = "📌 <b>Закрепленные номера:</b>\n\n"
    for i, num in enumerate(numbers, 1):
        text += f"{i}. {num}\n"
        
    await update.message.reply_text(text, parse_mode='HTML')

@admin_required
async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /list - список записей из БД"""
    await update.message.reply_text("⏳ Загружаю список записей...")
    
    try:
        appointments = db.get_all_appointments(limit=20)
        
        if not appointments:
            await update.message.reply_text("📋 Записей в базе не найдено.")
            return

        text = "📋 <b>Последние 20 записей:</b>\n\n"
        
        for apt in appointments:
            # Форматирование даты и времени
            dt_str = "N/A"
            if apt.get('appointment_date'):
                dt_str = str(apt['appointment_date'])
            
            tm_str = "N/A"    
            if apt.get('appointment_time'):
                tm_str = str(apt['appointment_time'])

            status_icon = "✅" if apt.get('status') == 'confirmed' else "❓"
            
            text += (
                f"{status_icon} <b>{apt.get('user_name', 'Неизвестно')}</b>\n"
                f"📞 {apt.get('user_phone', 'Нет телефона')}\n"
                f"👨‍⚕️ {apt.get('doctor_name', 'Врач удален')}\n"
                f"📅 {dt_str} в {tm_str}\n"
                f"────────────────\n"
            )
            
        # Разбиваем, если слишком длинное
        if len(text) > 4096:
            parts = [text[i:i+4096] for i in range(0, len(text), 4096)]
            for part in parts:
                await update.message.reply_text(part, parse_mode='HTML')
        else:
            await update.message.reply_text(text, parse_mode='HTML')
            
    except Exception as e:
        logger.error(f"Ошибка в команде list: {e}")
        await update.message.reply_text("❌ Произошла ошибка при получении списка.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status - проверка состояния системы"""
    try:
        doctors = db.get_doctors()
        doctors_count = len(doctors)
        
        connection = db.get_connection()
        if connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(f"SELECT COUNT(*) as count FROM {TABLE_PREFIX}appointments")
            appointments_count = cursor.fetchone()['count']
            cursor.close()
            connection.close()
        else:
            appointments_count = 0
        
        status_text = (
            "📊 <b>Статус системы</b>\n\n"
            f"✅ База данных: {DB_CONFIG['database']}\n"
            f"✅ Префикс таблиц: {TABLE_PREFIX}\n"
            f"👨‍⚕️ Врачей в базе: {doctors_count}\n"
            f"📅 Всего записей: {appointments_count}\n"
            f"🤖 Бот работает: Да\n\n"
            "<b>Последние 3 врача:</b>\n"
        )
        
        for i, doctor in enumerate(doctors[:3], 1):
            status_text += f"{i}. {doctor['name']} - {doctor.get('specialty', 'Специалист')}\n"
        
        if doctors_count > 3:
            status_text += f"... и еще {doctors_count - 3} врачей\n"
        
        await update.message.reply_text(status_text, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Ошибка в команде status: {e}")
        await update.message.reply_text("❌ Не удалось получить статус системы.")

async def book_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса записи - выбор врача"""
    doctors = db.get_doctors()
    
    if not doctors:
        await update.message.reply_text(
            "❌ Список врачей временно недоступен.\n"
            "Пожалуйста, попробуйте позже или свяжитесь с администрацией."
        )
        return ConversationHandler.END
    
    keyboard = []
    for doctor in doctors:
        # Обрезаем длинные имена
        name = doctor['name']
        if len(name) > 25:
            name = name[:22] + "..."
        
        specialty = doctor.get('specialty', 'Специалист')
        if len(specialty) > 20:
            specialty = specialty[:17] + "..."
        
        button_text = f"👨‍⚕️ {name} - {specialty}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"doctor_{doctor['id']}")])
    
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Выберите врача для записи:",
        reply_markup=reply_markup
    )
    
    return SELECT_DOCTOR

async def select_doctor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора врача"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("Запись отменена.")
        return ConversationHandler.END
    
    doctor_id = int(query.data.split('_')[1])
    context.user_data['doctor_id'] = doctor_id
    
    # Генерируем даты на ближайшие 7 дней
    keyboard = []
    today = datetime.now()
    
    for i in range(7):
        date = today + timedelta(days=i)
        date_str = date.strftime('%Y-%m-%d')
        display_date = date.strftime('%d.%m.%Y (%A)')
        
        # Переводим день недели на русский
        days_ru = {
            'Monday': 'Пн', 'Tuesday': 'Вт', 'Wednesday': 'Ср',
            'Thursday': 'Чт', 'Friday': 'Пт', 'Saturday': 'Сб', 'Sunday': 'Вс'
        }
        
        # Пропускаем воскресенья (Sunday = 6)
        if date.weekday() == 6:
            continue
            
        for eng, ru in days_ru.items():
            display_date = display_date.replace(eng, ru)
        
        keyboard.append([InlineKeyboardButton(display_date, callback_data=f"date_{date_str}")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_doctors")])
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "Выберите дату приёма:",
        reply_markup=reply_markup
    )
    
    return SELECT_DATE

async def select_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора даты"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("Запись отменена.")
        return ConversationHandler.END
    
    if query.data == "back_to_doctors":
        # Возврат к выбору врачей
        doctors = db.get_doctors()
        keyboard = []
        for doctor in doctors:
            button_text = f"👨‍⚕️ {doctor['name']} - {doctor.get('specialty', 'Специалист')}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"doctor_{doctor['id']}")])
        
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text("Выберите врача:", reply_markup=reply_markup)
        return SELECT_DOCTOR
    
    date = query.data.split('_')[1]
    context.user_data['date'] = date
    doctor_id = context.user_data.get('doctor_id')
    
    # Получаем занятые слоты из WordPress API
    occupied_slots = []
    if wp_api:
        try:
            occupied_slots = wp_api.get_occupied_slots(doctor_id=doctor_id, date=date)
            logger.info(f"Получены занятые слоты из WordPress: {occupied_slots}")
        except Exception as e:
            logger.error(f"Ошибка получения слотов из WordPress: {e}")
    
    # Получаем ВСЕ слоты на день
    all_slots = generate_day_slots(
        start_time=WORKING_HOURS.get('start', '09:00'),
        end_time=WORKING_HOURS.get('end', '18:00'),
        lunch_start=WORKING_HOURS.get('lunch_start', '13:00'),
        lunch_end=WORKING_HOURS.get('lunch_end', '14:00'),
        slot_duration=APPOINTMENT_DURATION
    )
    
    # Если выбранная дата - сегодня, скрываем прошедшее время
    try:
        today_str = datetime.now().strftime('%Y-%m-%d')
        if date == today_str:
            now_time = datetime.now().strftime('%H:%M')
            original_count = len(all_slots)
            all_slots = [slot for slot in all_slots if slot > now_time]
            logger.info(f"Фильтрация времени на сегодня ({date}): было {original_count}, стало {len(all_slots)}")
    except Exception as e:
        logger.error(f"Ошибка при фильтрации времени: {e}")
    
    # Создаём кнопки (по 3 в ряд)
    keyboard = []
    row = []
    

    # Если слотов нет (или все отфильтрованы)
    if not all_slots:
        message_text = f"❌ К сожалению, на {date} нет свободного времени."
        
        # Если сегодня и время прошло
        try:
            today_str = datetime.now().strftime('%Y-%m-%d')
            if date == today_str:
                now_check = datetime.now()
                end_time_str = WORKING_HOURS.get('end', '18:00')
                end_check = datetime.strptime(f"{today_str} {end_time_str}", "%Y-%m-%d %H:%M")
                
                if now_check > end_check:
                    message_text = (
                        f"❌ <b>Запись на сегодня закрыта.</b>\n\n"
                        f"Мы принимаем записи до {end_time_str}.\n"
                        f"Пожалуйста, выберите другой день."
                    )
        except Exception as e:
            logger.error(f"Ошибка проверки времени: {e}")

        await query.edit_message_text(message_text, parse_mode='HTML')
        
        # Логика возврата к выбору даты
        keyboard = []
        today = datetime.now()
        
        for i in range(7):
            date_opt = today + timedelta(days=i)
            # Пропускаем воскресенье
            if date_opt.weekday() == 6:
                continue
                
            date_str = date_opt.strftime('%Y-%m-%d')
            display_date = date_opt.strftime('%d.%m.%Y (%A)')
            
            days_ru = {
                'Monday': 'Пн', 'Tuesday': 'Вт', 'Wednesday': 'Ср',
                'Thursday': 'Чт', 'Friday': 'Пт', 'Saturday': 'Сб', 'Sunday': 'Вс'
            }
            for eng, ru in days_ru.items():
                display_date = display_date.replace(eng, ru)
            
            keyboard.append([InlineKeyboardButton(display_date, callback_data=f"date_{date_str}")])
        
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_doctors")])
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text("Выберите другую дату:", reply_markup=reply_markup)
        return SELECT_DATE

        
    for i, slot in enumerate(all_slots):
        if slot in occupied_slots:
            # Занятый слот
            row.append(InlineKeyboardButton(f"❌ {slot}", callback_data=f"busy_{slot}"))
        else:
            # Свободный слот
            row.append(InlineKeyboardButton(f"✅ {slot}", callback_data=f"time_{slot}"))
            
        if (i + 1) % 3 == 0:
            keyboard.append(row)
            row = []
    
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_dates")])
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Формируем сообщение
    available_count = len([s for s in all_slots if s not in occupied_slots])
    
    message = f"📅 Выберите время приёма на {date}:\n\n"
    message += f"✅ Свободно: {available_count}\n"
    message += f"❌ Занято: {len(occupied_slots)}\n"
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup
    )
    
    return SELECT_TIME

async def select_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора времени"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("Запись отменена.")
        return ConversationHandler.END
    
    if query.data == "back_to_dates":
        # Возврат к выбору даты
        # ... (лучше вынести в отдельную функцию, но пока дублируем логику из select_doctor, но без state transition)
        keyboard = []
        today = datetime.now()
        
        for i in range(7):
            date = today + timedelta(days=i)
            # Пропускаем воскресенье
            if date.weekday() == 6:
                continue
                
            date_str = date.strftime('%Y-%m-%d')
            display_date = date.strftime('%d.%m.%Y (%A)')
            
            days_ru = {
                'Monday': 'Пн', 'Tuesday': 'Вт', 'Wednesday': 'Ср',
                'Thursday': 'Чт', 'Friday': 'Пт', 'Saturday': 'Сб', 'Sunday': 'Вс'
            }
            for eng, ru in days_ru.items():
                display_date = display_date.replace(eng, ru)
            
            keyboard.append([InlineKeyboardButton(display_date, callback_data=f"date_{date_str}")])
        
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_doctors")])
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text("Выберите дату приёма:", reply_markup=reply_markup)
        return SELECT_DATE
    
    if query.data.startswith('busy_'):
        await query.answer("⚠️ Это время уже занято, выберите другое.", show_alert=True)
        return SELECT_TIME
    
    time = query.data.split('_')[1]
    context.user_data['time'] = time
    
    await query.edit_message_text(
        f"Отлично! Вы выбрали:\n\n"
        f"📅 Дата: {context.user_data['date']}\n"
        f"🕐 Время: {time}\n\n"
        f"Теперь отправьте ваше ФИО и номер телефона в формате:\n\n"
        f"<b>Пример:</b>\n"
        f"Иванов Иван Иванович\n"
        f"+998901234567"
    )
    
    return CONFIRM_BOOKING

async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение записи"""
    user_message = update.message.text
    lines = user_message.strip().split('\n')
    
    if len(lines) < 2:
        await update.message.reply_text(
            "❌ Пожалуйста, отправьте данные в правильном формате:\n"
            "ФИО\n"
            "Номер телефона"
        )
        return CONFIRM_BOOKING
    
    user_name = lines[0].strip()
    user_phone = lines[1].strip()
    
    # Базовая валидация номера телефона
    if not user_phone.replace('+', '').replace(' ', '').isdigit():
        await update.message.reply_text(
            "❌ Номер телефона должен содержать только цифры и знак '+'.\n"
            "Попробуйте снова:"
        )
        return CONFIRM_BOOKING
    
    
    # Создаём запись через WordPress API
    success = False
    appointment_id = None
    
    if wp_api: # Changed from db.wp_api to wp_api as per context
        success, appointment_id = wp_api.create_appointment(
            doctor_id=context.user_data['doctor_id'],
            date=context.user_data['date'],
            time=context.user_data['time'],
            patient_name=user_name,
            patient_phone=user_phone,
            telegram_id=update.effective_user.id
        )
    
    # Если API недоступен или вернул ошибку, пытаемся в локальную БД (как резерв)
    if not success:
        # Можно попробовать локально, если нужно, но пока просто логируем
        # success = db.create_appointment(...) 
        pass
        
    if success:
        await update.message.reply_text(
            f"✅ <b>Запись успешно создана!</b>\n\n"
            f"📋 <b>Ваши данные:</b>\n"
            f"👤 ФИО: {user_name}\n"
            f"📞 Телефон: {user_phone}\n"
            f"📅 Дата: {context.user_data['date']}\n"
            f"🕐 Время: {context.user_data['time']}\n\n"
            f"💡 <b>Важно:</b>\n"
            f"• Пожалуйста, приходите за 10 минут до приема\n"
            f"• При себе иметь паспорт\n"
            f"• При отмене записи сообщите заранее\n\n"
            f"🏥 <b>Ждём вас в клинике!</b>",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            "❌ Произошла ошибка при создании записи.\n"
            "Пожалуйста, попробуйте позже или свяжитесь с администрацией."
        )
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена операции"""
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Ошибка при обработке обновления: {context.error}")
    
    try:
        # Пробуем отправить сообщение об ошибке пользователю
        await update.message.reply_text(
            "❌ Произошла ошибка при обработке вашего запроса.\n"
            "Пожалуйста, попробуйте еще раз или обратитесь в поддержку."
        )
    except:
        pass

async def post_init(application: Application):
    """Настройка команд после инициализации приложения"""
    commands = [
        ("start", "🚀 Запустить бота"),
        ("book", "📝 Записаться на прием"),
        ("my", "📅 Мои записи (отмена)"),
        ("doctors", "👨‍⚕️ Наши врачи"),
        ("info", "🏥 О клинике"),
        ("help", "❓ Помощь"),
        # Admin commands are hidden from menu usually, or can be added if requested. 
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("✅ Команды бота успешно установлены")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось установить команды: {e}")

def main():
    """Запуск бота"""
    global db, wp_api # Make sure we affect the global variables used by handlers
    
    # Инициализация API
    wp_api = WordPressAPI(
        site_url=WORDPRESS_CONFIG['site_url'],
        username=WORDPRESS_CONFIG['username'],
        password=WORDPRESS_CONFIG['password'],
        api_key=WORDPRESS_CONFIG.get('api_key'),
        verify_ssl=WORDPRESS_CONFIG.get('verify_ssl', True),
        timeout=WORDPRESS_CONFIG.get('timeout', 10)
    )
    
    # Тест подключения
    success, message = wp_api.test_connection()
    if success:
        logger.info(f"✅ WordPress API подключен: {message}")
    else:
        logger.error(f"❌ Ошибка подключения к WordPress API: {message}")
        
    # Инициализация БД
    db = ClinicDatabase(DB_CONFIG, TABLE_PREFIX)
    # ВАЖНО: Передаем API в глобальный объект БД
    if db:
        db.wp_api = wp_api
        
    # Используем post_init для настройки команд
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    # Добавляем обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Обработчик разговора для записи
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('book', book_start)],
        states={
            SELECT_DOCTOR: [CallbackQueryHandler(select_doctor)],
            SELECT_DATE: [CallbackQueryHandler(select_date)],
            SELECT_TIME: [CallbackQueryHandler(select_time)],
            CONFIRM_BOOKING: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_booking)], # type: ignore
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("doctors", doctors_command))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("my", my_appointments_command))
    application.add_handler(CommandHandler("add_pin", add_pin_command))
    application.add_handler(CommandHandler("del_pin", del_pin_command))
    application.add_handler(CommandHandler("pinned", pinned_command))
    application.add_handler(CommandHandler("list", list_command)) # New command
    application.add_handler(CallbackQueryHandler(cancel_appointment_callback, pattern="^cancel_apt_")) 
    application.add_handler(CallbackQueryHandler(handle_admin_action, pattern="^adm_")) # Admin actions handlers
    application.add_handler(conv_handler)
    
    # Запускаем бота
    logger.info("🤖 Бот запущен и готов к работе!")
    print("\n" + "="*60)
    print("🏥 БОТ ДЛЯ ЗАПИСИ В КЛИНИКУ")
    print("="*60)
    print(f"База данных: {DB_CONFIG['database']}")
    print(f"Префикс таблиц: {TABLE_PREFIX}")
    print(f"Токен бота: {'*' * 20}")
    print("="*60)
    print("Бот запущен. Нажмите Ctrl+C для остановки.")
    print("="*60)
    
    # ФИКС ДЛЯ PYTHON 3.14: Явно создаем цикл событий, если его нет
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    # Run polling
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()