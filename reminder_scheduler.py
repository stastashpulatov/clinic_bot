import json
import os

SENT_REMINDERS_FILE = 'data/sent_reminders.json'

def load_sent_reminders():
    if os.path.exists(SENT_REMINDERS_FILE):
        try:
            with open(SENT_REMINDERS_FILE, 'r') as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_sent_reminder(apt_id):
    sent = load_sent_reminders()
    sent.add(str(apt_id))
    os.makedirs('data', exist_ok=True)
    with open(SENT_REMINDERS_FILE, 'w') as f:
        json.dump(list(sent), f)

async def check_reminders(context):
    """
    Периодическая задача для проверки напоминаний
    Запускается каждый час
    """
    bot = context.bot
    wp_api = context.job.data.get('wp_api')
    
    if not wp_api:
        logger.error("WP API not provided to reminder job")
        return

    try:
        # Получаем записи (статус confirmed)
        appointments = wp_api.get_filtered_appointments(limit=100, status_filter='confirmed')
        if not appointments:
            return

        today = datetime.now().date()
        sent_reminders = load_sent_reminders()
        
        for apt in appointments:
            apt_date_str = apt.get('appointment_date')
            if not apt_date_str:
                continue
                
            apt_date = datetime.strptime(apt_date_str, '%Y-%m-%d').date()
            days_diff = (apt_date - today).days
            
            # Напоминаем за 1 день (завтра)
            if days_diff == 1:
                tg_id = apt.get('user_telegram_id')
                apt_id = str(apt.get('id'))
                
                if not tg_id:
                    continue
                    
                # Проверка по персистентному хранилищу
                if apt_id in sent_reminders:
                    continue
                
                try:
                    name = apt.get('user_name', 'Пациент')
                    time = str(apt.get('appointment_time', ''))[:5]
                    date_iso = apt.get('appointment_date')
                    # Преобразуем дату в красивый вид для сообщения (опционально)
                    # Но пока оставим как есть из API
                    
                    doctor = apt.get('doctor_name', 'Врач')
                    
                    text = (
                        f"⏰ <b>Напоминание о приеме!</b>\n\n"
                        f"👋 Здравствуйте, {name}!\n"
                        f"Напоминаем, что вы записаны на прием <b>ЗАВТРА</b>.\n\n"
                        f"📅 Дата: <b>{date_iso}</b>\n"
                        f"🕐 Время: <b>{time}</b>\n"
                        f"👨‍⚕️ Врач: <b>{doctor}</b>\n\n"
                        f"Пожалуйста, подтвердите ваш визит или отмените запись, если у вас изменились планы."
                    )
                    
                    keyboard = [
                        [InlineKeyboardButton("✅ Подтверждаю", callback_data=f"confirm_visit_{apt_id}")],
                        [InlineKeyboardButton("❌ Отменить запись", callback_data=f"cancel_apt_{apt_id}_{tg_id}")]
                    ]
                    
                    await bot.send_message(
                        chat_id=tg_id, 
                        text=text, 
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='HTML'
                    )
                    
                    # Сохраняем ID отправленного напоминания
                    save_sent_reminder(apt_id)
                    logger.info(f"Напоминание отправлено пользователю {tg_id} для записи {apt_id}")
                    
                except Exception as e:
                    logger.error(f"Не удалось отправить напоминание {tg_id}: {e}")

    except Exception as e:
        logger.error(f"Ошибка в job check_reminders: {e}")

async def handle_confirm_visit(update, context):
    query = update.callback_query
    await query.answer("Спасибо за подтверждение!")
    await query.edit_message_text(
        f"{query.message.text}\n\n✅ <b>Вы подтвердили свой визит! Ждем вас!</b>",
        parse_mode='HTML'
    )
