@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo.
echo  ===================================
echo   CROS 廣告數字自動化腳本
echo  ===================================
echo.

:: 確認 Python 已安裝
python --version > nul 2>&1
if errorlevel 1 (
    echo [錯誤] 找不到 Python，請先安裝 Python 3.x
    echo 下載網址：https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: 確認 config.txt 已填寫
findstr /r "^TW_USER=$" config.txt > nul 2>&1
if not errorlevel 1 (
    echo [錯誤] config.txt 的 TW_USER 尚未填寫
    echo 請用記事本開啟 config.txt 並填入帳號密碼
    echo.
    pause
    exit /b 1
)

:: 確認 credentials.json 存在
if not exist "credentials.json" (
    echo [錯誤] 找不到 credentials.json
    echo 請向管理員索取此檔案，放入本資料夾後再執行
    echo.
    pause
    exit /b 1
)

echo  正在執行，請稍候...
echo  （瀏覽器將在背景運作，請勿關閉此視窗）
echo.

python cros_daily.py

echo.
echo  ===================================
if errorlevel 1 (
    echo   執行失敗，請查看上方錯誤訊息
    echo   或查看 logs\ 資料夾中的 log 檔案
) else (
    echo   執行完成！
    echo   結果已寫入 Google 試算表
)
echo  ===================================
echo.
pause
