# -*- coding: utf-8 -*-
# CROS 毎日自動集計スクリプト
# 昨日の受注日で TW / HK を集計して Google Spreadsheet に書き込む
# Windows タスクスケジューラから毎朝 08:00 に起動
# ログ: cros_updater/logs/YYYYMMDD.log
import sys, io, os, re, datetime, calendar, traceback

# 腳本所在資料夾為基準，任何電腦都適用
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
LOG_DIR    = os.path.join(BASE_DIR, 'logs')
CREDS_FILE = os.path.join(BASE_DIR, 'credentials.json')   # 憑證放同一資料夾
SHEET_ID   = '1Hs3hK9cikUOia_6uqv8-jibVJUu-rLlmd9VnQplx9FQ'

STATUS_FILTER = ['300', '400', '900']
AMOUNT_IDX    = 6   # 受注金額 の列インデックス (0-based)

# 新規・回購セクションの先頭行（テンプレートから固定）
SHINKI_START = 22
KAIKOU_START = 103

# ─── 帳密從 config.txt 讀取 ──────────────────────
def load_config():
    cfg = {}
    config_path = os.path.join(BASE_DIR, 'config.txt')
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            'config.txt 不存在，請複製一份並填入帳號密碼')
    with open(config_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                cfg[key.strip()] = val.strip()
    missing = [k for k in ('TW_USER','TW_PASS','HK_USER','HK_PASS') if not cfg.get(k)]
    if missing:
        raise ValueError(f'config.txt 尚未填寫：{", ".join(missing)}')
    return cfg

_cfg = load_config()

REGIONS = [
    {
        'name'      : 'TW',
        'session'   : os.path.join(BASE_DIR, 'session_tw.json'),
        'user'      : _cfg['TW_USER'],
        'pw'        : _cfg['TW_PASS'],
        'shinki_kw' : ['新規', '95折', '活動価'],
        'count_col' : 2,   # B
        'sale_col'  : 3,   # C
    },
    {
        'name'      : 'HK',
        'session'   : os.path.join(BASE_DIR, 'session_hk.json'),
        'user'      : _cfg['HK_USER'],
        'pw'        : _cfg['HK_PASS'],
        'shinki_kw' : ['HKLP', '95折LP'],
        'count_col' : 5,   # E
        'sale_col'  : 6,   # F
    },
]

SCOPES = ['https://www.googleapis.com/auth/spreadsheets',
          'https://www.googleapis.com/auth/drive']

# ─── ログ設定 ─────────────────────────────────────
today_str = datetime.date.today().strftime('%Y%m%d')
log_path  = os.path.join(LOG_DIR, f'{today_str}.log')

class Tee:
    def __init__(self, file_obj, original):
        self._file = file_obj
        self._orig = original
    def write(self, data):
        self._file.write(data); self._file.flush()
        self._orig.write(data); self._orig.flush()
    def flush(self):
        self._file.flush(); self._orig.flush()

os.makedirs(LOG_DIR, exist_ok=True)
_log_file = open(log_path, 'a', encoding='utf-8')
_orig_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stdout = Tee(_log_file, _orig_stdout)

print(f'\n{"="*60}', flush=True)
print(f'[{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] 開始', flush=True)
print(f'{"="*60}', flush=True)

# ─── 集計日・ワークシート名を動的に計算 ────────────
import gspread
import gspread.utils
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright
from collections import Counter

yesterday   = datetime.date.today() - datetime.timedelta(days=1)
TARGET_DATE = yesterday.strftime('%Y/%m/%d')
yr, mo      = yesterday.year, yesterday.month
days_in_mo  = calendar.monthrange(yr, mo)[1]

WORKSHEET    = f'{yr % 100}年{mo}月每日情況'
SHINKI_ROWS  = (SHINKI_START, SHINKI_START + days_in_mo - 1)
KAIKOU_ROWS  = (KAIKOU_START, KAIKOU_START + days_in_mo - 1)

print(f'集計日: {TARGET_DATE}', flush=True)
print(f'対象シート: {WORKSHEET}', flush=True)
print(f'新規行範囲: {SHINKI_ROWS}  回購行範囲: {KAIKOU_ROWS}', flush=True)

# ─── Google Sheets 接続 ──────────────────────────
creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
gc = gspread.authorize(creds)
sh = gc.open_by_key(SHEET_ID)

# ─── 新月シート自動作成 ──────────────────────────
def get_ws_name(y, m):
    return f'{y % 100}年{m}月每日情況'

def ensure_worksheet(sh, year, month):
    """当月シートがなければ前月から複製して月を書き換える"""
    ws_name   = get_ws_name(year, month)
    ws_titles = [w.title for w in sh.worksheets()]

    if ws_name in ws_titles:
        return sh.worksheet(ws_name)

    # 前月シートから複製
    if month == 1:
        prev_y, prev_m = year - 1, 12
    else:
        prev_y, prev_m = year, month - 1
    prev_name = get_ws_name(prev_y, prev_m)

    if prev_name not in ws_titles:
        raise ValueError(f'前月シート「{prev_name}」が見つかりません。手動で作成してください。')

    print(f'新月シート作成: {prev_name} → {ws_name}', flush=True)
    prev_ws = sh.worksheet(prev_name)

    # Google Sheets API でシートを複製
    sh.batch_update({'requests': [{'duplicateSheet': {
        'sourceSheetId': prev_ws.id,
        'newSheetName' : ws_name,
    }}]})
    new_ws = sh.worksheet(ws_name)

    # 全セルを取得して月・年テキストを置換
    old_m_str = f'{prev_m}月'
    new_m_str = f'{month}月'
    old_y_str = f'{prev_y % 100}年'
    new_y_str = f'{year % 100}年'

    all_vals = new_ws.get_all_values()
    batch_updates = []
    for r_i, row in enumerate(all_vals):
        for c_i, cell in enumerate(row):
            if old_m_str in cell or old_y_str in cell:
                new_val = cell.replace(old_m_str, new_m_str).replace(old_y_str, new_y_str)
                a1 = gspread.utils.rowcol_to_a1(r_i + 1, c_i + 1)
                batch_updates.append({'range': a1, 'values': [[new_val]]})
    if batch_updates:
        new_ws.batch_update(batch_updates, value_input_option='USER_ENTERED')
        print(f'  テキスト置換: {len(batch_updates)} セル更新', flush=True)

    # データ列 (B, C, E, F) をクリア（前月の数値を消す）
    prev_days = calendar.monthrange(prev_y, prev_m)[1]
    new_days  = calendar.monthrange(year, month)[1]
    clear_end = max(prev_days, new_days)  # 多い方に合わせてクリア

    clear_ranges = []
    for col in ['B', 'C', 'E', 'F']:
        # 新規セクション
        clear_ranges.append(f'{col}{SHINKI_START}:{col}{SHINKI_START + clear_end - 1}')
        # 回購セクション
        clear_ranges.append(f'{col}{KAIKOU_START}:{col}{KAIKOU_START + clear_end - 1}')
    new_ws.batch_clear(clear_ranges)
    print(f'  データ列クリア完了 ({len(clear_ranges)} 範囲)', flush=True)

    # 新月の方が前月より日数が多い場合、新しい日行を追加
    if new_days > prev_days:
        for extra_day in range(prev_days + 1, new_days + 1):
            # 新規セクション
            s_row = SHINKI_START + extra_day - 1
            k_row = KAIKOU_START + extra_day - 1
            day_label = f'{month}月{extra_day}日'
            new_ws.update_cell(s_row, 1, day_label)
            new_ws.update_cell(k_row, 1, day_label)
        print(f'  追加日行: {prev_days + 1}日〜{new_days}日', flush=True)

    print(f'✓ 新月シート「{ws_name}」の準備完了', flush=True)
    return new_ws

# ─── シート確保 ──────────────────────────────────
print('\n--- Google Sheets シート確認 ---', flush=True)
ws = ensure_worksheet(sh, yr, mo)
col_a = ws.col_values(1)
print('シート準備完了', flush=True)

# ─── Playwright helpers ──────────────────────────
def is_shinki(name, kws):
    return any(k in (name or '') for k in kws)

def find_row(col_a_cache, date_str, r0, r1):
    m = re.search(r'(\d{4})/(\d{2})/(\d{2})', date_str)
    if not m: return None
    needle = f'{int(m.group(2))}月{int(m.group(3))}日'
    for i in range(r0 - 1, min(r1, len(col_a_cache))):
        if needle in (col_a_cache[i] or ''):
            return i + 1
    return None

def wait_app(page, timeout_s=60):
    for _ in range(timeout_s // 2):
        page.wait_for_timeout(2000)
        if 'NEXTAGE' in page.locator('body').inner_text():
            return True
    return False

def do_login(page, user, pw):
    inputs = page.locator('input')
    cnt = inputs.count()
    if cnt >= 1:
        inputs.nth(0).click(); page.wait_for_timeout(200); inputs.nth(0).fill(user)
    if cnt >= 2:
        inputs.nth(1).click(); page.wait_for_timeout(200); inputs.nth(1).fill(pw)
    page.wait_for_timeout(300)
    btn = page.locator('button:has-text("登入"), button[type="submit"]')
    if btn.count() > 0: btn.first.click()
    else: page.keyboard.press('Enter')
    print('  ログイン送信。認証コードが必要な場合はブラウザで入力してください（5分待機）...', flush=True)
    for _ in range(150):
        page.wait_for_timeout(2000)
        if 'NEXTAGE' in page.locator('body').inner_text():
            return True
    return False

def goto_order_list2(page):
    page.mouse.click(30, 28); page.wait_for_timeout(2000)
    el = page.get_by_text('受注一覧2（1行1受注）', exact=True)
    if el.count() > 0: el.first.click()
    else:
        page.evaluate("""
            () => { for (const el of document.querySelectorAll('*'))
                if (el.childElementCount===0 && (el.innerText||'').includes('受注一覧2'))
                    { el.click(); break; } }
        """)
    page.wait_for_timeout(3000)
    for _ in range(10):
        page.wait_for_timeout(2000)
        if 'キャンペーン名' in page.locator('body').inner_text(): break

def set_filters(page, status_list, date):
    if status_list:
        page.evaluate(f"""
            () => {{ for (const cb of document.querySelectorAll('input[type="checkbox"]'))
                if ({status_list}.includes(cb.value) && !cb.checked) cb.click(); }}
        """)
        page.wait_for_timeout(300)
    page.evaluate("window.scrollTo(0, 0)"); page.wait_for_timeout(300)
    pos = page.evaluate("""
        () => {
            for (const el of document.querySelectorAll('*')) {
                if ((el.textContent||'').trim()==='受注日' && el.children.length===0) {
                    let p = el.parentElement;
                    for (let i=0;i<10;i++) {
                        if (!p) break;
                        const inp = Array.from(p.querySelectorAll('input[type="text"]'))
                            .filter(x => x.getBoundingClientRect().width>20
                                      && x.placeholder!=='HH:mm:ss');
                        if (inp.length>=2) {
                            const r0=inp[0].getBoundingClientRect(),r1=inp[1].getBoundingClientRect();
                            return [{x:r0.x+r0.width/2,y:r0.y+r0.height/2},
                                    {x:r1.x+r1.width/2,y:r1.y+r1.height/2}];
                        }
                        p = p.parentElement;
                    }
                }
            }
            return null;
        }
    """)
    if pos:
        for pt in pos:
            page.mouse.click(pt['x'], pt['y']); page.wait_for_timeout(150)
            page.keyboard.press('Control+a'); page.keyboard.type(date)

def read_page(page):
    return page.evaluate(f"""
        () => {{
            const res = [];
            for (const tr of document.querySelectorAll('tbody tr')) {{
                const cells = tr.querySelectorAll('td');
                if (cells.length >= 14) {{
                    const campaign = (cells[13].innerText||'').trim();
                    const amt = parseInt((cells[{AMOUNT_IDX}].innerText||'').replace(/,/g,'')) || 0;
                    res.push({{campaign, amount: amt}});
                }}
            }}
            return res;
        }}
    """)

def has_next(page):
    return page.evaluate("""
        () => { const b=document.querySelector('.js-list-next-button');
                return b ? !b.disabled : false; }
    """)

def read_all(page):
    rows = []
    for pg in range(1, 100):
        r = read_page(page)
        rows.extend(r)
        print(f'    第{pg}頁: {len(r)}筆', flush=True)
        if not r or not has_next(page): break
        page.evaluate("document.querySelector('.js-list-next-button').click()")
        page.wait_for_timeout(2000)
    return rows

# ─── Main: CROS 集計ループ ────────────────────────
errors = []

with sync_playwright() as p:
    for reg in REGIONS:
        print(f'\n{"━"*50}', flush=True)
        print(f'  {reg["name"]}  対象: {TARGET_DATE}', flush=True)
        print(f'{"━"*50}', flush=True)
        try:
            browser = p.chromium.launch(headless=True)   # 画面ロック中でも動作
            if os.path.exists(reg['session']):
                ctx = browser.new_context(storage_state=reg['session'])
            else:
                ctx = browser.new_context()
            page = ctx.new_page()

            page.goto('https://asp.acs-tpkg.com/service/cros/')
            wait_app(page, 40)

            if 'NEXTAGE' not in page.locator('body').inner_text():
                print('  セッション無効 → ログイン試みる', flush=True)
                # セッション期限切れ時は一時的に headless=False で再起動
                page.close(); ctx.close(); browser.close()
                browser = p.chromium.launch(headless=False)
                ctx = browser.new_context()
                page = ctx.new_page()
                page.goto('https://asp.acs-tpkg.com/service/cros/')
                wait_app(page, 40)
                ok = do_login(page, reg['user'], reg['pw'])
                if ok:
                    ctx.storage_state(path=reg['session'])
                    print('  ✓ ログイン成功・セッション更新', flush=True)
                else:
                    raise RuntimeError(f'{reg["name"]} ログイン失敗（認証コード未入力？）')
            else:
                print('  セッション有効', flush=True)

            goto_order_list2(page)
            set_filters(page, STATUS_FILTER, TARGET_DATE)
            page.locator('button:has-text("検索")').last.click()
            page.wait_for_timeout(5000)
            for _ in range(8):
                page.wait_for_timeout(2000)
                if '顧客ID' in page.locator('body').inner_text(): break

            all_rows = read_all(page)

            shinki = [r for r in all_rows if is_shinki(r['campaign'], reg['shinki_kw'])]
            kaikou = [r for r in all_rows if not is_shinki(r['campaign'], reg['shinki_kw'])]
            s_cnt, s_sale = len(shinki), sum(r['amount'] for r in shinki)
            k_cnt, k_sale = len(kaikou), sum(r['amount'] for r in kaikou)

            camp = Counter(r['campaign'] for r in all_rows)
            for name, cnt in camp.most_common():
                tag = '新規' if is_shinki(name, reg['shinki_kw']) else '回購'
                amt = sum(r['amount'] for r in all_rows if r['campaign'] == name)
                print(f'    [{tag}] {name!r}: {cnt}件 / {amt:,}', flush=True)
            print(f'  >>> 新規 {s_cnt}件 / SALE {s_sale:,}', flush=True)
            print(f'  >>> 回購 {k_cnt}件 / SALE {k_sale:,}', flush=True)

            r_s = find_row(col_a, TARGET_DATE, *SHINKI_ROWS)
            r_k = find_row(col_a, TARGET_DATE, *KAIKOU_ROWS)
            if r_s:
                ws.update_cell(r_s, reg['count_col'], s_cnt)
                ws.update_cell(r_s, reg['sale_col'],  s_sale)
                print(f'  ✓ 新規 Row {r_s} 書込完了', flush=True)
            else:
                print(f'  ⚠ 新規 row not found for {TARGET_DATE}', flush=True)
            if r_k:
                ws.update_cell(r_k, reg['count_col'], k_cnt)
                ws.update_cell(r_k, reg['sale_col'],  k_sale)
                print(f'  ✓ 回購 Row {r_k} 書込完了', flush=True)
            else:
                print(f'  ⚠ 回購 row not found for {TARGET_DATE}', flush=True)

        except Exception as e:
            msg = f'{reg["name"]} エラー: {e}'
            print(f'  ✗ {msg}', flush=True)
            traceback.print_exc(file=sys.stdout)
            errors.append(msg)
        finally:
            try: ctx.close()
            except: pass
            try: browser.close()
            except: pass

# ─── 完了 ────────────────────────────────────────
print(f'\n{"="*60}', flush=True)
if errors:
    print(f'[完了 - {len(errors)}件のエラーあり]', flush=True)
    for e in errors: print(f'  ✗ {e}', flush=True)
else:
    print('[完了 - 全成功]', flush=True)
print(f'[{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}]', flush=True)
_log_file.close()
