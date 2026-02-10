
import mysql.connector
from config import DB_CONFIG
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Список врачей из fallback list (то что нужно пользователю)
# Лаборанты (Имомов, Адилова) удалены из активного списка
FALLBACK_DOCTORS = [
    {"id": 6, "name": "Зеберг Дмитрий", "specialty": "Уролог", "description": "Врач высшей категории"},
    {"id": 8, "name": "Стасюк Лариса", "specialty": "Невролог", "description": ""},
    {"id": 7, "name": "Гафурова Нигора", "specialty": "УЗИ", "description": ""},
    {"id": 2, "name": "Диярова Лола", "specialty": "Гинеколог", "description": ""}
]

def split_name(full_name):
    """Разбивка имени на части"""
    parts = full_name.split()
    last_name = parts[0] if len(parts) > 0 else ""
    first_name = parts[1] if len(parts) > 1 else ""
    middle_name = parts[2] if len(parts) > 2 else ""
    return first_name, last_name, middle_name

def add_return_date_column(cursor):
    """Добавление колонки return_date если её нет"""
    try:
        cursor.execute("SHOW COLUMNS FROM doctors LIKE 'return_date'")
        result = cursor.fetchone()
        if not result:
            logger.info("Добавление колонки return_date...")
            cursor.execute("ALTER TABLE doctors ADD COLUMN return_date DATE NULL DEFAULT NULL")
            logger.info("Колонка return_date добавлена успешно")
        else:
            logger.info("Колонка return_date уже существует")
    except Exception as e:
        logger.error(f"Ошибка при добавлении колонки: {e}")

def init_doctors():
    try:
        # Подключение к БД
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        logger.info("Подключение к БД успешно")
        
        # 0. Миграция схемы (добавление return_date)
        add_return_date_column(cursor)
        
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
        logger.info("Активные врачи обновлены, лаборанты скрыты, колонка return_date проверена.")
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == "__main__":
    init_doctors()
