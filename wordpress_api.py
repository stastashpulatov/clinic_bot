import requests
import logging

class WordPressAPI:
    def __init__(self, site_url, username=None, password=None, api_key=None, verify_ssl=True, timeout=10, retry_attempts=3, cache_ttl=60):
        self.site_url = site_url
        self.username = username
        self.password = password
        self.api_key = api_key
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.logger = logging.getLogger('wordpress_api')
        
        self.headers = {
            'User-Agent': 'ClinicTelegramBot/1.0',
            'Accept': 'application/json'
        }
        
        if self.api_key:
            self.headers['x-api-key'] = self.api_key
            
        # Проверка соединения при инициализации
        try:
            self.logger.info(f"WordPress API инициализирован для {self.site_url}")
            # Можно сделать легкую проверку доступности
        except Exception as e:
            self.logger.error(f"Ошибка инициализации API: {e}")

    def get_doctors(self):
        """Получение списка врачей"""
        try:
            response = requests.get(
                f"{self.site_url}/wp-json/clinic/v1/doctors",
                headers=self.headers,
                timeout=self.timeout,
                verify=self.verify_ssl
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Ошибка получения врачей: {e}")
            return []

    def test_connection(self):
        """Проверка подключения к API"""
        try:
            # Пробуем получить список врачей как тест
            self.get_doctors()
            return True, "Подключение успешно"
        except Exception as e:
            return False, str(e)

    def get_occupied_slots(self, doctor_id, date):
        """Получение занятых слотов"""
        try:
            params = {'doctor_id': doctor_id, 'date': date}
            if self.api_key:
                params['api_key'] = self.api_key # Дублируем в GET для надежности
                
            response = requests.get(
                f"{self.site_url}/wp-json/clinic/v1/get-appointments",
                params=params,
                headers=self.headers,
                timeout=self.timeout,
                verify=self.verify_ssl
            )
            response.raise_for_status()
            data = response.json()
            # API возвращает array of objects {time, status}. Нам нужен список времен.
            slots = [item['time'][:5] for item in data] # "10:00:00" -> "10:00"
            return slots
        except Exception as e:
            self.logger.error(f"Ошибка получения слотов: {e}")
            return []

    def create_appointment(self, doctor_id, date, time, patient_name, patient_phone, telegram_id=None):
        """Создание записи"""
        try:
            payload = {
                'doctor_id': doctor_id,
                'appointment_date': date,
                'appointment_time': time,
                'user_name': patient_name,
                'user_phone': patient_phone,
                'telegram_id': telegram_id
            }
            if self.api_key:
                payload['api_key'] = self.api_key
                
            response = requests.post(
                f"{self.site_url}/wp-json/clinic/v1/appointments",
                json=payload,
                headers=self.headers,
                timeout=self.timeout,
                verify=self.verify_ssl
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    return True, result.get('id')
            
            self.logger.error(f"Ошибка создания записи: {response.text}")
            return False, None
            
        except Exception as e:
            self.logger.error(f"Исключение при создании записи: {e}")
            return False, None


    def get_patient_appointments(self, telegram_id):
        """Получение записей пациента по Telegram ID"""
        try:
            # Используем endpoint /my-appointments
            response = requests.get(
                f"{self.site_url}/wp-json/clinic/v1/my-appointments",
                params={'telegram_id': telegram_id},
                headers=self.headers,
                timeout=self.timeout,
                verify=self.verify_ssl
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Ошибка получения записей пациента: {e}")
            return []

    def cancel_appointment(self, appointment_id):
        """Отмена записи"""
        try:
            # Используем endpoint /cancel-appointment
            response = requests.post(
                f"{self.site_url}/wp-json/clinic/v1/cancel-appointment",
                params={'appointment_id': appointment_id},
                headers=self.headers,
                timeout=self.timeout,
                verify=self.verify_ssl
            )
            
            if response.status_code == 200:
                return True
            
            self.logger.error(f"Ошибка отмены записи: {response.text}")
            return False
        except Exception as e:
            self.logger.error(f"Ошибка отмены записи: {e}")
            return False

    def get_all_appointments(self, limit=50):
        """Получение всех записей (для админов)"""
        try:
            params = {'limit': limit}
            if self.api_key:
                params['api_key'] = self.api_key
                
            response = requests.get(
                f"{self.site_url}/wp-json/clinic/v1/all-appointments",
                params=params,
                headers=self.headers,
                timeout=self.timeout,
                verify=self.verify_ssl
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Ошибка получения всех записей: {e}")
            return []

    def update_appointment_status(self, appointment_id, status_code):
        """Обновление статуса записи"""
        try:
            payload = {'appointment_id': appointment_id, 'status': status_code}
            if self.api_key:
                payload['api_key'] = self.api_key
                
            response = requests.post(
                f"{self.site_url}/wp-json/clinic/v1/update-status",
                data=payload, # POST параметры
                headers=self.headers,
                timeout=self.timeout,
                verify=self.verify_ssl
            )
            
            if response.status_code == 200:
                return True
                
            self.logger.error(f"Ошибка обновления статуса: {response.text}")
            return False
        except Exception as e:
            self.logger.error(f"Исключение при обновлении статуса: {e}")
            return False

def calculate_available_slots(occupied_slots, start_time, end_time, lunch_start, lunch_end, slot_duration):
    """
    Вычисляет свободные слоты на основе занятых
    Start/End times format: "HH:MM"
    occupied_slots: list of "HH:MM" strings
    """
    from datetime import datetime, timedelta
    
    slots = []
    
    # Парсим время
    current = datetime.strptime(start_time, "%H:%M")
    end = datetime.strptime(end_time, "%H:%M")
    l_start = datetime.strptime(lunch_start, "%H:%M")
    l_end = datetime.strptime(lunch_end, "%H:%M")
    
    while current < end:
        # Проверяем обед
        is_lunch = False
        if l_start <= current < l_end:
            is_lunch = True
            
        if not is_lunch:
            time_str = current.strftime("%H:%M")
            if time_str not in occupied_slots:
                slots.append(time_str)
        
        current += timedelta(minutes=slot_duration)
        
    return slots

def generate_day_slots(start_time, end_time, lunch_start, lunch_end, slot_duration):
    """
    Генерирует все возможные слоты на день (без учета занятости)
    """
    from datetime import datetime, timedelta
    
    slots = []
    
    # Парсим время
    current = datetime.strptime(start_time, "%H:%M")
    end = datetime.strptime(end_time, "%H:%M")
    l_start = datetime.strptime(lunch_start, "%H:%M")
    l_end = datetime.strptime(lunch_end, "%H:%M")
    
    while current < end:
        # Проверяем обед
        is_lunch = False
        if l_start <= current < l_end:
            is_lunch = True
            
        # Проверяем не попадает ли слот на обед (например начинается в 12:45 и идет 45 мин = 13:30)
        # Но по старой логике (calculate_available_slots) проверялось только время начала.
        # Оставим проверку только времени начала для совместимости с логикой calculate_available_slots
        
        if not is_lunch:
            time_str = current.strftime("%H:%M")
            slots.append(time_str)
        
        current += timedelta(minutes=slot_duration)
        
    return slots
