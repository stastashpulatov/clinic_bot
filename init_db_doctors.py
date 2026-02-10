
import mysql.connector
from config import DB_CONFIG
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Список врачей из fallback list (то что нужно пользователю)
FALLBACK_DOCTORS = [
    {"id": 10, "name": "Имомов Сабир", "specialty": "Лаборант", "description": ""},
    {"id": 6, "name": "Зеберг Дмитрий", "specialty": "Уролог", "description": "Врач высшей категории"},
    {"id": 8, "name": "Стасюк Лариса", "specialty": "Невролог", "description": ""},
    {"id": 7, "name": "Гафурова Нигора", "specialty": "УЗИ", "description": ""},
    {"id": 9, "name": "Адилова Надира", "specialty": "Лаборант", "description": ""},
    {"id": 2, "name": "Диярова Лола", "specialty": "Гинеколог", "description": ""}
]

def split_name(full_name):
    """Разбивка имени на части"""
    parts = full_name.split()
    last_name = parts[0] if len(parts) > 0 else ""
    first_name = parts[1] if len(parts) > 1 else ""
    middle_name = parts[2] if len(parts) > 2 else ""
    return first_name, last_name, middle_name

def init_doctors():
    try:
        # Подключение к БД
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        logger.info("Подключение к БД успешно")
        
        # 1. Сначала деактивируем всех врачей (soft delete)
        logger.info("Деактивация всех текущих врачей...")
        cursor.execute("UPDATE doctors SET is_active = 0")
        
        # 2. Обновляем или вставляем нужных врачей
        logger.info("Обновление списка врачей...")
        query = """
            INSERT INTO doctors (id, first_name, last_name, middle_name, specialty, description, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE
            first_name = VALUES(first_name),
            last_name = VALUES(last_name),
            middle_name = VALUES(middle_name),
            specialty = VALUES(specialty),
            description = VALUES(description),
            is_active = 1
        """
        
        for doc in FALLBACK_DOCTORS:
            first, last, middle = split_name(doc["name"])
            values = (
                doc["id"], 
                first, 
                last, 
                middle, 
                doc["specialty"], 
                doc["description"]
            )
            cursor.execute(query, values)
            logger.info(f"Обновлен/Добавлен врач: {doc['name']}")
            
        conn.commit()
        logger.info("✅ База данных успешно синхронизирована!")
        logger.info("Все врачи из списка теперь активны, остальные деактивированы.")
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == "__main__":
    init_doctors()
