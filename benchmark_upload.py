# -*- coding: utf-8 -*-
"""
benchmark_upload.py  —  Benchmark Email 聯絡人名單自動上傳

Usage:
  python benchmark_upload.py mode1             # 更新 TW + HK 新顧客名單
  python benchmark_upload.py mode2 0601 0622   # 建立購買過名單（MMDD MMDD）
"""

import sys, io, os, re, csv, datetime, calendar, tempfile, time, argparse, traceback

from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── 帳密 ─────────────────────────────────────────────
def load_config():
    cfg = {}
    with open(os.path.join(BASE_DIR, 'config.txt'), 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                cfg[k.strip()] = v.strip()
    return cfg

_cfg = load_config()
CROS_URL = 'https://asp.acs-tpkg.com/service/cros/'
TW_REG   = {'name':'TW','session':os.path.join(BASE_DIR,'session_tw.json'),'user':_cfg['TW_USER'],'pw':_cfg['TW_PASS']}
HK_REG   = {'name':'HK','session':os.path.join(BASE_DIR,'session_hk.json'),'user':_cfg['HK_USER'],'pw':_cfg['HK_PASS']}

BM_EMAIL = 'nextagetw@c-nextage.com'
BM_PASS  = '20220304'
BM_URL   = 'https://ui.benchmarkemail.com'
BM_SESSION = os.path.join(BASE_DIR, 'session_bm.json')

TW_PREFIX = 'V_(新)顧客名單_含生日~'
HK_PREFIX = 'Vhk_(新)顧客名單_含生日~'

GSHEET_URL     = 'https://docs.google.com/spreadsheets/d/1FSJnFhVNu7DNtLvercxrh-c4OaGpZd9el28kaM2QkYw/edit?gid=631490487'
GSHEET_SESSION = os.path.join(BASE_DIR, 'session_google.json')

# ──────────────────────────────────────────────────────
# CROS 部分
# ──────────────────────────────────────────────────────

def cros_wait_app(page, timeout_s=60):
    for _ in range(timeout_s // 2):
        page.wait_for_timeout(2000)
        if 'NEXTAGE' in page.locator('body').inner_text():
            return True
    return False

def cros_login(page, user, pw):
    inputs = page.locator('input')
    if inputs.count() >= 1:
        inputs.nth(0).click(); page.wait_for_timeout(200); inputs.nth(0).fill(user)
    if inputs.count() >= 2:
        inputs.nth(1).click(); page.wait_for_timeout(200); inputs.nth(1).fill(pw)
    page.wait_for_timeout(300)
    btn = page.locator('button:has-text("登入"), button[type="submit"]')
    if btn.count() > 0: btn.first.click()
    else: page.keyboard.press('Enter')
    print('  ログイン送信（認証コードが必要な場合は手動入力）')
    for _ in range(150):
        page.wait_for_timeout(2000)
        if 'NEXTAGE' in page.locator('body').inner_text():
            return True
    return False

def query_cros_emails(reg, date_from, date_to):
    """
    CROS 受注顧客ターゲットリスト作成 で期間検索し、email リストを返す。
    date_from / date_to: datetime.date
    """
    print(f'  [{reg["name"]}] CROS 検索: {date_from} → {date_to}')
    emails = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx_kw  = {'viewport': {'width':1280,'height':900}}
        if os.path.exists(reg['session']):
            ctx_kw['storage_state'] = reg['session']
        ctx  = browser.new_context(**ctx_kw)
        page = ctx.new_page()

        page.goto(CROS_URL)
        cros_wait_app(page, 30)

        if 'NEXTAGE' not in page.locator('body').inner_text():
            print(f'  [{reg["name"]}] セッション無効 → ログイン')
            page.close(); ctx.close(); browser.close()
            browser = pw.chromium.launch(headless=False)
            ctx  = browser.new_context(viewport={'width':1280,'height':900})
            page = ctx.new_page()
            page.goto(CROS_URL)
            cros_wait_app(page, 40)
            if not cros_login(page, reg['user'], reg['pw']):
                browser.close()
                raise RuntimeError(f'{reg["name"]} CROS ログイン失敗')
            ctx.storage_state(path=reg['session'])
            print(f'  [{reg["name"]}] ✓ ログイン・セッション保存')

        # 受注顧客ターゲットリスト作成 へ移動
        page.mouse.click(30, 28)
        page.wait_for_timeout(2000)
        page.get_by_text('受注顧客ターゲットリスト作成', exact=True).first.click()
        page.wait_for_timeout(3000)

        # 期間入力（inputs[0]=start, inputs[1]=end）
        d_start = date_from.strftime('%Y/%m/%d')
        d_end   = date_to.strftime('%Y/%m/%d')
        inps    = page.locator('input[type="text"]')
        inps.nth(0).click(); page.keyboard.press('Control+a'); page.keyboard.type(d_start)
        page.wait_for_timeout(200)
        inps.nth(1).click(); page.keyboard.press('Control+a'); page.keyboard.type(d_end)
        page.wait_for_timeout(200)

        # 検索
        page.locator('button:has-text("検索")').last.click()
        page.wait_for_timeout(5000)
        for _ in range(10):
            page.wait_for_timeout(2000)
            body = page.locator('body').inner_text()
            if '顧客ID' in body or '該当するデータがありません' in body:
                break

        if '該当するデータがありません' in page.locator('body').inner_text():
            print(f'  [{reg["name"]}] データなし（{d_start}〜{d_end}）')
            ctx.close(); browser.close()
            return []

        # CSV ダウンロード
        csv_path = os.path.join(tempfile.gettempdir(),
                                f'cros_{reg["name"]}_{date_from:%Y%m%d}_{date_to:%Y%m%d}.csv')
        with page.expect_download() as dl_info:
            page.locator('button:has-text("検索結果ダウンロード")').click()
        dl_info.value.save_as(csv_path)
        print(f'  [{reg["name"]}] CSV saved: {csv_path}')

        ctx.close(); browser.close()

    # email 抽出
    with open(csv_path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        cols   = reader.fieldnames or []
        email_col = next((c for c in cols if c.lower() == 'email'), None) \
                 or next((c for c in cols if 'mail' in c.lower()), None)
        if not email_col and cols:
            # fallback: index 5 (0-based)
            email_col = cols[5] if len(cols) > 5 else cols[0]
        for row in reader:
            em = (row.get(email_col) or '').strip().lower()
            if em and '@' in em:
                emails.append(em)

    print(f'  [{reg["name"]}] {len(emails)} emails found')
    return emails

# ──────────────────────────────────────────────────────
# Benchmark Email 部分
# ──────────────────────────────────────────────────────

def bm_login(page):
    # 有保存的 session 先試
    if os.path.exists(BM_SESSION):
        try:
            page.goto(BM_URL + '/lists', wait_until='networkidle', timeout=20000)
            time.sleep(2)
            if 'login' not in page.url:
                print('  [BM] セッション有効')
                return
        except: pass

    page.goto(BM_URL + '/login', wait_until='domcontentloaded', timeout=30000)
    page.wait_for_selector('input[name="login"]', timeout=15000)
    page.locator('input[name="login"]').fill(BM_EMAIL)
    page.locator('input[name="password"]').fill(BM_PASS)
    remember = page.locator('input[name="remember-login"]')
    if remember.count() > 0 and not remember.is_checked():
        remember.check()
    page.locator('input[name="password"]').press('Enter')
    page.wait_for_function("() => !window.location.pathname.includes('login')", timeout=20000)
    # 保存 session
    page.context.storage_state(path=BM_SESSION)
    print('  [BM] ログイン完了・セッション保存')

def bm_goto_lists(page):
    try:
        page.goto(BM_URL + '/lists', wait_until='networkidle', timeout=20000)
    except: pass
    time.sleep(2)
    # 1ページあたり 100 件表示
    try:
        page.locator('select.form-control').select_option('100')
        time.sleep(2)
    except Exception:
        pass

def _scan_lists_for_prefix(page, prefix):
    """現在ページから prefix に一致するリストを探す。"""
    return page.evaluate(f"""
        () => {{
            for (const a of document.querySelectorAll('a[href*="lists/detail"]')) {{
                const name = (a.textContent||'').trim();
                if (name.startsWith('{prefix}')) {{
                    const m = a.href.match(/id=(\\d+)/);
                    if (m) return {{name, id: m[1]}};
                }}
            }}
            return null;
        }}
    """)

def bm_find_list(page, prefix):
    """
    名前が prefix で始まるリストを探す。全ページを巡回。
    Returns {'name': ..., 'id': ...} or None
    """
    bm_goto_lists(page)
    result = _scan_lists_for_prefix(page, prefix)
    if result:
        return result

    # 次ページがあれば巡回（最大5ページ）
    for _ in range(5):
        next_btn = page.evaluate(r"""
            () => {
                for (const a of document.querySelectorAll('.pagination a,a[name]')) {
                    const name = a.getAttribute('name')||'';
                    const label = a.getAttribute('aria-label')||'';
                    if (name.includes('next') || label.toLowerCase().includes('next')) {
                        const r = a.getBoundingClientRect();
                        if (r.width > 0) return {x: r.x+r.width/2, y: r.y+r.height/2};
                    }
                }
                // Also try "nextPage" name
                const np = document.querySelector('a[name="nextPage"]');
                if (np) {
                    const r = np.getBoundingClientRect();
                    if (r.width > 0) return {x: r.x+r.width/2, y: r.y+r.height/2};
                }
                return null;
            }
        """)
        if not next_btn:
            break
        page.mouse.click(next_btn['x'], next_btn['y'])
        time.sleep(2)
        result = _scan_lists_for_prefix(page, prefix)
        if result:
            return result
    return None

def _click_visible_btn(page, text):
    """visibility:visible のボタンを座標クリック。複数 overlay がある場合に有効。"""
    pos = page.evaluate(f"""
        () => {{
            for (const b of document.querySelectorAll('button')) {{
                const s = window.getComputedStyle(b);
                if ((b.textContent||'').trim()==='{text}' && s.visibility==='visible') {{
                    const r = b.getBoundingClientRect();
                    if (r.width > 0) return {{x: r.x+r.width/2, y: r.y+r.height/2}};
                }}
            }}
            return null;
        }}
    """)
    if pos:
        page.mouse.move(pos['x'], pos['y']); time.sleep(0.2)
        page.mouse.click(pos['x'], pos['y'])
        return True
    return False

def _click_btn(page, text):
    """visibility 無視でボタン座標クリック（編輯・儲存後完成など）。"""
    pos = page.evaluate(f"""
        () => {{
            for (const b of document.querySelectorAll('button')) {{
                if ((b.textContent||'').trim()==='{text}') {{
                    const r = b.getBoundingClientRect();
                    if (r.width > 0) return {{x: r.x+r.width/2, y: r.y+r.height/2}};
                }}
            }}
            return null;
        }}
    """)
    if pos:
        page.mouse.click(pos['x'], pos['y']); return True
    return False

def bm_upload_to_list(page, list_id, csv_path):
    """既存リストに CSV をアップロード。"""
    upload_url = f'{BM_URL}/contacts/add/upload?contact_master_id={list_id}&redir='
    page.goto(upload_url, wait_until='networkidle', timeout=20000)
    time.sleep(2)

    # ファイル選択
    page.locator('input[type="file"]').first.set_input_files(csv_path)
    time.sleep(2)

    # 下一步（アップロード開始）— visible ボタンを探す
    _click_visible_btn(page, '下一步')

    # /mapping ページを待つ
    for _ in range(20):
        time.sleep(1)
        if 'mapping' in page.url:
            break

    # mapping: email 列が自動マッピング済み → 儲存後完成
    time.sleep(2)
    _click_btn(page, '儲存後完成')
    time.sleep(5)
    print(f'  [BM] Upload complete: list={list_id}')

def bm_rename_list(page, list_id, new_name):
    """リスト名を変更。"""
    page.goto(f'{BM_URL}/lists/detail?id={list_id}', wait_until='networkidle', timeout=20000)
    time.sleep(2)

    edit_pos = page.evaluate("""
        () => {
            for (const b of document.querySelectorAll('button')) {
                if ((b.textContent||'').trim()==='編輯') {
                    const r = b.getBoundingClientRect();
                    if (r.width > 0) return {x: r.x+r.width/2, y: r.y+r.height/2};
                }
            }
            return null;
        }
    """)
    if not edit_pos:
        raise RuntimeError(f'編輯 button not found for list {list_id}')

    page.mouse.click(edit_pos['x'], edit_pos['y'])
    time.sleep(2)

    name_inp = page.locator('.overlay-screen.open input[type="text"]').first
    name_inp.click(click_count=3)
    name_inp.fill(new_name)
    time.sleep(0.3)
    name_inp.press('Enter')
    time.sleep(3)
    print(f'  [BM] Renamed list {list_id} → {new_name!r}')

def bm_create_list_upload(page, list_name, csv_path):
    """新規リスト作成 + CSV アップロード。新リスト ID を返す。"""
    bm_goto_lists(page)

    # 建立新聯絡人名單
    _click_btn(page, '建立新聯絡人名單')
    time.sleep(2)

    # Step1: 一般名單（default） → 下一步
    _click_visible_btn(page, '下一步')
    time.sleep(2)

    # Step2: 從檔案匯入（default） → 下一步
    _click_visible_btn(page, '下一步')
    time.sleep(2)

    # Step3: 名單名稱 input
    name_inp = page.locator('.overlay-screen.open input[type="text"], input[type="text"]').first
    name_inp.click(click_count=3)
    name_inp.fill(list_name)
    time.sleep(0.3)

    # 下一步 → upload URL（新リスト ID が URL に入る）
    _click_visible_btn(page, '下一步')
    for _ in range(30):
        time.sleep(1)
        if 'upload' in page.url and 'contact_master_id' in page.url:
            break

    m = re.search(r'contact_master_id=(\d+)', page.url)
    list_id = m.group(1) if m else None
    if not list_id:
        # フォールバック: アップロード後に名前検索で ID を取得
        print(f'  [BM] URL に list_id なし (URL={page.url}) — アップロード後に名前検索')
    else:
        print(f'  [BM] New list created: {list_name!r}, id={list_id}')

    # ファイル選択
    page.locator('input[type="file"]').first.set_input_files(csv_path)
    time.sleep(2)

    # 下一步
    _click_visible_btn(page, '下一步')
    for _ in range(20):
        time.sleep(1)
        if 'mapping' in page.url:
            break

    time.sleep(2)
    _click_btn(page, '儲存後完成')
    time.sleep(5)

    # ID が取れていない場合は名前検索でリカバリ
    if not list_id:
        try:
            info = bm_find_list(page, list_name)
            list_id = info['id'] if info else None
        except Exception:
            pass
    print(f'  [BM] New list upload complete: {list_name!r}, id={list_id}')
    return list_id

def save_emails_csv(emails, path):
    """メールリストを CSV に保存。"""
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f).writerow(['email'])
        for e in emails:
            csv.writer(f).writerow([e])
    print(f'  CSV: {path} ({len(emails)} emails)')

# ──────────────────────────────────────────────────────
# Google Sheets 聯絡人主表 更新
# ──────────────────────────────────────────────────────

def click_gsheet_button():
    """Google Sheets の「更新聯絡人主表」ボタンをクリック。"""
    print('\n[GSheet] 聯絡人主表 更新中...')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx_kw  = {'viewport': {'width': 1440, 'height': 900}}
        if os.path.exists(GSHEET_SESSION):
            ctx_kw['storage_state'] = GSHEET_SESSION
        ctx  = browser.new_context(**ctx_kw)
        page = ctx.new_page()

        page.goto(GSHEET_URL, wait_until='networkidle', timeout=30000)

        # Google ログインが必要な場合は手動待機
        if 'accounts.google.com' in page.url or 'ServiceLogin' in page.url:
            print('  [GSheet] Google ログインが必要です。ブラウザでログインしてください（3分以内）')
            page.wait_for_function(
                "() => window.location.hostname === 'docs.google.com'",
                timeout=180000)
            ctx.storage_state(path=GSHEET_SESSION)

        # シートのロードを待つ
        time.sleep(8)

        # ── Strategy 1: aria-label / title 属性で検索 ──
        pos = page.evaluate("""
            () => {
                const keywords = ['更新聯絡人主表', '更新'];
                for (const kw of keywords) {
                    for (const attr of ['aria-label','title','data-tooltip']) {
                        for (const el of document.querySelectorAll(`[${attr}*="${kw}"]`)) {
                            const r = el.getBoundingClientRect();
                            if (r.width > 0) {
                                return {x: r.x+r.width/2, y: r.y+r.height/2,
                                        label: el.getAttribute(attr)};
                            }
                        }
                    }
                }
                return null;
            }
        """)

        if not pos:
            # ── Strategy 2: iframe 内を検索 ──
            for frame in page.frames:
                try:
                    pos = frame.evaluate("""
                        () => {
                            for (const el of document.querySelectorAll('[aria-label],[role="button"]')) {
                                const txt = (el.textContent||el.getAttribute('aria-label')||'').trim();
                                if (txt.includes('更新') && txt.includes('聯絡人')) {
                                    const r = el.getBoundingClientRect();
                                    if (r.width > 0) return {x:r.x+r.width/2, y:r.y+r.height/2, label:txt};
                                }
                            }
                            return null;
                        }
                    """)
                    if pos:
                        break
                except Exception:
                    continue

        if not pos:
            # ── Strategy 3: テキストノードで検索 ──
            pos = page.evaluate("""
                () => {
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    let node;
                    while ((node = walker.nextNode())) {
                        if (node.textContent.includes('更新聯絡人主表')) {
                            const el = node.parentElement;
                            const r = el.getBoundingClientRect();
                            if (r.width > 0) return {x:r.x+r.width/2, y:r.y+r.height/2, label:'text:'+node.textContent.trim()};
                        }
                    }
                    return null;
                }
            """)

        if pos:
            page.mouse.click(pos['x'], pos['y'])
            print(f'  [GSheet] ✓ ボタンクリック: {pos.get("label","")}')
            time.sleep(15)  # スクリプト実行を待つ
        else:
            # スクリーンショットを保存してログに残す
            ss_path = os.path.join(BASE_DIR, 'logs', 'gsheet_debug.png')
            os.makedirs(os.path.dirname(ss_path), exist_ok=True)
            page.screenshot(path=ss_path)
            print(f'  [GSheet] ⚠ ボタンが見つかりません。スクリーンショット: {ss_path}')

        ctx.storage_state(path=GSHEET_SESSION)
        ctx.close()
        browser.close()

# ──────────────────────────────────────────────────────
# Mode 1: 新顧客名単 更新
# ──────────────────────────────────────────────────────

def mode1():
    today = datetime.date.today()
    # 先月の同日をカットオフに（月末超え対応: 7/31→6/30, 3/31→2/28）
    prev_month = today.month - 1 if today.month > 1 else 12
    prev_year  = today.year if today.month > 1 else today.year - 1
    last_of_prev = calendar.monthrange(prev_year, prev_month)[1]
    new_cutoff = datetime.date(prev_year, prev_month, min(today.day, last_of_prev))

    print(f'Today: {today}  /  New cutoff: {new_cutoff} ({new_cutoff:%m%d})')

    targets = [
        (TW_REG, TW_PREFIX),
        (HK_REG, HK_PREFIX),
    ]

    with sync_playwright() as pw:
        browser  = pw.chromium.launch(headless=False, slow_mo=300)
        ctx_kw   = {'viewport': {'width':1280,'height':900}}
        if os.path.exists(BM_SESSION):
            ctx_kw['storage_state'] = BM_SESSION
        bm_ctx   = browser.new_context(**ctx_kw)
        bm_page  = bm_ctx.new_page()
        bm_login(bm_page)

        for cros_reg, prefix in targets:
            print(f'\n{"─"*50}')
            print(f'  {cros_reg["name"]}  prefix={prefix!r}')

            info = bm_find_list(bm_page, prefix)
            if not info:
                print(f'  ⚠ List not found: {prefix!r}')
                continue

            list_name = info['name']
            list_id   = info['id']
            print(f'  Found: {list_name!r}  (id={list_id})')

            # 現在の MMDD を解析
            m = re.search(r'~(\d{4})$', list_name)
            if not m:
                print(f'  ⚠ Cannot parse MMDD from {list_name!r}')
                continue

            old_mmdd = m.group(1)
            try:
                old_cutoff = new_cutoff.replace(
                    month=int(old_mmdd[:2]), day=int(old_mmdd[2:]))
            except ValueError:
                print(f'  ⚠ Invalid date in list name: {old_mmdd}')
                continue

            if old_cutoff >= new_cutoff:
                print(f'  ✓ Already up-to-date ({list_name}), skip')
                continue

            date_from = old_cutoff + datetime.timedelta(days=1)
            date_to   = new_cutoff
            print(f'  Query: {date_from} → {date_to}')

            # CROS で email 取得
            emails = query_cros_emails(cros_reg, date_from, date_to)

            new_list_name = re.sub(r'~\d{4}$', f'~{new_cutoff:%m%d}', list_name)

            if emails:
                csv_path = os.path.join(
                    tempfile.gettempdir(),
                    f'bm_{cros_reg["name"]}_{date_from:%Y%m%d}.csv')
                save_emails_csv(emails, csv_path)
                bm_upload_to_list(bm_page, list_id, csv_path)
            else:
                print(f'  No emails for range → rename only')

            bm_rename_list(bm_page, list_id, new_list_name)

        bm_ctx.storage_state(path=BM_SESSION)
        bm_ctx.close(); browser.close()

    # Google Sheets 聯絡人主表を更新
    click_gsheet_button()

    print('\n=== Mode 1 完了 ===')

# ──────────────────────────────────────────────────────
# Mode 2: 購買過名単 作成
# ──────────────────────────────────────────────────────

def mode2(mmdd_from, mmdd_to):
    today     = datetime.date.today()
    date_from = datetime.date(today.year, int(mmdd_from[:2]), int(mmdd_from[2:]))
    date_to   = datetime.date(today.year, int(mmdd_to[:2]),   int(mmdd_to[2:]))
    list_name = f'{mmdd_from}~{mmdd_to}購買過名單'

    print(f'Mode 2: {date_from} → {date_to}  /  List: {list_name!r}')

    tw_emails = query_cros_emails(TW_REG, date_from, date_to)
    hk_emails = query_cros_emails(HK_REG, date_from, date_to)

    # 重複排除
    all_emails = list(dict.fromkeys(tw_emails + hk_emails))
    print(f'\nTotal (deduped): {len(all_emails)} emails')

    csv_path = os.path.join(tempfile.gettempdir(), f'bm_mode2_{mmdd_from}_{mmdd_to}.csv')
    save_emails_csv(all_emails, csv_path)

    with sync_playwright() as pw:
        browser  = pw.chromium.launch(headless=False, slow_mo=300)
        ctx_kw   = {'viewport': {'width':1280,'height':900}}
        if os.path.exists(BM_SESSION):
            ctx_kw['storage_state'] = BM_SESSION
        bm_ctx  = browser.new_context(**ctx_kw)
        bm_page = bm_ctx.new_page()
        bm_login(bm_page)
        bm_create_list_upload(bm_page, list_name, csv_path)
        bm_ctx.storage_state(path=BM_SESSION)
        bm_ctx.close(); browser.close()

    print(f'\n=== Mode 2 完了: {list_name!r} ===')

# ──────────────────────────────────────────────────────

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    parser = argparse.ArgumentParser(description='Benchmark Email 聯絡人名單自動上傳')
    parser.add_argument('mode', choices=['mode1', 'mode2'])
    parser.add_argument('mmdd_from', nargs='?', help='Mode 2 開始日 MMDD')
    parser.add_argument('mmdd_to',   nargs='?', help='Mode 2 結束日 MMDD')
    args = parser.parse_args()

    try:
        if args.mode == 'mode1':
            mode1()
        else:
            if not args.mmdd_from or not args.mmdd_to:
                parser.error('mode2 requires mmdd_from and mmdd_to (e.g. 0601 0622)')
            mode2(args.mmdd_from, args.mmdd_to)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
