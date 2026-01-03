
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
            
        # Для совместимости: если начало слота не в обед, то слот валиден
        
        if not is_lunch:
            time_str = current.strftime("%H:%M")
            slots.append(time_str)
        
        current += timedelta(minutes=slot_duration)
        
    return slots
