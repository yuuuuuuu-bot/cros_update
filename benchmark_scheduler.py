# -*- coding: utf-8 -*-
"""
benchmark_scheduler.py
每天由 Windows 工作排程器啟動；只在每月 15 日 / 月底當天執行 mode1。
"""
import sys, io, os, datetime, calendar, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
LOG_DIR    = os.path.join(BASE_DIR, 'logs')
SCRIPT     = os.path.join(BASE_DIR, 'benchmark_upload.py')

os.makedirs(LOG_DIR, exist_ok=True)

today    = datetime.date.today()
last_day = calendar.monthrange(today.year, today.month)[1]

if today.day not in (15, last_day):
    print(f'{today}: 非執行日（15日 / {last_day}日のみ実行），スキップ')
    sys.exit(0)

log_file = os.path.join(LOG_DIR, f'benchmark_{today:%Y%m%d}.log')
print(f'{today}: mode1 実行 → {log_file}')

with open(log_file, 'w', encoding='utf-8') as f:
    result = subprocess.run(
        [sys.executable, SCRIPT, 'mode1'],
        stdout=f, stderr=subprocess.STDOUT,
        cwd=BASE_DIR
    )

sys.exit(result.returncode)
