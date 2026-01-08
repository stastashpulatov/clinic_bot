<?php
/**
 * Plugin Name: Clinic Telegram Bot API
 * Description: REST API endpoints для интеграции с Telegram ботом клиники (KiviCare Integration)
 * Version: 2.0
 * Author: Clinic Bot
 */

define('CLINIC_BOT_API_KEY', 'tg_bot_secret_key_8451'); // Секретный ключ для защиты

// Регистрация REST API endpoints
add_action('rest_api_init', function () {

    // 1. Получение списка врачей (из KiviCare)
    register_rest_route('clinic/v1', '/doctors', array(
        'methods' => 'GET',
        'callback' => 'clinic_get_kivi_doctors',
        'permission_callback' => 'clinic_check_api_key'
    ));

    // 2. Получение занятых слотов
    register_rest_route('clinic/v1', '/get-appointments', array(
        'methods' => 'GET',
        'callback' => 'clinic_get_kivi_appointments',
        'permission_callback' => 'clinic_check_api_key'
    ));

    // 3. Создание новой записи
    register_rest_route('clinic/v1', '/appointments', array(
        'methods' => 'POST',
        'callback' => 'clinic_create_kivi_appointment',
        'permission_callback' => 'clinic_check_api_key'
    ));

    // 4. Отмена записи
    register_rest_route('clinic/v1', '/cancel-appointment', array(
        'methods' => 'POST',
        'callback' => 'clinic_cancel_kivi_appointment',
        'permission_callback' => 'clinic_check_api_key'
    ));

    // 5. Получение записей пациента
    register_rest_route('clinic/v1', '/my-appointments', array(
        'methods' => 'GET',
        'callback' => 'clinic_get_patient_appointments',
        'permission_callback' => 'clinic_check_api_key'
    ));

    // 6. Получение всех записей (для админов)
    register_rest_route('clinic/v1', '/all-appointments', array(
        'methods' => 'GET',
        'callback' => 'clinic_get_all_appointments',
        'permission_callback' => 'clinic_check_api_key'
    ));
});

/**
 * Проверка API ключа
 */
function clinic_check_api_key($request)
{
    // Разрешаем публичный доступ для тестов, если нужно, но лучше защита
    $key = $request->get_header('x-api-key');
    if ($key === CLINIC_BOT_API_KEY) {
        return true;
    }
    // Также проверяем параметр GET для удобства тестов
    if ($request->get_param('api_key') === CLINIC_BOT_API_KEY) {
        return true;
    }
    return new WP_Error('forbidden', 'Invalid API Key', array('status' => 403));
}

/**
 * Получение врачей из KiviCare
 */
function clinic_get_kivi_doctors($request)
{
    global $wpdb;

    // Получаем пользователей с ролью/capability 'kiviCare_doctor'
    // Используем WP_User_Query для надежности
    $args = array(
        'meta_key' => 'ae3rf_capabilities',
        'meta_value' => 'kiviCare_doctor',
        'meta_compare' => 'LIKE'
    );
    $user_query = new WP_User_Query($args);
    $doctors = $user_query->get_results();

    $response = array();

    foreach ($doctors as $doctor) {
        $meta = get_user_meta($doctor->ID);

        // Извлекаем специализацию из basic_data JSON
        $specialty = 'Врач';
        if (!empty($meta['basic_data'][0])) {
            $basic_data = json_decode($meta['basic_data'][0], true);
            if (!empty($basic_data['specialties'][0]['label'])) {
                $specialty = $basic_data['specialties'][0]['label'];
            }
        }

        $response[] = array(
            'id' => $doctor->ID,
            'name' => $doctor->display_name, // или $meta['first_name'][0] . ' ' . $meta['last_name'][0]
            'specialty' => $specialty,
            'description' => !empty($meta['description'][0]) ? $meta['description'][0] : ''
        );
    }

    return rest_ensure_response($response);
}

/**
 * Получение записей (для проверки занятости)
 */
function clinic_get_kivi_appointments($request)
{
    global $wpdb;
    $table_name = 'ae3rf_kc_appointments'; // Название таблицы KiviCare

    $doctor_id = $request->get_param('doctor_id');
    $date = $request->get_param('date');

    if (!$doctor_id || !$date) {
        return new WP_Error('missing_params', 'Doctor ID and Date required');
    }

    // Запрос к таблице KiviCare
    $query = $wpdb->prepare(
        "SELECT id, appointment_start_time, status 
         FROM $table_name 
         WHERE doctor_id = %d 
         AND appointment_start_date = %s
         AND status != 0", // Предполагаем 0 = Отменено? Или берем все
        $doctor_id,
        $date
    );

    $appointments = $wpdb->get_results($query);

    $formatted = array();
    foreach ($appointments as $apt) {
        $formatted[] = array(
            'time' => substr($apt->appointment_start_time, 0, 5), // '10:00:00' -> '10:00'
            'status' => $apt->status
        );
    }

    return rest_ensure_response($formatted);
}

/**
 * Создание записи в KiviCare
 */
function clinic_create_kivi_appointment($request)
{
    global $wpdb;

    $doctor_id = $request->get_param('doctor_id');
    $date = $request->get_param('appointment_date');
    $time = $request->get_param('appointment_time');
    $patient_name = $request->get_param('user_name');
    $patient_phone = $request->get_param('user_phone');
    $telegram_id = $request->get_param('telegram_id'); // Желательно передавать

    if (!$doctor_id || !$date || !$time || !$patient_name) {
        return new WP_Error('missing_fields', 'Required fields missing');
    }

    // 1. Найти или создать пациента (WP User)
    $patient_id = 0;

    // Ищем по telegram_id в meta
    // (Это сложно быстро сделать без meta query, поэтому упростим: ищем по username)
    // Username формат: tg_user_{telegram_id}

    $username = 'tg_patient_' . ($telegram_id ? $telegram_id : rand(1000, 9999));
    $user = get_user_by('login', $username);

    if ($user) {
        $patient_id = $user->ID;
    } else {
        // Создаем нового пользователя
        $random_password = wp_generate_password();
        $email = $username . '@example.com'; // Фейковый email

        $userdata = array(
            'user_login' => $username,
            'user_pass' => $random_password,
            'user_email' => $email,
            'display_name' => $patient_name,
            'first_name' => $patient_name,
            'role' => 'subscriber' // Стандартная роль
        );

        $patient_id = wp_insert_user($userdata);

        if (is_wp_error($patient_id)) {
            // Если ошибка (например email занят), попробуем просто ID 0 или вернем ошибку
            // Попробуем найти по email
            return new WP_Error('user_error', 'Cannot create patient user: ' . $patient_id->get_error_message());
        }

        // Сохраняем телефон
        update_user_meta($patient_id, 'mobile_number', $patient_phone);
    }

    // 2. Рассчитываем конец приема (+30 мин)
    $start_datetime = $date . ' ' . $time;
    $end_timestamp = strtotime($start_datetime) + (30 * 60);
    $end_time = date('H:i:s', $end_timestamp);
    $end_date = date('Y-m-d', $end_timestamp); // На случай если переход через полночь (редко)

    if (strlen($time) == 5)
        $time .= ':00';

    // 3. Вставляем в таблицу KiviCare
    $table_name = 'ae3rf_kc_appointments';

    $result = $wpdb->insert(
        $table_name,
        array(
            'appointment_start_date' => $date,
            'appointment_start_time' => $time,
            'appointment_end_date' => $end_date,
            'appointment_end_time' => $end_time,
            'clinic_id' => 1, // Default clinic
            'doctor_id' => $doctor_id,
            'patient_id' => $patient_id,
            'status' => 1, // 1 = Confirmed (обычно)
            'created_at' => current_time('mysql'),
            'description' => "Запись через Telegram Бот. Пациент: $patient_name, Тел: $patient_phone"
        ),
        array('%s', '%s', '%s', '%s', '%d', '%d', '%d', '%d', '%s', '%s')
    );

    if ($result === false) {
        return new WP_Error('db_error', 'Database insert failed');
    }

    return rest_ensure_response(array(
        'success' => true,
        'id' => $wpdb->insert_id,
        'message' => 'Appointment created in KiviCare',
        'patient_id' => $patient_id
    ));
}

/**
 * Отмена записи
 */
function clinic_cancel_kivi_appointment($request)
{
    global $wpdb;
    $table_name = 'ae3rf_kc_appointments';

    $appointment_id = $request->get_param('appointment_id');

    if (!$appointment_id) {
        return new WP_Error('missing_id', 'Appointment ID required');
    }

    // Обновляем статус на 0 (Cancelled)
    $result = $wpdb->update(
        $table_name,
        array('status' => '0'), // 0 = Cancelled
        array('id' => $appointment_id),
        array('%s'),
        array('%d')
    );

    if ($result === false) {
        return new WP_Error('db_error', 'Update failed');
    }

    return rest_ensure_response(array('success' => true, 'message' => 'Appointment cancelled'));
}

/**
 * Получение записей пациента по Telegram ID
 */
function clinic_get_patient_appointments($request)
{
    global $wpdb;
    $table_name = 'ae3rf_kc_appointments';

    $telegram_id = $request->get_param('telegram_id');

    if (!$telegram_id) {
        return new WP_Error('missing_id', 'Telegram ID required');
    }

    // 1. Находим user_id по username (tg_patient_ID)
    $username = 'tg_patient_' . $telegram_id;
    $user = get_user_by('login', $username);

    if (!$user) {
        // Если пользователя нет, значит и записей нет
        return rest_ensure_response(array());
    }

    $patient_id = $user->ID;

    // 2. Ищем будущие активные записи
    $query = $wpdb->prepare(
        "SELECT id, doctor_id, appointment_start_date, appointment_start_time, status 
         FROM $table_name 
         WHERE patient_id = %d 
         AND status != 0
         AND appointment_start_date >= CURDATE()
         ORDER BY appointment_start_date ASC, appointment_start_time ASC",
        $patient_id
    );

    $appointments = $wpdb->get_results($query);

    $response = array();
    foreach ($appointments as $apt) {
        // Имя врача
        $doctor_info = get_userdata($apt->doctor_id);
        $doctor_name = $doctor_info ? $doctor_info->display_name : 'Врач #' . $apt->doctor_id;

        $response[] = array(
            'id' => $apt->id,
            'doctor' => $doctor_name,
            'date' => $apt->appointment_start_date,
            'time' => substr($apt->appointment_start_time, 0, 5),
            'status' => $apt->status
        );
    }

    return rest_ensure_response($response);
}
/**
 * Получение всех записей (для админов)
 */
function clinic_get_all_appointments($request)
{
    global $wpdb;
    $table_name = 'ae3rf_kc_appointments';
    $patient_table = 'ae3rf_kc_patient_details';

    $limit = $request->get_param('limit') ? intval($request->get_param('limit')) : 50;

    // Получаем последние записи с JOIN к таблице пациентов
    // Важно: status!=0 (не отмененные) или все? Админам лучше все, но можно фильтровать.
    // Пока берем все для истории.

    // Получаем записи с сегодняшнего дня и будущие, исключая отмененные (status != 0)
    $query = $wpdb->prepare(
        "SELECT * FROM $table_name 
         WHERE appointment_start_date >= CURDATE() 
         AND status != 0
         ORDER BY appointment_start_date ASC, appointment_start_time ASC
         LIMIT %d",
        $limit
    );

    $appointments = $wpdb->get_results($query);

    // DEBUG: Если ошибка, возвращаем её
    if ($wpdb->last_error) {
        return rest_ensure_response(array(
            'error' => $wpdb->last_error,
            'query' => $query
        ));
    }

    $response = array();
    foreach ($appointments as $apt) {
        // Данные врача
        $doctor_info = get_userdata($apt->doctor_id);
        $doctor_name = $doctor_info ? $doctor_info->display_name : 'Врач #' . $apt->doctor_id;

        // Данные пациента
        $patient_name = 'Гость';
        $patient_phone = '';

        // Попытка 1: Если patient_id это WP User
        if (!empty($apt->patient_id)) {
            $patient_info = get_userdata($apt->patient_id);
            if ($patient_info) {
                $patient_name = $patient_info->display_name;
                $patient_phone = get_user_meta($patient_info->ID, 'mobile_number', true);
            }
        }

        // Попытка 2: Проверяем, есть ли поля имени прямо в таблице (иногда бывают)
        if (!empty($apt->first_name))
            $patient_name = $apt->first_name . ' ' . $apt->last_name;
        if (!empty($apt->mobile_number))
            $patient_phone = $apt->mobile_number;

        // Попытка 3: Из описания (для бота)
        $source = 'site';
        if (isset($apt->description) && strpos($apt->description, 'Telegram Бот') !== false) {
            $source = 'bot';
            if (preg_match('/Пациент: (.*?), Тел: (.*)/', $apt->description, $matches)) {
                $patient_name = $matches[1];
                $patient_phone = $matches[2];
            }
        }

        $status_val = isset($apt->status) ? $apt->status : 0;
        $status_str = 'pending';
        if ($status_val == 1)
            $status_str = 'confirmed';
        elseif ($status_val == 0)
            $status_str = 'cancelled';

        $response[] = array(
            'id' => $apt->id,
            'doctor_name' => $doctor_name,
            'user_name' => $patient_name,
            'user_phone' => $patient_phone,
            'appointment_date' => $apt->appointment_start_date,
            'appointment_time' => substr($apt->appointment_start_time, 0, 5),
            'status' => $status_str,
            'source' => $source,
            'created_at' => isset($apt->created_at) ? $apt->created_at : '',
            'debug_pid' => $apt->patient_id // Debug
        );
    }

    return rest_ensure_response($response);
}
