#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АВТОМАТИЧЕСКОЕ ИСПРАВЛЕНИЕ clinic_bot.py

Этот скрипт автоматически исправляет:
1. Метод _get_fallback_doctors
2. SQL запрос WHERE clause в get_doctors
"""

import re
import sys
import os
from datetime import datetime

def create_backup(filename):
    """Создание резервной копии"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"{filename}.backup_{timestamp}"
    
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    
    with open(backup_name, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"✅ Создана резервная копия: {backup_name}")
    return backup_name

def fix_fallback_doctors(content):
    """Исправление метода _get_fallback_doctors"""
    
    # Новый корректный метод
    new_method = '''    def _get_fallback_doctors(self):
        """Резервный список врачей - ЭТАЛОННЫЙ СПИСОК"""
        return [
            {"id": 10, "name": "Имомов Сабир", "specialty": "Лаборант", "description": "", "return_date": None},
            {"id": 6, "name": "Зеберг Дмитрий", "specialty": "Уролог", "description": "Врач высшей категории", "return_date": None},
            {"id": 8, "name": "Стасюк Лариса", "specialty": "Невролог", "description": "", "return_date": None},
            {"id": 7, "name": "Гафурова Нигора", "specialty": "УЗИ", "description": "", "return_date": None},
            {"id": 9, "name": "Адилова Надира", "specialty": "Лаборант", "description": "", "return_date": None},
            {"id": 2, "name": "Диярова Лола", "specialty": "Гинеколог", "description": "", "return_date": None}
        ]'''
    
    # Ищем метод _get_fallback_doctors с помощью регулярного выражения
    pattern = r'    def _get_fallback_doctors\(self\):.*?return \[.*?\n        \]'
    
    match = re.search(pattern, content, re.DOTALL)
    if match:
        content = content.replace(match.group(0), new_method)
        print("✅ Исправлен метод _get_fallback_doctors")
        return content, True
    else:
        print("⚠️  Метод _get_fallback_doctors не найден или уже исправлен")
        return content, False

def fix_get_doctors_query(content):
    """Исправление SQL запроса в методе get_doctors"""
    
    # Старый WHERE clause
    old_where = r'WHERE is_active = 1 OR \(return_date IS NOT NULL AND return_date >= CURDATE\(\)\)'
    
    # Новый WHERE clause
    new_where = 'WHERE is_active = 1'
    
    if re.search(old_where, content):
        content = re.sub(old_where, new_where, content)
        print("✅ Исправлен WHERE clause в get_doctors")
        return content, True
    else:
        print("⚠️  WHERE clause не найден или уже исправлен")
        return content, False

def add_improved_logging(content):
    """Добавление улучшенного логирования в get_doctors"""
    
    # Ищем строку после cursor.fetchall()
    pattern = r'(doctors = cursor\.fetchall\(\))\n(\s+)if not doctors:'
    
    replacement = r'''\1
\2
\2logger.info(f"✅ Получено {len(doctors)} активных врачей из БД")
\2
\2if not doctors:'''
    
    if re.search(pattern, content):
        content = re.sub(pattern, replacement, content)
        print("✅ Добавлено улучшенное логирование")
        return content, True
    else:
        print("ℹ️  Логирование уже добавлено или не требуется")
        return content, False

def main():
    """Основная функция"""
    print("="*60)
    print("🔧 АВТОМАТИЧЕСКОЕ ИСПРАВЛЕНИЕ clinic_bot.py")
    print("="*60)
    
    filename = 'clinic_bot.py'
    
    # Проверка наличия файла
    if not os.path.exists(filename):
        print(f"❌ Файл {filename} не найден!")
        print("   Убедитесь, что вы запускаете скрипт в директории проекта")
        return False
    
    # Создание резервной копии
    print("\n📁 Создание резервной копии...")
    backup_file = create_backup(filename)
    
    # Чтение файла
    print(f"\n📖 Чтение файла {filename}...")
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    changes = []
    
    # Применение исправлений
    print("\n🔧 Применение исправлений...\n")
    
    content, changed = fix_fallback_doctors(content)
    if changed:
        changes.append("_get_fallback_doctors")
    
    content, changed = fix_get_doctors_query(content)
    if changed:
        changes.append("get_doctors WHERE clause")
    
    content, changed = add_improved_logging(content)
    if changed:
        changes.append("logging")
    
    # Сохранение изменений
    if content != original_content:
        print(f"\n💾 Сохранение изменений...")
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"✅ Файл {filename} успешно обновлён!")
        
        if changes:
            print(f"\n📋 Применённые изменения:")
            for i, change in enumerate(changes, 1):
                print(f"  {i}. {change}")
        
        print("\n" + "="*60)
        print("✅ ИСПРАВЛЕНИЕ ЗАВЕРШЕНО УСПЕШНО!")
        print("="*60)
        
        print("\n📌 СЛЕДУЮЩИЕ ШАГИ:")
        print("1. Запустите: python init_db_doctors.py")
        print("2. Запустите: python test_system.py")
        print("3. Запустите: python clinic_bot.py")
        
        print(f"\n💡 Резервная копия сохранена: {backup_file}")
        print("   Вы можете восстановить её в случае проблем")
        
        return True
    else:
        print("\n" + "="*60)
        print("ℹ️  ИЗМЕНЕНИЯ НЕ ТРЕБУЮТСЯ")
        print("="*60)
        print("\nФайл clinic_bot.py уже содержит все необходимые исправления")
        print("или использует другую структуру кода.")
        
        # Удаляем ненужную резервную копию
        if os.path.exists(backup_file):
            os.remove(backup_file)
            print(f"\n🗑️  Удалена ненужная резервная копия: {backup_file}")
        
        return False

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)