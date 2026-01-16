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
from config import WORDPRESS_CONFIG, WORKING_HOURS, DOCTOR_SCHEDULES, APPOINTMENT_DURATION, ADMIN_IDS, PINNED_NUMBERS_FILE, DB_CONFIG, TABLE_PREFIX, BOT_TOKEN
try:
    from config import CLINIC_INFO
except ImportError:
    # Fallback if config.py is old
    CLINIC_INFO = {
        "address": "г. Ташкент",
        "phone": "+998(55) 516 11 00",
        "working_hours": "09:00-15:00",
        "email": "diason2new@gmail.com"
    }
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

async def run_sync(func, *args, **kwargs):
    """Запуск синхронной функции в отдельном потоке"""
    loop = asyncio.get_running_loop()
    from functools import partial
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))

# Константы для ConversationHandler
SELECT_DOCTOR, SELECT_DATE, SELECT_TIME, CONFIRM_BOOKING = range(4)

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
        connection = self.get_connection()
        if not connection:
            logger.warning("Нет подключения к БД, используем резервный список врачей")
            return self._get_fallback_doctors()
        
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
            
            if not doctors:
                logger.info("Список врачей из БД пуст, используем резервный список")
                return self._get_fallback_doctors()

            logger.info(f"Получено {len(doctors)} врачей")
            return doctors
            
        except Error as e:
            logger.error(f"Ошибка получения врачей: {e}")
            return self._get_fallback_doctors()
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    def _get_fallback_doctors(self):
        """Резервный список врачей"""
        return [
            {"id": 10, "name": "Имомов Сабир", "specialty": "Лаборант", "description": ""},
            {"id": 6, "name": "Зеберг Дмитрий", "specialty": "Уролог", "description": "Врач высшей категории"},
            {"id": 8, "name": "Стасюк Лариса", "specialty": "Невролог", "description": ""},
            {"id": 7, "name": "Гафурова Нигора", "specialty": "УЗИ", "description": ""},
            {"id": 9, "name": "Адилова Надира", "specialty": "Лаборант", "description": ""},
            {"id": 2, "name": "Диярова Лола", "specialty": "Гинеколог", "description": ""}
        ]


    
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

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для получения ID пользователя"""
    user_id = update.effective_user.id
    is_admin = user_id in ADMIN_IDS
    status = "АДМИН 👮‍♂️" if is_admin else "ПОЛЬЗОВАТЕЛЬ 👤"
    
    msg = f"🆔 Ваш ID: `{user_id}`\nСтатус: {status}\nАдминов в списке: {len(ADMIN_IDS)}"
    if not is_admin:
        msg += "\n(Если вы добавили ID, перезагрузите бота)"
        
    await update.message.reply_text(msg, parse_mode='Markdown')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    
    # Проверяем подключение
    try:
        doctors = await run_sync(db.get_doctors)
        doctors_count = len(doctors)
    except Exception as e:
        logger.error(f"Ошибка при проверке подключения: {e}")
        doctors_count = 0
    
    # Получаем часы работы
    work_start = WORKING_HOURS.get('start', '09:00')
    work_end = WORKING_HOURS.get('end', '18:00')
    
    welcome_text = (
        f"👋 Здравствуйте, <b>{user.first_name}</b>!\n\n"
        f"🏥 Добро пожаловать в <b>медицинский центр Diason</b>!\n\n"
        f"🤖 <b>Я помогу вам:</b>\n"
        f"• 📅 Записаться на прием к врачу\n"
        f"• 📋 Посмотреть ваши записи\n"
        f"• 👨‍⚕️ Узнать о наших специалистах\n"
        f"• ℹ️ Получить информацию о клинике\n\n"
        f"⏰ <b>Часы работы:</b> {work_start} - {work_end}\n"
        f"👨‍⚕️ <b>Врачей в базе:</b> {doctors_count}\n\n"
        f"Выберите действие из меню ниже 👇"
    )
    
    # Создаем главное меню с кнопками
    from telegram import ReplyKeyboardMarkup, KeyboardButton
    
    keyboard = []
    
    # Сначала добавляем админскую кнопку, если есть права
    is_admin = user.id in ADMIN_IDS
    logger.info(f"Start command: User {user.id} ({user.first_name}). Is Admin: {is_admin}. Admin list len: {len(ADMIN_IDS)}")
    
    if is_admin:
        keyboard.append([KeyboardButton("👮‍♂️ Админ панель")])
        
    # Добавляем основные кнопки
    keyboard.extend([
        [KeyboardButton("📅 Записаться на прием")],
        [KeyboardButton("📋 Мои записи"), KeyboardButton("👨‍⚕️ Наши врачи")],
        [KeyboardButton("ℹ️ О клинике"), KeyboardButton("📞 Контакты")],
        [KeyboardButton("❓ Помощь")]
    ])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='HTML')



async def doctors_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /doctors"""
    # await update.message.reply_text("👨‍⚕️ Получаю список врачей...") # Removed to reduce noise
    
    doctors = await run_sync(db.get_doctors)
    
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
        f"<b>Контактная информация:</b>\n"
        f"📍 Адрес: {CLINIC_INFO['address']}\n"
        f"📞 Телефон: {CLINIC_INFO['phone']}\n"
        f"🕒 Часы работы: {CLINIC_INFO['working_hours']}\n"
        f"📧 Email: {CLINIC_INFO['email']}\n\n"
        "Мы заботимся о вашем здоровье!"
    )
    
    await update.message.reply_text(info_text, parse_mode='HTML')


async def contacts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для отображения контактов клиники"""
    # Получаем часы работы
    work_start = WORKING_HOURS.get('start', '09:00')
    work_end = WORKING_HOURS.get('end', '18:00')
    lunch_start = WORKING_HOURS.get('lunch_start', '13:00')
    lunch_end = WORKING_HOURS.get('lunch_end', '14:00')
    
    
    lunch_str = ""
    if lunch_start != "00:00" and lunch_end != "00:00":
        lunch_str = f"   Обед: {lunch_start} - {lunch_end}\n"
    elif lunch_start == lunch_end: # Если начало и конец совпадают (например "13:00" но мы так не пишем), или оба 00:00
        lunch_str = "   Без обеда\n" if lunch_start == "00:00" else "" # Или просто не выводим
        # В данном случае, если в конфиге 00:00, лучше просто не писать строку про обед, или написать "Без перерыва"
        if lunch_start == "00:00":
             lunch_str = "   Без перерыва\n"

    from config import CLINIC_INFO
    
    contacts_text = (
        "📞 <b>Контактная информация</b>\n\n"
        f"🏥 <b>{CLINIC_INFO['name']}</b>\n\n"
        f"📱 <b>Телефон:</b> {CLINIC_INFO['phone']}\n"
        f"📧 <b>Email:</b> {CLINIC_INFO['email']}\n"
        f"📍 <b>Адрес:</b> {CLINIC_INFO['address']}\n\n"
        "⏰ <b>Часы работы:</b>\n"
        f"   Пн-Сб: {work_start} - {work_end}\n"
        f"{lunch_str}"
        "   Вс: Выходной\n\n"
        "🚗 <b>Как добраться:</b>\n"
        "   Метро: станция Буюк Ипак Йули\n"
        "   Ориентир: гостиница Саёхат\n\n"
        "💬 Вы также можете записаться через этого бота!\n"
        "Нажмите \"📅 Записаться на прием\""
    )
    
    await update.message.reply_text(contacts_text, parse_mode='HTML')


async def my_appointments_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /my - просмотр и отмена записей (для админов - все записи)"""
    user_id = update.effective_user.id
    
    # === ЛОГИКА ДЛЯ ВСЕХ ПОЛЬЗОВАТЕЛЕЙ ===

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
    if wp_api and await run_sync(wp_api.cancel_appointment, apt_id):
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
    
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    if not wp_api:
        await query.answer("❌ API отключен", show_alert=True)
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
        success = await run_sync(wp_api.update_appointment_status, apt_id, 4)
        action_text = "✅ Посетил"
        user_msg = "🏥 <b>Спасибо за посещение нашего медицинского центра!</b>\nБудем рады видеть вас снова! Желаем крепкого здоровья! 🌟"
    else:
        # Не пришел -> Status 5 (No Show)
        success = await run_sync(wp_api.update_appointment_status, apt_id, 5)
        action_text = "⛔ Не пришел"
        user_msg = "⚠️ <b>Вы пропустили запись.</b>\nМы отметили, что вы не пришли на прием. Если вы хотите записаться снова, используйте команду /book."

    if not success:
        await query.answer("❌ Ошибка обновления статуса", show_alert=True)
        return
    
    # Уведомляем пользователя
    if user_tg_id > 0:
        try:
            await context.bot.send_message(chat_id=user_tg_id, text=user_msg, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю {user_tg_id}: {e}")
    
    # Показываем уведомление админу
    await query.answer(f"{action_text} - статус обновлен!", show_alert=False)
    
    # Получаем текущий фильтр
    current_filter = context.user_data.get('admin_filter', 'all')
    
    # Получаем обновленный список записей
    appointments = wp_api.get_filtered_appointments(limit=50, status_filter=current_filter)
    
    # Определяем название фильтра
    filter_names = {
        'all': 'Все записи',
        'confirmed': 'Подтвержденные',
        'visited': 'Посетили',
        'noshow': 'Не пришли'
    }
    filter_display = filter_names.get(current_filter, 'Все записи')
    
    # Формируем обновленное сообщение
    message_text = f"👮‍♂️ <b>Режим администратора</b>\n📋 Фильтр: <b>{filter_display}</b>\n\n"
    
    if not appointments:
        message_text += "📭 Записей не найдено"
    else:
        message_text += f"<b>Найдено записей: {len(appointments)}</b>\n"
        message_text += "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for i, apt in enumerate(appointments[:10], 1):
            dt_str = str(apt.get('appointment_date', 'N/A'))
            tm_str = str(apt.get('appointment_time', 'N/A'))[:5]
            
            raw_status = apt.get('status')
            if raw_status == 'confirmed' or raw_status == 'pending':
                status_icon = "🔵"
                status_text = "Ожидает"
            elif raw_status == 'visited':
                status_icon = "✅"
                status_text = "Посетил"
            elif raw_status == 'noshow':
                status_icon = "⛔"
                status_text = "Не пришел"
            else:
                status_icon = "❓"
                status_text = "Неизвестно"
            
            src = apt.get('source')
            if src == 'bot' or (not src and apt.get('user_telegram_id')):
                source_icon = "🤖"
            else:
                source_icon = "🌐"
            
            message_text += (
                f"{i}. {status_icon} <b>{apt.get('user_name', 'Неизвестно')}</b>\n"
                f"   📞 {apt.get('user_phone', 'Нет')}\n"
                f"   👨‍⚕️ {apt.get('doctor_name', 'Врач удален')}\n"
                f"   📅 {dt_str} | 🕐 {tm_str}\n"
                f"   {source_icon} {status_text}\n\n"
            )
        
        if len(appointments) > 10:
            message_text += f"... и еще {len(appointments) - 10} записей\n\n"
    
    # Создаем кнопки фильтров
    filter_keyboard = [
        [
            InlineKeyboardButton("📋 Все" if current_filter == 'all' else "Все", callback_data="admin_filter_all"),
            InlineKeyboardButton("🔵 Ожидают" if current_filter == 'confirmed' else "Ожидают", callback_data="admin_filter_confirmed"),
        ],
        [
            InlineKeyboardButton("✅ Посетили" if current_filter == 'visited' else "Посетили", callback_data="admin_filter_visited"),
            InlineKeyboardButton("⛔ Не пришли" if current_filter == 'noshow' else "Не пришли", callback_data="admin_filter_noshow"),
        ],
        [
            InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
            InlineKeyboardButton("📊 Экспорт в Excel", callback_data="admin_export_excel")
        ]
    ]
    
    # Добавляем кнопки действий для подтвержденных записей
    if current_filter in ['all', 'confirmed']:
        confirmed_apts = [apt for apt in appointments if apt.get('status') in ['confirmed', 'pending']]
        if confirmed_apts:
            filter_keyboard.append([InlineKeyboardButton("━━━ Действия ━━━", callback_data="noop")])
            for apt in confirmed_apts[:5]:
                apt_id_new = apt.get('id')
                user_tg_id_new = apt.get('telegram_id') or 0
                name = apt.get('user_name', 'Неизвестно')[:15]
                filter_keyboard.append([
                    InlineKeyboardButton(f"✅ {name}", callback_data=f"adm_v_{apt_id_new}_{user_tg_id_new}"),
                    InlineKeyboardButton(f"⛔ {name}", callback_data=f"adm_n_{apt_id_new}_{user_tg_id_new}")
                ])
    
    filter_markup = InlineKeyboardMarkup(filter_keyboard)
    
    # Обновляем сообщение
    try:
        await query.edit_message_text(
            message_text,
            reply_markup=filter_markup,
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Ошибка обновления сообщения: {e}")
        await query.answer("Список обновлен!", show_alert=False)


async def handle_admin_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка переключения фильтров для админов"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return
    
    # Определяем выбранный фильтр
    filter_map = {
        'admin_filter_all': 'all',
        'admin_filter_confirmed': 'confirmed',
        'admin_filter_visited': 'visited',
        'admin_filter_noshow': 'noshow'
    }
    
    new_filter = filter_map.get(query.data, 'all')
    context.user_data['admin_filter'] = new_filter
    
    # Получаем отфильтрованные записи
    appointments = wp_api.get_filtered_appointments(limit=50, status_filter=new_filter)
    
    # Определяем название фильтра
    filter_names = {
        'all': 'Все записи',
        'confirmed': 'Подтвержденные',
        'visited': 'Посетили',
        'noshow': 'Не пришли'
    }
    filter_display = filter_names.get(new_filter, 'Все записи')
    
    # Формируем единое сообщение со всеми записями
    message_text = f"👮‍♂️ <b>Режим администратора</b>\n📋 Фильтр: <b>{filter_display}</b>\n\n"
    
    if not appointments:
        message_text += "� Записей не найдено"
    else:
        message_text += f"<b>Найдено записей: {len(appointments)}</b>\n"
        message_text += "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        # Показываем первые 10 записей
        for i, apt in enumerate(appointments[:10], 1):
            dt_str = str(apt.get('appointment_date', 'N/A'))
            tm_str = str(apt.get('appointment_time', 'N/A'))[:5]
            
            raw_status = apt.get('status')
            if raw_status == 'confirmed' or raw_status == 'pending':
                status_icon = "🔵"
                status_text = "Ожидает"
            elif raw_status == 'visited':
                status_icon = "✅"
                status_text = "Посетил"
            elif raw_status == 'noshow':
                status_icon = "⛔"
                status_text = "Не пришел"
            else:
                status_icon = "❓"
                status_text = "Неизвестно"
            
            # Источник
            src = apt.get('source')
            if src == 'bot' or (not src and apt.get('user_telegram_id')):
                source_icon = "🤖"
            else:
                source_icon = "🌐"
            
            message_text += (
                f"{i}. {status_icon} <b>{apt.get('user_name', 'Неизвестно')}</b>\n"
                f"   📞 {apt.get('user_phone', 'Нет')}\n"
                f"   👨‍⚕️ {apt.get('doctor_name', 'Врач удален')}\n"
                f"   📅 {dt_str} | 🕐 {tm_str}\n"
                f"   {source_icon} {status_text}\n\n"
            )
        
        if len(appointments) > 10:
            message_text += f"... и еще {len(appointments) - 10} записей\n\n"
    
    # Создаем кнопки фильтров с выделением текущего
    filter_keyboard = [
        [
            InlineKeyboardButton("📋 Все" if new_filter == 'all' else "Все", callback_data="admin_filter_all"),
            InlineKeyboardButton("🔵 Ожидают" if new_filter == 'confirmed' else "Ожидают", callback_data="admin_filter_confirmed"),
        ],
        [
            InlineKeyboardButton("✅ Посетили" if new_filter == 'visited' else "Посетили", callback_data="admin_filter_visited"),
            InlineKeyboardButton("⛔ Не пришли" if new_filter == 'noshow' else "Не пришли", callback_data="admin_filter_noshow"),
        ],
        [
            InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
            InlineKeyboardButton("📊 Экспорт в Excel", callback_data="admin_export_excel")
        ]
    ]
    
    # Добавляем кнопки действий для подтвержденных записей
    if new_filter in ['all', 'confirmed']:
        confirmed_apts = [apt for apt in appointments if apt.get('status') in ['confirmed', 'pending']]
        if confirmed_apts:
            filter_keyboard.append([InlineKeyboardButton("━━━ Действия ━━━", callback_data="noop")])
            for apt in confirmed_apts[:5]:  # Первые 5 подтвержденных
                apt_id = apt.get('id')
                user_tg_id = apt.get('telegram_id') or 0
                name = apt.get('user_name', 'Неизвестно')[:15]
                filter_keyboard.append([
                    InlineKeyboardButton(f"✅ {name}", callback_data=f"adm_v_{apt_id}_{user_tg_id}"),
                    InlineKeyboardButton(f"⛔ {name}", callback_data=f"adm_n_{apt_id}_{user_tg_id}")
                ])
    
    filter_markup = InlineKeyboardMarkup(filter_keyboard)
    
    # Обновляем сообщение
    await query.edit_message_text(
        message_text,
        reply_markup=filter_markup,
        parse_mode='HTML'
    )


async def show_admin_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать статистику записей для админов"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return
    
    # Получаем все записи для подсчета статистики
    all_appointments = wp_api.get_all_appointments(limit=200)
    
    # Подсчитываем по статусам
    confirmed_count = 0
    visited_count = 0
    noshow_count = 0
    
    # Подсчитываем по источникам
    bot_count = 0
    site_count = 0
    
    for apt in all_appointments:
        status = apt.get('status', '')
        if status in ['confirmed', 'pending']:
            confirmed_count += 1
        elif status == 'visited':
            visited_count += 1
        elif status == 'noshow':
            noshow_count += 1
        
        # Источник
        src = apt.get('source')
        if src == 'bot' or (not src and apt.get('user_telegram_id')):
            bot_count += 1
        else:
            site_count += 1
    
    total_count = len(all_appointments)
    
    stats_text = (
        "📊 <b>Статистика записей</b>\n\n"
        "<b>По статусу:</b>\n"
        f"🔵 Подтвержденные: {confirmed_count}\n"
        f"✅ Посетили: {visited_count}\n"
        f"⛔ Не пришли: {noshow_count}\n\n"
        "<b>По источнику:</b>\n"
        f"🤖 Бот: {bot_count}\n"
        f"🌐 Сайт: {site_count}\n\n"
        f"<b>Всего записей: {total_count}</b>"
    )
    
    # Кнопка возврата к админ панели
    back_keyboard = [[InlineKeyboardButton("⬅️ Назад в админ панель", callback_data="back_to_admin_panel")]]
    back_markup = InlineKeyboardMarkup(back_keyboard)
    
    await query.edit_message_text(stats_text, reply_markup=back_markup, parse_mode='HTML')


async def show_pinned_numbers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать закрепленные номера через callback"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return
    
    numbers = load_pinned_numbers()
    
    if not numbers:
        text = "📌 <b>Закрепленные номера</b>\n\n📋 Список закрепленных номеров пуст."
    else:
        text = "📌 <b>Закрепленные номера:</b>\n\n"
        for i, num in enumerate(numbers, 1):
            text += f"{i}. {num}\n"
        
        text += f"\n<b>Всего номеров:</b> {len(numbers)}"
    
    # Кнопка возврата
    back_keyboard = [[InlineKeyboardButton("⬅️ Назад в админ панель", callback_data="back_to_admin_panel")]]
    back_markup = InlineKeyboardMarkup(back_keyboard)
    
    await query.edit_message_text(text, reply_markup=back_markup, parse_mode='HTML')


async def show_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать список записей из БД через callback"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return
    
    try:
        appointments = db.get_all_appointments(limit=20)
        
        if not appointments:
            text = "📋 <b>Список записей (БД)</b>\n\n📭 Записей в базе не найдено."
        else:
            text = "📋 <b>Последние 20 записей из БД:</b>\n\n"
            
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
        
        # Кнопка возврата
        back_keyboard = [[InlineKeyboardButton("⬅️ Назад в админ панель", callback_data="back_to_admin_panel")]]
        back_markup = InlineKeyboardMarkup(back_keyboard)
        
        # Разбиваем, если слишком длинное
        if len(text) > 4096:
            # Отправляем первую часть с кнопкой
            await query.edit_message_text(text[:4096], parse_mode='HTML')
            # Отправляем остальные части
            parts = [text[i:i+4096] for i in range(4096, len(text), 4096)]
            for part in parts[:-1]:
                await query.message.reply_text(part, parse_mode='HTML')
            # Последняя часть с кнопкой
            await query.message.reply_text(parts[-1], reply_markup=back_markup, parse_mode='HTML')
        else:
            await query.edit_message_text(text, reply_markup=back_markup, parse_mode='HTML')
            
    except Exception as e:
        logger.error(f"Ошибка в show_list_callback: {e}")
        await query.edit_message_text("❌ Произошла ошибка при получении списка.", parse_mode='HTML')


async def back_to_admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Возврат в главное меню админ панели"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return
    
    # Показываем главное меню админ панели
    keyboard = [
        [InlineKeyboardButton("📋 Все записи", callback_data="admin_filter_all")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("📊 Экспорт в Excel", callback_data="admin_export_excel")],
        [InlineKeyboardButton("📌 Закрепленные номера", callback_data="admin_pinned")],
        [InlineKeyboardButton("📋 Список записей (БД)", callback_data="admin_list")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "👮‍♂️ <b>Админ панель</b>\n\n"
        "Выберите действие:",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )



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

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий кнопок меню"""
    text = update.message.text
    
    if text == "📅 Записаться на прием":
        await book_start(update, context)
    elif text == "📋 Мои записи":
        await my_appointments_command(update, context)
    elif text == "👨‍⚕️ Наши врачи":
        await doctors_command(update, context)
    elif text == "ℹ️ О клинике":
        await info_command(update, context)
    elif text == "📞 Контакты":
        await contacts_command(update, context)
    elif text == "❓ Помощь":
        await help_command(update, context)
    elif text == "👮‍♂️ Админ панель":
        # Проверяем права админа
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("⛔ У вас нет доступа к админ панели.")
            return
        
        # Предлагаем выбор админских действий
        keyboard = [
            [InlineKeyboardButton("📋 Все записи", callback_data="admin_filter_all")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("📊 Экспорт в Excel", callback_data="admin_export_excel")],
            [InlineKeyboardButton("📌 Закрепленные номера", callback_data="admin_pinned")],
            [InlineKeyboardButton("📋 Список записей (БД)", callback_data="admin_list")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "👮‍♂️ <b>Админ панель</b>\n\n"
            "Выберите действие:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

async def book_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса записи"""
    # Ограничение времени для ТЕКУЩЕГО дня проверяется позже при выборе даты
    # (Removed global block)


    # Если вызвано кнопкой меню, message будет, если командой - тоже
    context.user_data.clear()
    
    # Получаем список врачей
    # Получаем список врачей
    doctors = db.get_doctors()
    
    if not doctors:
        await update.message.reply_text(
            "❌ К сожалению, список врачей временно недоступен.\n"
            "Попробуйте позже или свяжитесь с нами по телефону."
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
        "👨‍⚕️ Выберите врача для записи:",
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
    
    # Сохраняем имя врача для дальнейшего использования
    doctors = db.get_doctors()
    doctor_name = "Неизвестный врач"
    for doc in doctors:
        if doc['id'] == doctor_id:
            doctor_name = doc['name']
            break
    context.user_data['doctor_name'] = doctor_name
    
    # Генерируем даты на ближайшие 7 дней
    keyboard = []
    today = datetime.now()
    
    for i in range(7):
        if i == 0:
            deadline_hour = context.bot_data.get('metrics', {}).get('booking_deadline', 11) # fallback
            from config import BOT_SETTINGS
            deadline_hour = BOT_SETTINGS.get('same_day_booking_deadline', 11)
            
            if today.hour >= deadline_hour:
                continue
            
            
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
    
    # Получаем расписание для конкретного врача (или используем стандартное)
    doctor_schedule = DOCTOR_SCHEDULES.get(doctor_id, WORKING_HOURS)
    
    # Получаем ВСЕ слоты на день с учетом индивидуального расписания врача
    all_slots = generate_day_slots(
        start_time=doctor_schedule.get('start', '09:00'),
        end_time=doctor_schedule.get('end', '18:00'),
        lunch_start=doctor_schedule.get('lunch_start', '13:00'),
        lunch_end=doctor_schedule.get('lunch_end', '14:00'),
        slot_duration=APPOINTMENT_DURATION,
        date_str=date
    )
    
    # (Старая ручная фильтрация удалена, теперь это делает generate_day_slots)
    
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
    """Выбор времени"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("Запись отменена.")
        return ConversationHandler.END
    
    if query.data == "back_to_dates":
        doctor_id = context.user_data.get('doctor_id')
        
        # Генерируем даты заново (как в select_doctor)
        keyboard = []
        today = datetime.now()
        
        for i in range(7):
            date = today + timedelta(days=i)
            date_str = date.strftime('%Y-%m-%d')
            display_date = date.strftime('%d.%m.%Y (%A)')
            
            days_ru = {
                'Monday': 'Пн', 'Tuesday': 'Вт', 'Wednesday': 'Ср',
                'Thursday': 'Чт', 'Friday': 'Пт', 'Saturday': 'Сб', 'Sunday': 'Вс'
            }
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
    
    # Удаляем сообщение с календарем/временем, чтобы не захламлять чат
    try:
        await query.message.delete()
    except Exception:
        pass
        
    # Сразу переходим к запросу контакта
    return await request_contact(update, context)

async def request_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашиваем контакт после выбора времени"""
    from telegram import ReplyKeyboardMarkup, KeyboardButton
    
    keyboard = [[KeyboardButton("📞 Поделиться номером телефона", request_contact=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    # Если это CallbackQuery, то update.message - это сообщение, к которому привязана кнопка
    # Но мы его уже удалили в select_time, поэтому отправляем новое сообщение
    
    # Используем effective_user для проверки админа
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    msg_text = f"✅ Вы выбрали время: <b>{context.user_data['time']}</b>\n\n"
    
    if user.id in ADMIN_IDS:
        msg_text += (
            "Для завершения записи поделитесь номером телефона 👇\n"
            "Нажмите кнопку или введите номер вручную (для админов):"
        )
    else:
        msg_text += (
            "Для завершения записи, пожалуйста, поделитесь вашим номером телефона 👇\n"
            "Нажмите кнопку ниже, чтобы отправить номер:"
        )
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=msg_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    return CONFIRM_BOOKING

async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение контакта/имени и создание записи"""
    message = update.message
    
    # 1. Если пришел КОНТАКТ
    if message.contact:
        phone = message.contact.phone_number
        if not phone.startswith('+'):
            phone = '+' + phone
        context.user_data['phone'] = phone
        
        # Спрашиваем имя (удаляем клавиатуру с кнопкой контакта)
        from telegram import ReplyKeyboardRemove
        await message.reply_text(
            f"✅ Номер получен: {phone}\n\n"
            f"Теперь введите ваше <b>Имя и Фамилию</b>:",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='HTML'
        )
        return CONFIRM_BOOKING

    # 2. Если пришел ТЕКСТ (Имя или телефон вручную)
    if message.text and not message.contact:
        # Если телефон еще не получен
        if 'phone' not in context.user_data:
            user = update.effective_user
            
            # АДМИН: Разрешаем ручной ввод
            if user.id in ADMIN_IDS:
                raw_phone = message.text.strip()
                # Простая проверка: есть цифры и длина приемлемая
                clean_phone = ''.join(filter(str.isdigit, raw_phone))
                
                if len(clean_phone) >= 7:
                    if not raw_phone.startswith('+'):
                         # Если ввели без плюса, можно добавить, но лучше оставить как есть или почистить
                         # Для простоты сохраняем как ввел админ, но убеждаемся что это похоже на номер
                         pass
                    
                    context.user_data['phone'] = raw_phone
                    
                    # Спрашиваем имя
                    from telegram import ReplyKeyboardRemove
                    await message.reply_text(
                        f"✅ Номер принят вручную: {raw_phone}\n\n"
                        f"Теперь введите <b>Имя и Фамилию</b> пациента:",
                        reply_markup=ReplyKeyboardRemove(),
                        parse_mode='HTML'
                    )
                    return CONFIRM_BOOKING
                else:
                    await message.reply_text(
                        "❌ Номер кажется некорректным (слишком короткий).\n"
                        "Введите нормальный номер или нажмите кнопку."
                    )
                    return CONFIRM_BOOKING
            
            # ОБЫЧНЫЙ ЮЗЕР: Требуем кнопку
            from telegram import ReplyKeyboardMarkup, KeyboardButton
            keyboard = [[KeyboardButton("📞 Поделиться номером телефона", request_contact=True)]]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            await message.reply_text(
                 "Пожалуйста, сначала отправьте номер телефона, нажав кнопку ниже 👇",
                 reply_markup=reply_markup
            )
            return CONFIRM_BOOKING
        # Если телефон есть, значит это ИМЯ
        context.user_data['name'] = message.text
        
        # Все данные есть - СОЗДАЕМ ЗАПИСЬ
        await finalize_booking(update, context)
        return ConversationHandler.END

async def finalize_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Финальное создание записи"""
    user_data = context.user_data
    doctor_id = user_data['doctor_id']
    date = user_data['date']
    time = user_data['time']
    # Добавляем секунды к времени, если их нет
    if len(time) == 5:
        time_full = time + ":00"
    else:
        time_full = time

    name = user_data['name']
    phone = user_data['phone']
    user = update.effective_user
    
    # 1. Создаем запись в WordPress
    success = False
    result = "WordPress API не подключен или ошибка сети"
    
    if wp_api:
        try:
            success, result = await run_sync(wp_api.create_appointment,
                doctor_id=doctor_id,
                date=date,
                time=time_full,
                patient_name=name,
                patient_phone=phone,
                telegram_id=user.id
            )
        except Exception as e:
            logger.error(f"Ошибка вызова WP API: {e}")
            result = str(e)
    else:
        logger.warning("WordPress API не инициализирован. Пропускаем сохранение на сайт.")
    
    # 2. Создаем запись в локальной БД (дублирование)
    try:
        db_success = await run_sync(
            db.create_appointment,
            user_id=user.id,
            doctor_id=doctor_id,
            appointment_date=date,
            appointment_time=time_full,
            user_name=name,
            user_phone=phone
        )
        if db_success:
            logger.info(f"✅ Запись сохранена в локальной БД: {name} на {date} {time}")
        else:
            logger.warning(f"⚠️ Не удалось сохранить запись в локальную БД")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения в локальную БД: {e}")
    
    # Отправляем главное меню обратно
    from telegram import ReplyKeyboardMarkup, KeyboardButton
    
    keyboard = []
    # Сначала добавляем админскую кнопку, если есть права
    if user.id in ADMIN_IDS:
        keyboard.append([KeyboardButton("👮‍♂️ Админ панель")])
        logger.info(f"✅ User {user.id} found in ADMIN_IDS. Added admin button.")
    else:
        logger.info(f"User {user.id} NOT in ADMIN_IDS: {ADMIN_IDS}")

    keyboard.extend([
        [KeyboardButton("📅 Записаться на прием")],
        [KeyboardButton("📋 Мои записи"), KeyboardButton("👨‍⚕️ Наши врачи")],
        [KeyboardButton("ℹ️ О клинике"), KeyboardButton("📞 Контакты")],
        [KeyboardButton("❓ Помощь")]
    ])
    
    logger.info(f"Keyboard rows: {len(keyboard)}")
        
    main_menu = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

    if success:
        appointment_id = result
        logger.info(f"✅ Запись создана: ID {appointment_id}, {name} к врачу {doctor_id} на {date} {time}")
        
        await update.message.reply_text(
            f"✅ <b>ВЫ УСПЕШНО ЗАПИСАНЫ!</b>\n\n"
            f"�‍⚕️ Врач: <b>{user_data['doctor_name']}</b>\n"
            f"📅 Дата: <b>{date}</b>\n"
            f"🕐 Время: <b>{time}</b>\n"
            f"👤 Пациент: <b>{name}</b>\n\n"
            f"📞 Мы свяжемся с вами по номеру {phone} для подтверждения.\n"
            f"� Ждем вас в клинике Diason!",
            parse_mode='HTML',
            reply_markup=main_menu
        )
        
        # Меню для админов (всегда с кнопкой)
        # Меню для админов (всегда с кнопкой)
        admin_keyboard = [
            [KeyboardButton("👮‍♂️ Админ панель")],
            [KeyboardButton("📅 Записаться на прием")],
            [KeyboardButton("📋 Мои записи"), KeyboardButton("👨‍⚕️ Наши врачи")],
            [KeyboardButton("ℹ️ О клинике"), KeyboardButton("📞 Контакты")],
            [KeyboardButton("❓ Помощь")]
        ]
        admin_menu = ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True, is_persistent=True)

        # Оповещение админов
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    reply_markup=admin_menu,
                    text=f"🆕 <b>НОВАЯ ЗАПИСЬ!</b>\n"
                         f"� {name} ({phone})\n"
                         f"👨‍⚕️ {user_data['doctor_name']}\n"
                         f"🗓️ {date} {time}\n"
                         f"🤖 Источник: Бот",
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")
                
    else:
        # Failure case
        logger.error(f"❌ Ошибка создания записи для {user.id}: {result}")
        error_msg = "Неизвестная ошибка"
        if isinstance(result, str):
            error_msg = result
        elif isinstance(result, dict) and 'message' in result:
             error_msg = result['message']

        await update.message.reply_text(
            f"❌ <b>Ошибка при создании записи</b>\n"
            f"{error_msg}\n"
            f"Пожалуйста, попробуйте еще раз или свяжитесь с нами по телефону.",
            parse_mode='HTML',
            reply_markup=main_menu
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
        entry_points=[CommandHandler('book', book_start), MessageHandler(filters.Regex("^📅 Записаться на прием$"), book_start)],
        states={
            SELECT_DOCTOR: [CallbackQueryHandler(select_doctor)],
            SELECT_DATE: [CallbackQueryHandler(select_date)],
            SELECT_TIME: [CallbackQueryHandler(select_time)],
            CONFIRM_BOOKING: [
                MessageHandler(filters.CONTACT, confirm_booking),
                MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_booking)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("id", id_command))
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
    application.add_handler(CallbackQueryHandler(handle_admin_action, pattern="^adm_[vn]_")) # Admin actions handlers
    application.add_handler(CallbackQueryHandler(handle_admin_filter, pattern="^admin_filter_")) # Admin filter handlers
    application.add_handler(CallbackQueryHandler(show_admin_statistics, pattern="^admin_stats$")) # Admin statistics
    application.add_handler(CallbackQueryHandler(show_pinned_numbers_callback, pattern="^admin_pinned$")) # Admin pinned numbers
    application.add_handler(CallbackQueryHandler(show_list_callback, pattern="^admin_list$")) # Admin list from DB
    application.add_handler(CallbackQueryHandler(back_to_admin_panel_callback, pattern="^back_to_admin_panel$")) # Back to admin panel
    application.add_handler(conv_handler)
    
    # Обработчик текстовых сообщений (для меню) должен быть ПОСЛЕ ConversationHandler
    # чтобы не перехватывать ввод внутри диалога
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))
    
    # Команда экспорта (только для админов)
    from excel_export import create_appointments_excel
    
    async def generate_and_send_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Общая функция для генерации и отправки отчета"""
        # Определяем, куда отвечать (message или callback query)
        if update.callback_query:
            message = update.callback_query.message
            await update.callback_query.answer()
            status_msg = await message.reply_text("⏳ Генерирую отчет...")
        else:
            status_msg = await update.message.reply_text("⏳ Генерирую отчет...")
            
        try:
            # Получаем все записи (можно добавить фильтры по датам аргументами)
            appointments = wp_api.get_filtered_appointments(limit=1000, status_filter='all')
            if not appointments:
                await status_msg.edit_text("📭 Записей не найдено.")
                return

            filepath = create_appointments_excel(appointments)
            
            await status_msg.chat.send_document(
                document=open(filepath, 'rb'),
                filename=os.path.basename(filepath),
                caption="📊 Отчет по записям"
            )
            await status_msg.delete()
            # Удаляем файл после отправки
            os.remove(filepath)
        except Exception as e:
            logger.error(f"Ошибка экспорта: {e}")
            await status_msg.edit_text("❌ Ошибка при создании отчета.")

    async def export_excel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка кнопки экспорта"""
        if update.effective_user.id not in ADMIN_IDS:
             await update.callback_query.answer("⛔ Нет доступа", show_alert=True)
             return
        await generate_and_send_export(update, context)

    async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in ADMIN_IDS:
             return
        await generate_and_send_export(update, context)

    application.add_handler(CommandHandler("export", export_command))
    application.add_handler(CallbackQueryHandler(export_excel_callback, pattern="^admin_export_excel$")) # Export excel
    
    # Напоминания
    from reminder_scheduler import check_reminders, handle_confirm_visit
    application.add_handler(CallbackQueryHandler(handle_confirm_visit, pattern="^confirm_visit_"))
    
    # Планировщик (JobQueue)
    if application.job_queue:
        # Запускаем каждый день в 10:00 (но для теста можно и почаще, пока поставим раз в час для проверки завтрашнего дня)
        # В продакшене лучше ставить определенное время, например run_daily
        # Но run_repeating тоже ок для начала
        application.job_queue.run_repeating(
            check_reminders, 
            interval=3600, # Каждый час
            first=10, # Первый запуск через 10 сек
            data={'wp_api': wp_api}
        )
        logger.info("⏰ Планировщик напоминаний запущен")
    else:
        logger.warning("⚠️ JobQueue не доступен!")

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