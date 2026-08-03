"""
民大自动打卡 v17 - 验证码OCR版
=============================
v17 变更:
- CAS 新增验证码, 使用 ddddocr 进行自动识别
- 识别失败 → 截图 + 放弃, 不再误提交
- 配合 GitHub Actions 安装 ddddocr

v16 变更:
- do_cas_login() 返回 (success, reason)
- 登录失败 → 立即中止
"""
import os, sys, time, json, traceback
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PT

BJT = timezone(timedelta(hours=8))

SCHOOL_LAT = 30.562897
SCHOOL_LNG = 103.966624
WXWEB = "https://gyglxt.swun.edu.cn/wxweb/"
COOKIE_FILE = "swun_cookies.json"

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

USERNAME = os.environ.get("SWUN_USERNAME") or ""
PASSWORD = os.environ.get("SWUN_PASSWORD") or ""


def in_checkin_window():
    """Check-in window: 21:30 - 23:25 BJT (server-side enforced)."""
    now = datetime.now(BJT)
    return (
        (now.hour == 21 and now.minute >= 30) or
        now.hour == 22 or
        (now.hour == 23 and now.minute <= 25)
    )


def window_status():
    """Human-readable window status for logging."""
    now = datetime.now(BJT)
    return f"{now.strftime('%H:%M')} BJT — {'IN window' if in_checkin_window() else 'OUTSIDE window'}"


def log(msg):
    safe = msg.encode("ascii", errors="replace").decode("ascii")
    print(f"[{datetime.now(BJT).strftime('%H:%M:%S')}] {safe}")


def save_cookies(context):
    try:
        cookies = context.cookies()
        with open(COOKIE_FILE, "w") as f:
            json.dump(cookies, f)
        log(f"Saved {len(cookies)} cookies")
    except Exception as e:
        log(f"Cookie save err: {e}")


def load_cookies(context):
    try:
        if os.path.exists(COOKIE_FILE):
            with open(COOKIE_FILE) as f:
                cookies = json.load(f)
                if cookies:
                    context.add_cookies(cookies)
                    log(f"Loaded {len(cookies)} cookies")
                    return True
    except:
        pass
    return False


def do_cas_login(page):
    """Returns (success, error_reason)."""
    try:
        page.click("#userNameLogin_a")
    except Exception:
        return False, "userNameLogin_a button not found"

    page.wait_for_timeout(2000)

    # Check for captcha — CAS added this around 2026-07-31
    captcha_info = page.evaluate("""(function() {
        var c = document.querySelector('#captcha, #randCode, [name="captcha"], [name="randCode"]');
        if (c) return {found: true, id: c.id || c.name, tag: c.tagName};
        var imgs = document.querySelectorAll('img');
        for (var i of imgs) { if (i.src && i.src.includes('captcha')) return {found: true, img: i.src}; }
        return {found: false};
    })()""")

    if captcha_info.get("found"):
        log("Captcha detected — running OCR...")

        try:
            import ddddocr
        except ImportError:
            log("ddddocr not installed")
            return False, "ocr library missing"

        # First, we must make the captcha <img> visible.
        # CAS generates a fresh captcha on page load — we need to trigger it.
        page.evaluate("""(function() {
            // Click the captcha refresh element to generate the captcha image
            var refresh = document.querySelector('#captchaImg, img[id*="captcha"], img[src*="captcha"], [onclick*="captcha"], [onclick*="Captcha"]');
            if (refresh) { refresh.click(); return 'clicked_captcha_img'; }
            // Try clicking common refresh links
            var links = document.querySelectorAll('a');
            for (var i = 0; i < links.length; i++) {
                if ((links[i].onclick && links[i].onclick.toString().includes('captcha')) ||
                    links[i].innerText.includes('换') || links[i].innerText.includes('刷新')) {
                    links[i].click(); return 'clicked_refresh_link';
                }
            }
            // Try the captcha icon img[8] which was captcha1.png (40x40)
            var imgs = document.querySelectorAll('img');
            for (var j = 0; j < imgs.length; j++) {
                var src = imgs[j].src || '';
                if (src.includes('captcha')) { imgs[j].click(); return 'clicked_captcha_icon_' + j; }
            }
            return 'no_refresh_found';
        })()""")

        # Wait for the captcha image to load
        page.wait_for_timeout(3000)

        # Now try to capture the captcha image
        captcha_bytes = None

        # img[8] was captcha1.png icon — clicking it should refresh #captchaImg
        # img[9] is #captchaImg but size=0x0 initially — needs click to load
        captcha_selectors = [
            "#captchaImg",
            "img[id*='captcha']",
            "img[id*='Captcha']",
            'img[src*="captcha"]',
        ]

        for sel in captcha_selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0:
                    # Check if the image actually loaded
                    is_loaded = page.evaluate(f"""(function() {{
                        var img = document.querySelector('{sel}');
                        return img && img.naturalWidth > 0 && img.naturalHeight > 0;
                    }})()""")
                    if not is_loaded:
                        log(f"'{sel}' found but not loaded (size=0x0), skipping")
                        continue
                    captcha_bytes = el.screenshot(timeout=5000)
                    log(f"Captured captcha via '{sel}' ({len(captcha_bytes)} bytes)")
                    break
            except Exception as e:
                log(f"'{sel}' failed: {e}")
                continue

        if not captcha_bytes:
            # Last resort: full page screenshot
            captcha_bytes = page.screenshot(full_page=False)

        if captcha_bytes:
            with open("daka_captcha_raw.png", "wb") as f:
                f.write(captcha_bytes)
            ocr = ddddocr.DdddOcr(show_ad=False)
            code = (ocr.classification(captcha_bytes) or "").strip().lower()
            log(f"OCR: '{code}'")

            if code and len(code) >= 4:
                captcha_input_id = captcha_info.get("id") or "captcha"
                page.fill(f"#{captcha_input_id}", code)
                log(f"Filled captcha: {code}")
            else:
                log(f"OCR unreliable (len={len(code)}): '{code}'")
                return False, f"OCR unreliable: '{code}'"
        else:
            log("No captcha image found at all")
            return False, "no captcha image"

    page.fill("#username", USERNAME)
    page.fill("#password", PASSWORD)
    salt = page.evaluate("(document.getElementById('pwdEncryptSalt')||{}).value") or "rjBFAaHsNkKAhpoi"
    log(f"Encrypt salt: {salt[:20]}...")

    encrypted = page.evaluate(f"""encryptPassword(document.getElementById('password').value, "{salt}")""")
    page.evaluate(f"""document.getElementById('password').value = "{encrypted}"; document.getElementById('saltPassword').value = "{encrypted}";""")

    log("Submitting CAS form...")
    page.screenshot(path="daka_cas.png")
    page.evaluate("document.querySelector('form').submit()")
    page.wait_for_timeout(10000)

    url = page.url
    log(f"After CAS: {url[:120]}")
    page.screenshot(path="daka_cas_result.png")

    # If we're still on the authserver login page — login failed
    if "authserver" in url and "login" in url:
        # Try to read the error message
        error_text = page.evaluate("""(function() {
            var e = document.querySelector('.error, .msg, .alert, [id*="error"], [id*="msg"]');
            return e ? e.innerText || e.textContent : '';
        })()""")
        log(f"CAS ERROR: {error_text[:200] if error_text else 'no error message found'}")
        return False, f"CAS rejected: {error_text[:100] if error_text else 'unknown'}"

    return ("wxweb" in url or "appcas" in url), None


def find_and_click_clock(page):
    """Locate and click the check-in circle."""

    # Phase 1: Wait for Vue SPA to render actual content
    body = ""
    for i in range(30):
        body = page.locator("body").inner_text().strip()
        if len(body) > 10:
            break
        if i == 0:
            log("Waiting for SPA to render...")
        page.wait_for_timeout(1000)
    else:
        log("FATAL: Page still blank after 30s — SPA did not mount")
        page.screenshot(path="daka_error.png")
        return False

    with open("page_text.txt", "w", encoding="utf-8") as f:
        f.write(body)
    log(f"Page rendered: {len(body)} chars")
    page.screenshot(path="daka_clock.png", full_page=True)

    if "已打卡" in body or "签到成功" in body:
        log("ALREADY CHECKED IN TODAY")
        return True

    # Phase 2: Wait for queryPersonDetailInfo API — up to 3 minutes
    # This API is the gatekeeper; the page is unusable until it returns
    for i in range(90):
        toast_visible = page.evaluate("""
            (function() {
                var t = document.querySelector('.van-toast--loading, .van-loading');
                if (t && window.getComputedStyle(t).display !== 'none') return true;
                var tt = document.querySelector('.van-toast__text');
                if (tt && (tt.textContent.includes('queryPerson') || tt.textContent.includes('\\u52a0\\u8f7d'))) return true;
                return false;
            })()
        """)
        if toast_visible:
            if i == 0:
                log("Waiting for queryPersonDetailInfo API (up to 3min)...")
            page.wait_for_timeout(2000)
        else:
            log(f"API loaded ({i * 2}s)")
            break
    else:
        log("FATAL: queryPersonDetailInfo API never completed (3min)")
        page.screenshot(path="daka_error.png")
        return False

    # ⌛ 最后防线：点击前确认仍在窗口内
    if not in_checkin_window():
        log(f"Window closed before click! {window_status()}")
        log("Aborting to avoid server rejection.")
        return True

    # Phase 3: Click the circle
    circle = page.locator(".position-circle")
    if circle.count() == 0:
        log("No .position-circle found")
        page.screenshot(path="daka_error.png")
        return False

    circ_box = circle.first.bounding_box()
    if circ_box:
        cx = circ_box['x'] + circ_box['width'] / 2
        cy = circ_box['y'] + circ_box['height'] / 2
        log(f"Clicking at ({cx:.0f}, {cy:.0f})")
        page.mouse.click(cx, cy)
    else:
        circle.first.click()

    # Phase 4: Wait for result — up to 30s
    for i in range(15):
        page.wait_for_timeout(2000)
        toast = page.evaluate("""
            (function() {
                var t = document.querySelector('.van-toast__text');
                var d = document.querySelector('.van-dialog__message');
                return {toast: t ? t.textContent : '', dialog: d ? d.textContent : ''};
            })()
        """)
        log(f"After click {i*2}s — Toast: {toast['toast'][:80]}, Dialog: {toast['dialog'][:80]}")

        if "成功" in toast['toast'] or "签到成功" in toast['toast']:
            log("CHECK-IN SUCCESSFUL!")
            page.screenshot(path="daka_done.png")
            return True
        if "已打卡" in toast['toast'] or "已经打卡" in toast['toast']:
            log("ALREADY CHECKED IN TODAY")
            return True
        if "失败" in toast['toast'] or "不在" in toast['toast']:
            log(f"Check-in rejected: {toast['toast'][:120]}")
            page.screenshot(path="daka_done.png")
            return False

        # Also check if loading toast re-appeared (server is processing)
        still_loading = page.evaluate("""
            (function() {
                var t = document.querySelector('.van-toast--loading');
                return t && window.getComputedStyle(t).display !== 'none';
            })()
        """)
        if still_loading:
            log("Server still processing, waiting...")

    log("Result unclear after 30s — assuming success (check manually)")
    page.screenshot(path="daka_done.png")
    return True


def do_checkin(headless=True, force=False):
    """Main entry. force=True skips all time-window checks."""

    now = datetime.now(BJT)

    if not in_checkin_window() and not force:
        log(f"{window_status()} — will poll every 2min (max 3h)...")
        deadline = now + timedelta(hours=3)
        while True:
            time.sleep(120)
            now = datetime.now(BJT)
            if in_checkin_window():
                log(f"Window open! {window_status()}")
                break
            if now > deadline:
                log("Poll timeout (3h elapsed), giving up")
                return True
            if now.hour >= 23 and now.minute > 25:
                log("Window already closed for today, giving up")
                return True
            log(f"Still waiting... ({now.strftime('%H:%M')} BJT)")

    if force and not in_checkin_window():
        log(f"WARNING: {window_status()} — API calls may fail (code 500).")

    log("=" * 60)
    log(f"v17 - Starting check-in at {now.strftime('%Y-%m-%d %H:%M:%S')} BJT")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
                "--headless=new",
            ],
        )

        context = browser.new_context(
            geolocation={"latitude": SCHOOL_LAT, "longitude": SCHOOL_LNG},
            permissions=["geolocation"],
            viewport={"width": 1920, "height": 1080},
            user_agent=DESKTOP_UA,
            locale="zh-CN",
        )

        page = context.new_page()
        page.add_init_script("""Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});""")

        try:
            # Step 1: Load
            load_cookies(context)
            log("Loading wxweb...")
            page.goto(WXWEB, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)
            log(f"URL: {page.url[:120]}")

            # Step 2: Login
            if "authserver" in page.url or "#/login" in page.url:
                if "#/login" in page.url:
                    log("=> SPA login page")
                    page.locator("text=统一身份认证登录").first.click()
                    page.wait_for_timeout(3000)
                    try:
                        page.wait_for_url("**/authserver.swun.edu.cn/**", timeout=20000)
                    except PT:
                        pass

                ok, reason = do_cas_login(page)
                if not ok:
                    log(f"FATAL: CAS login failed — {reason}")
                    return False

                try:
                    page.wait_for_url("**/wxweb/**", timeout=30000)
                except PT:
                    pass
            elif "wxweb" in page.url:
                log("=> Already logged in (cookie)")
            else:
                log(f"Unknown login state: {page.url[:120]}")
                page.screenshot(path="daka_unknown.png")

            save_cookies(context)

            # Step 3: OAuth handling
            page.wait_for_timeout(3000)
            if "hoyOauth" in page.url:
                log("OAuth token processing (15s)...")
                page.wait_for_timeout(15000)

            # ⌛ Login+OAuth cost time — re-verify window before proceeding
            if not force and not in_checkin_window():
                log(f"Window closed after login! {window_status()}")
                log("Aborting to avoid server rejection.")
                return True

            # Step 4: Navigate to clock page
            log("=> PositioningClock...")
            try:
                page.goto(f"{WXWEB}#/PositioningClock", wait_until="networkidle", timeout=30000)
            except PT:
                pass
            log(f"Clock URL: {page.url[:120]}")

            # Step 5: Wait for API + click
            ok = find_and_click_clock(page)
            return ok

        except PT as e:
            log(f"Timeout: {e}")
            page.screenshot(path="daka_error.png")
            return False
        except Exception as e:
            log(f"Error: {traceback.format_exc()}")
            page.screenshot(path="daka_error.png")
            return False
        finally:
            context.close()
            browser.close()
            log("Done")


def main():
    import argparse
    ap = argparse.ArgumentParser(description="民大自动打卡 v17")
    ap.add_argument("-m", "--manual", action="store_true", help="Non-headless, interactive")
    ap.add_argument("--show", action="store_true", help="Show browser window")
    ap.add_argument("--force", action="store_true", help="Skip time window check")
    args = ap.parse_args()

    ok = do_checkin(
        headless=(not args.show and not args.manual),
        force=args.force
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
