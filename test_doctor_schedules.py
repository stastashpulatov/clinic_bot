from wordpress_api import generate_day_slots
from config import DOCTOR_SCHEDULES, WORKING_HOURS, APPOINTMENT_DURATION

print("=" * 60)
print("ТЕСТ 1: Слоты для Диярова Лола (ID: 2)")
print("=" * 60)

# Тест для Диярова Лола (ID: 2)
schedule = DOCTOR_SCHEDULES.get(2)
slots = generate_day_slots(
    start_time=schedule['start'],
    end_time=schedule['end'],
    lunch_start=schedule['lunch_start'],
    lunch_end=schedule['lunch_end'],
    slot_duration=APPOINTMENT_DURATION
)

print(f'\nРасписание: {schedule}')
print(f'\nСгенерированные слоты:')
for slot in slots:
    print(f'  - {slot}')

print(f'\n📊 Первый слот: {slots[0]}')
print(f'📊 Последний слот: {slots[-1]}')
print(f'📊 Всего слотов: {len(slots)}')

# Проверки
try:
    assert slots[0] == '09:45', f'Первый слот должен быть 09:45, получен {slots[0]}'
    assert slots[-1] == '13:30', f'Последний слот должен быть 13:30, получен {slots[-1]}'
    print('\n✅ ТЕСТ 1 ПРОЙДЕН!')
except AssertionError as e:
    print(f'\n❌ ТЕСТ 1 НЕ ПРОЙДЕН: {e}')

print("\n" + "=" * 60)
print("ТЕСТ 2: Слоты для стандартного врача (ID: 6)")
print("=" * 60)

# Тест для стандартного врача (должен использовать WORKING_HOURS)
schedule2 = DOCTOR_SCHEDULES.get(6, WORKING_HOURS)
slots2 = generate_day_slots(
    start_time=schedule2['start'],
    end_time=schedule2['end'],
    lunch_start=schedule2['lunch_start'],
    lunch_end=schedule2['lunch_end'],
    slot_duration=APPOINTMENT_DURATION
)

print(f'\nРасписание: {schedule2}')
print(f'\nСгенерированные слоты:')
for slot in slots2:
    print(f'  - {slot}')

print(f'\n📊 Первый слот: {slots2[0]}')
print(f'📊 Последний слот: {slots2[-1]}')
print(f'📊 Всего слотов: {len(slots2)}')

# Проверки
try:
    assert slots2[0] == '09:00', f'Первый слот должен быть 09:00, получен {slots2[0]}'
    assert slots2[-1] == '13:30', f'Последний слот должен быть 13:30, получен {slots2[-1]}'
    print('\n✅ ТЕСТ 2 ПРОЙДЕН!')
except AssertionError as e:
    print(f'\n❌ ТЕСТ 2 НЕ ПРОЙДЕН: {e}')

print("\n" + "=" * 60)
print("✅ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ")
print("=" * 60)
