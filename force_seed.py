import mysql.connector
from mysql.connector import Error
from config import DB_CONFIG, TABLE_PREFIX

def get_fallback_doctors():
    """Резервный список врачей"""
    return [
        {"id": 10, "name": "Имомов Сабир", "specialty": "Лаборант", "description": ""},
        {"id": 6, "name": "Зеберг Дмитрий", "specialty": "Уролог", "description": "Врач высшей категории"},
        {"id": 8, "name": "Стасюк Лариса", "specialty": "Невролог", "description": ""},
        {"id": 7, "name": "Гафурова Нигора", "specialty": "УЗИ", "description": ""},
        {"id": 9, "name": "Адилова Надира", "specialty": "Лаборант", "description": ""},
        {"id": 2, "name": "Диярова Лола", "specialty": "Гинеколог", "description": ""}
    ]

def seed_doctors():
    print("Connecting to database...")
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        if connection.is_connected():
            cursor = connection.cursor()
            print("Connected!")
            
            doctors = get_fallback_doctors()
            print(f"Seeding {len(doctors)} doctors...")
            
            query = f"""
                INSERT INTO {TABLE_PREFIX}doctors 
                (id, first_name, last_name, middle_name, specialty, description, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                first_name = VALUES(first_name),
                last_name = VALUES(last_name),
                middle_name = VALUES(middle_name),
                specialty = VALUES(specialty),
                description = VALUES(description),
                is_active = 1
            """
            
            for doc in doctors:
                parts = doc['name'].split()
                last_name = parts[0] if len(parts) > 0 else "Unknown"
                first_name = parts[1] if len(parts) > 1 else ""
                middle_name = " ".join(parts[2:]) if len(parts) > 2 else ""
                
                cursor.execute(query, (
                    doc['id'],
                    first_name,
                    last_name,
                    middle_name,
                    doc['specialty'],
                    doc['description'],
                    1
                ))
                print(f"Upserted: {doc['name']}")
            
            connection.commit()
            print("Done! Database seeded.")
            
    except Error as e:
        print(f"Error: {e}")
    finally:
        if 'connection' in locals() and connection.is_connected():
            cursor.close()
            connection.close()

if __name__ == "__main__":
    seed_doctors()
