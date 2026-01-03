@echo off
echo ========================================
echo Запуск бота для записи в клинику
echo ========================================
echo.

echo Проверяю наличие Python...
python --version
if errorlevel 1 (
    echo ❌ Python не установлен или не добавлен в PATH
    pause
    exit /b 1
)

echo.
echo Запускаю бота...
echo Для остановки нажмите Ctrl+C
echo.
python clinic_bot_final.py

echo.
echo ========================================
echo Бот остановлен
echo ========================================
echo.
pause