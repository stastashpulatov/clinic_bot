@echo off
echo ========================================
echo Установка зависимостей для бота клиники
echo ========================================
echo.

echo 1. Обновление pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo ❌ Ошибка при обновлении pip
    pause
    exit /b 1
)

echo.
echo 2. Установка python-telegram-bot...
pip install python-telegram-bot==20.7
if errorlevel 1 (
    echo ❌ Ошибка при установке python-telegram-bot
    pause
    exit /b 1
)

echo.
echo 3. Установка mysql-connector-python...
pip install mysql-connector-python==8.1.0
if errorlevel 1 (
    echo ❌ Ошибка при установке mysql-connector-python
    pause
    exit /b 1
)

echo.
echo ========================================
echo ✅ Все зависимости успешно установлены!
echo ========================================
echo.
echo Теперь вы можете запустить:
echo 1. run_analysis.bat - для проверки базы данных
echo 2. run_bot.bat - для запуска бота
echo.
pause