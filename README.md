# CROS 廣告數字自動化腳本

每天自動從 CROS 抓取昨日受注資料，寫入 Google 試算表。

---

## 首次設定（新電腦）

### 步驟 1：安裝套件
雙擊執行 `setup_first_time.bat`，等待安裝完成。

### 步驟 2：填寫帳號密碼
用記事本開啟 `config.txt`，填入您的 CROS 帳號密碼：
```
TW_USER=您的台灣帳號
TW_PASS=您的密碼
HK_USER=您的香港帳號
HK_PASS=您的密碼
```

### 步驟 3：取得 Google 憑證
向管理員索取 `credentials.json`，放入本資料夾（與 `run.bat` 同一層）。

### 步驟 4：執行
雙擊 `run.bat`，首次執行時瀏覽器會開啟讓您登入，之後會自動記住登入狀態。

---

## 設定自動排程（每天 09:00）

在 PowerShell 執行以下指令（將路徑改為您的資料夾位置）：

先在 PowerShell 中 `cd` 到本資料夾，再執行：

```powershell
$py    = (Get-Command python).Source
$dir   = (Get-Item .).FullName
$action   = New-ScheduledTaskAction -Execute $py -Argument "`"$dir\cros_daily.py`"" -WorkingDirectory $dir
$trigger  = New-ScheduledTaskTrigger -Daily -At "09:00AM"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -StartWhenAvailable -WakeToRun
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "CROS_Daily_Update" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
```

---

## 日常使用

| 情境 | 做什麼 |
|------|--------|
| 查看昨日結果 | 直接看 Google 試算表 |
| 手動補跑某天 | 修改 `cros_daily.py` 第一行 `TARGET_DATE`，執行 `run.bat` |
| 執行異常 | 查看 `logs/YYYYMMDD.log` |

## 注意事項

| 情況 | 處理方式 |
|------|---------|
| Session 過期（幾週一次）| 腳本自動開啟瀏覽器，重新登入即可 |
| HK 需要驗證碼 | 在瀏覽器輸入手機收到的 6 位數驗證碼 |
| 新月份 | 自動複製上月工作表並更新，無需手動 |
| 電腦需開機 | 睡眠可自動喚醒；完全關機則無法執行 |

---

---

## Benchmark Email 名單上傳（benchmark_upload.py）

每月 **15 日** 和 **月底** 自動更新聯絡人名單，完成後自動點擊 Google Sheets「更新聯絡人主表」。

### 模式說明

| 模式 | 說明 | 範例 |
|------|------|------|
| `mode1` | 更新 TW + HK 新顧客名單（截止日 = 上月同日） | 每月 15 / 月底自動執行 |
| `mode2 MMDD MMDD` | 建立指定檔期「購買過名單」 | `python benchmark_upload.py mode2 0601 0622` |

### 手動執行

```
run_benchmark.bat mode1
run_benchmark.bat mode2 0601 0622
```

### 設定自動排程（每天 10:00，15日/月底自動判斷執行）

先在 PowerShell 中 `cd` 到本資料夾，再執行以下指令：

```powershell
$py    = (Get-Command python).Source
$dir   = (Get-Item .).FullName
$action   = New-ScheduledTaskAction -Execute $py -Argument "`"$dir\benchmark_scheduler.py`"" -WorkingDirectory $dir
$trigger  = New-ScheduledTaskTrigger -Daily -At "10:00AM"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable -WakeToRun
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "BM_Mode1_HalfMonthly" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
```

### 首次執行 Google Sheets 登入

第一次執行 mode1 時，瀏覽器會開啟 Google 登入頁面，手動登入後 session 自動保存，之後免登入。

---

## 不在 GitHub 的檔案（各自處理）

| 檔案 | 說明 |
|------|------|
| `config.txt` | 填入帳密後屬於個人資料，請勿上傳 |
| `credentials.json` | 向管理員索取 |
| `session_*.json` | 登入後自動產生（tw / hk / bm / google） |
| `logs/` | 本機執行紀錄 |
