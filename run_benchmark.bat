@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo.
echo  ===================================
echo   Benchmark Email 名單自動上傳
echo  ===================================
echo.
echo  使用方式：
echo    mode1        更新 TW+HK 新顧客名單（每月15日 / 月底執行）
echo    mode2 MMDD MMDD  建立購買過名單（例：mode2 0601 0622）
echo.

if "%1"=="" (
    echo [錯誤] 請指定模式，例如：run_benchmark.bat mode1
    echo.
    pause
    exit /b 1
)

python --version > nul 2>&1
if errorlevel 1 (
    echo [錯誤] 找不到 Python
    pause
    exit /b 1
)

echo  執行中（瀏覽器將在背景開啟，請勿手動關閉）...
echo.

python benchmark_upload.py %*

echo.
echo  ===================================
if errorlevel 1 (
    echo   執行失敗，請查看錯誤訊息
) else (
    echo   完成！
)
echo  ===================================
echo.
pause
