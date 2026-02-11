import mysql.connector
from config import DB_CONFIG
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ЭТАЛОННЫЙ СПИСОК ВРАЧЕЙ - согласно предоставленному скриншоту
# Этот список должен использоваться везде в проекте
# ВСЕ врачи из этого списка должны быть АКТИВНЫ
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

def add_return_date_column(cursor):
    """Добавление колонки return_date если её нет"""
    try:
        cursor.execute("SHOW COLUMNS FROM doctors LIKE 'return_date'")
        result = cursor.fetchone()
        if not result:
            logger.info("Добавление колонки return_date...")
            cursor.execute("ALTER TABLE doctors ADD COLUMN return_date DATE NULL DEFAULT NULL")
            logger.info("✅ Колонка return_date добавлена успешно")
        else:
            logger.info("✅ Колонка return_date уже существует")
    except Exception as e:
        logger.error(f"❌ Ошибка при добавлении колонки: {e}")

def init_doctors():
    try:
        # Подключение к БД
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        logger.info("✅ Подключение к БД успешно")
        
        # 0. Миграция схемы (добавление return_date)
        add_return_date_column(cursor)
        
        # 1. Деактивируем всех врачей (для очистки)
        logger.info("🔄 Деактивация всех текущих врачей...")
        cursor.execute("UPDATE doctors SET is_active = 0")
        
        # 2. Активируем только врачей из эталонного списка
        logger.info(f"🔄 Активация {len(FALLBACK_DOCTORS)} врачей из эталонного списка...")
        query = """
            INSERT INTO doctors (id, first_name, last_name, middle_name, specialty, description, is_active, return_date)
            VALUES (%s, %s, %s, %s, %s, %s, 1, NULL)
            ON DUPLICATE KEY UPDATE
            first_name = VALUES(first_name),
            last_name = VALUES(last_name),
            middle_name = VALUES(middle_name),
            specialty = VALUES(specialty),
            description = VALUES(description),
            is_active = 1,
            return_date = NULL
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
            logger.info(f"✅ Активирован врач: {doc['name']} (ID: {doc['id']}, {doc['specialty']})")
            
        conn.commit()
        
        # 3. Проверка результата
        cursor.execute("SELECT COUNT(*) FROM doctors WHERE is_active = 1")
        active_count = cursor.fetchone()[0]
        
        logger.info("=" * 60)
        logger.info("✅ СИНХРОНИЗАЦИЯ ЗАВЕРШЕНА УСПЕШНО!")
        logger.info(f"📊 Активных врачей в базе: {active_count}")
        logger.info(f"📊 Ожидалось врачей: {len(FALLBACK_DOCTORS)}")
        logger.info("=" * 60)
        
        if active_count != len(FALLBACK_DOCTORS):
            logger.warning(f"⚠️ ВНИМАНИЕ: Количество активных врачей ({active_count}) не совпадает с ожидаемым ({len(FALLBACK_DOCTORS)})")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
            logger.info("🔌 Соединение с БД закрыто")

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🏥 ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ВРАЧЕЙ")
    print("=" * 60)
    print(f"\n📋 Будет активировано {len(FALLBACK_DOCTORS)} врачей:\n")
    for i, doc in enumerate(FALLBACK_DOCTORS, 1):
        print(f"{i}. {doc['name']} - {doc['specialty']}")
    print("\n" + "=" * 60 + "\n")
    
    init_doctors()