@echo off
cd /d "%~dp0"
echo Starting GenWise AI/ML Classroom...
echo.
echo Open http://127.0.0.1:8777 in your browser.
echo On a fresh database, the first signup becomes the first teacher account.
echo.
python genwise_classroom\app.py
pause
