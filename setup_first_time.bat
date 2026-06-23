@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo.
echo  ===================================
echo   首次安裝 - 安裝必要套件
echo  ===================================
echo.

python --version > nul 2>&1
if errorlevel 1 (
    echo [錯誤] 找不到 Python，請先安裝 Python 3.x
    echo 下載網址：https://www.python.org/downloads/
    echo 安裝時請勾選「Add Python to PATH」
    echo.
    pause
    exit /b 1
)

echo  安裝 Python 套件中...
pip install playwright gspread google-auth
echo.
echo  安裝 Chromium 瀏覽器中（約 100MB）...
python -m playwright install chromium
echo.
echo  ===================================
echo   安裝完成！接下來請：
echo.
echo   1. 用記事本開啟 config.txt
echo      填入您的 CROS 帳號密碼
echo.
echo   2. 向管理員索取 credentials.json
echo      放入本資料夾
echo.
echo   3. 雙擊 run.bat 執行
echo  ===================================
echo.
pause
