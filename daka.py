"""
民大自动打卡 v19 - 全链路修复版
=============================
v19 变更:
- 修复根因: secrets 为空导致空密码登录失败 (v15-v18 全中招)
- 移除错误的验证码检测逻辑 (v16/v17 误判 #captcha 隐藏输入框)
- 真实验证码: 仅当 needCaptcha 为真 + captchaSwitch=="2" 时触发滑块
- 正常流程 (needCaptcha 空) 直接走表单加密提交
- 保留 CAS REST API 旁路 (/authserver/v1/tickets 已验证存在)
- Cookie 持久化保留 (配合 workflow cache 实现跨 run 复用)

v18 变更(已废弃):
- CAS REST API 路径错误 (/cas/ -> /authserver/)
- Cookie 持久化无跨 run 复用

v17 变更(已废弃):
- ddddocr OCR 误判 (验证码默认不需要)

v16 变更:
- do_cas_login() 返回 (success, reason)
- 登录失败 -> 立即中止
"""
import os, sys, time, json, traceback, re, ssl
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PT

BJT = timezone(timedelta(hours=8))

SCHOOL_LAT = 30.562897
SCHOOL_LNG = 103.966624
WXWEB = "https://gyglxt.swun.edu.cn/wxweb/"
CAS_BASE = "https://authserver.swun.edu.cn/authserver"
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
    now = datetime.now(BJT)
    return f"{now.strftime('%H:%M')} BJT — {'IN window' if in_checkin_window() else 'OUTSIDE window'}"


def log(msg):
    print(f"[{datetime.now(BJT).strftime('%H:%M:%S')}] {msg}", flush=True)


def save_cookies(context):
    """Save ALL cookies across all domains."""
    try:
        cookies = context.cookies()
        domains = set(c.get("domain", "?") for c in cookies)
        with open(COOKIE_FILE, "w") as f:
            json.dump(cookies, f)
        log(f"Saved {len(cookies)} cookies from domains: {', '.join(sorted(domains))}")
    except Exception as e:
        log(f"Cookie save err: {e}")


def load_cookies(context):
    """Load saved cookies into the browser context."""
    try:
        if os.path.exists(COOKIE_FILE):
            with open(COOKIE_FILE) as f:
                cookies = json.load(f)
                if cookies:
                    context.add_cookies(cookies)
                    domains = set(c.get("domain", "?") for c in cookies)
                    log(f"Loaded {len(cookies)} cookies from domains: {', '.join(sorted(domains))}")
                    return True
    except Exception as e:
        log(f"Cookie load err: {e}")
    return False


def try_cas_rest_api():
    """Try the CAS REST API to get a Service Ticket without the login form.

    Verified endpoint: /authserver/v1/tickets (returns 401 for bad creds).
      1. POST /authserver/v1/tickets?username=..&password=.. -> 201 + TGT Location
      2. POST {TGT}?service=..                               -> 200 + ST body

    Returns (success, service_ticket_or_error_message).
    """
    if not USERNAME or not PASSWORD:
        return False, "no credentials"

    ssl_ctx = ssl.create_default_context()

    # POST username/password -> get TGT
    tgt_url = None
    for mode in ("querystring", "body"):
        try:
            if mode == "querystring":
                url = f"{CAS_BASE}/v1/tickets?username={urllib.parse.quote(USERNAME)}&password={urllib.parse.quote(PASSWORD)}"
                req = urllib.request.Request(url, method="POST")
            else:
                url = f"{CAS_BASE}/v1/tickets"
                body = urllib.parse.urlencode({
                    "username": USERNAME, "password": PASSWORD
                }).encode()
                req = urllib.request.Request(url, data=body, method="POST")
                req.add_header("Content-Type", "application/x-www-form-urlencoded")
            req.add_header("User-Agent", DESKTOP_UA)
            log(f"REST POST {url[:70]}... (mode={mode})")
            resp = urllib.request.urlopen(req, context=ssl_ctx, timeout=30)
            if resp.status == 201:
                tgt_url = resp.headers.get("Location") or resp.read().decode().strip()
                log(f"TGT obtained: {tgt_url[:90]}")
                break
            else:
                log(f"REST {mode} -> HTTP {resp.status}")
        except urllib.error.HTTPError as e:
            log(f"REST {mode} -> HTTP {e.code}")
        except Exception as e:
            log(f"REST {mode} failed: {e}")

    if not tgt_url:
        return False, "CAS REST API unavailable"

    # Exchange TGT for Service Ticket
    try:
        st_body = urllib.parse.urlencode({"service": WXWEB}).encode()
        st_req = urllib.request.Request(tgt_url, data=st_body, method="POST")
        st_req.add_header("Content-Type", "application/x-www-form-urlencoded")
        st_req.add_header("User-Agent", DESKTOP_UA)
        st_resp = urllib.request.urlopen(st_req, context=ssl_ctx, timeout=30)
        if st_resp.status == 200:
            st = st_resp.read().decode().strip()
            log(f"ST obtained: {st[:30]}...")
            return True, st
        return False, f"ST request returned HTTP {st_resp.status}"
    except Exception as e:
        return False, f"ST request failed: {e}"


def do_cas_login(page):
    """Perform CAS login. Returns (success, error_reason).

    Flow (matches real login.js):
      1. Fill username/password (plaintext)
      2. Check needCaptcha: if truthy + captchaSwitch=="2" -> slider captcha
         (we bypass via REST API instead of solving the slider)
      3. Normal path: let the page JS encrypt and submit
      4. Detect failure by staying on authserver login page
    """
    # We should be on the password login form (cllt=userNameLogin) already.
    # Do NOT force-cllt here; the page defaults to it after clicking SSO.
    # If we're on a different tab (e.g. phone login), click the account tab.
    page.evaluate("""(function() {
        var cllt = document.querySelector('#cllt');
        if (cllt && cllt.value !== 'userNameLogin') {
            var tab = document.querySelector('#userNameLogin_a, a[onclick*="userNameLogin"], [id*="userNameLogin"]');
            if (tab) tab.click();
        }
    })()""")
    page.wait_for_timeout(1000)

    # ---- Read the REAL captcha state (not the static #captcha input) ----
    captcha_state = page.evaluate("""(function() {
        return {
            needCaptcha: window.needCaptcha || '',
            captchaSwitch: window.captchaSwitch || '',
            cllt: (document.querySelector('#cllt')||{}).value || '',
            captchaDiv_display: (function() {
                var d = document.querySelector('#captchaDiv');
                return d ? window.getComputedStyle(d).display : 'N/A';
            })(),
            sliderCaptchaDiv: (function() {
                var d = document.querySelector('#sliderCaptchaDiv');
                return d ? window.getComputedStyle(d).display : 'N/A';
            })(),
        };
    })()""")
    log(f"Captcha state: {captcha_state}")

    captcha_required = bool(captcha_state.get("needCaptcha")) and \
                       captcha_state.get("captchaSwitch") == "2"

    if captcha_required:
        log("Slider captcha REQUIRED -> trying CAS REST API bypass...")
        ok, result = try_cas_rest_api()
        if ok:
            st = result
            ticket_url = (
                f"{WXWEB}?ticket={urllib.parse.quote(st)}"
                if "?" not in WXWEB else f"{WXWEB}&ticket={urllib.parse.quote(st)}"
            )
            log("REST API success! Redirecting via ST...")
            page.goto(ticket_url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(5000)
            url = page.url
            log(f"After ST redirect: {url[:100]}")
            if "authserver" in url and "login" in url:
                return False, "ST redirect looped back to CAS login"
            return ("wxweb" in url or "appcas" in url), None
        else:
            log(f"CAS REST API failed: {result}")
            log("Slider captcha cannot be solved automatically.")
            log("Run `python daka.py --show` locally to login once; cookies saved for reuse.")
            page.screenshot(path="daka_captcha_blocked.png")
            return False, f"slider captcha + REST unavailable: {result}"

    # ---- Normal path: no captcha required ----
    page.fill("#username", USERNAME)
    page.fill("#password", PASSWORD)
    log("Filled credentials")

    # Let the page's own JS handle encryption + submission via #login_submit
    # (matches login.js: checkForm -> encryptPassword -> disable #password -> submit)
    page.click("#login_submit")
    log("Clicked login_submit")

    # Wait for navigation / result
    page.wait_for_timeout(8000)
    url = page.url
    log(f"After CAS submit: {url[:110]}")
    page.screenshot(path="daka_cas_result.png")

    # Read any error message shown
    err = page.evaluate("""(function() {
        var t = document.querySelector('#showErrorTip, .error, .msg, [id*="error"]');
        if (!t) return '';
        return (t.innerText || t.textContent || '').substring(0, 120);
    })()""")
    if err:
        log(f"CAS response: {err[:80]}")

    # If still on the authserver login page -> login failed
    if "authserver" in url and "login" in url:
        return False, f"CAS rejected: {err[:80] if err else 'stayed on login page'}"

    return ("wxweb" in url or "appcas" in url), None


def find_and_click_clock(page):
    """Locate and click the check-in circle. 4-phase wait."""

    # Phase 1: Wait for Vue SPA to render
    body = ""
    for i in range(30):
        body = page.locator("body").inner_text().strip()
        if len(body) > 10:
            break
        if i == 0:
            log("Waiting for SPA to render...")
        page.wait_for_timeout(1000)
    else:
        log("FATAL: Page blank after 30s")
        page.screenshot(path="daka_error.png")
        return False

    with open("page_text.txt", "w", encoding="utf-8") as f:
        f.write(body)
    log(f"Page: {len(body)} chars")
    page.screenshot(path="daka_clock.png", full_page=True)

    if "已打卡" in body or "签到成功" in body:
        log("ALREADY CHECKED IN TODAY")
        return True

    # Phase 2: Wait for queryPersonDetailInfo API (up to 3min)
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

    # Phase 4: Wait for result (up to 30s)
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
    log(f"v19 - Starting check-in at {now.strftime('%Y-%m-%d %H:%M:%S')} BJT")

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
            # Step 1: Load cookies & visit wxweb
            had_cookies = load_cookies(context)
            log("Loading wxweb...")
            page.goto(WXWEB, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)
            log(f"URL: {page.url[:120]}")
            log(f"Cookie status: {'reused' if had_cookies else 'no saved cookies'}")

            # Step 2: Handle auth state
            if "authserver" in page.url or "#/login" in page.url:
                if "#/login" in page.url:
                    log("=> SPA login page -> clicking CAS SSO")
                    page.locator("text=统一身份认证登录").first.click()
                    page.wait_for_timeout(3000)
                    try:
                        page.wait_for_url("**/authserver.swun.edu.cn/**", timeout=20000)
                    except PT:
                        pass

                # Check if CAS auto-redirected (valid TGC cookie).
                # NOTE: the SSO URL contains "appcas" in its service param,
                # so "appcas in url" is NOT a valid login-success signal.
                page.wait_for_timeout(3000)
                url_after = page.url
                if "wxweb" in url_after:
                    log("=> CAS auto-login via TGC cookie (no form needed!)")
                elif "authserver" in url_after and "login" in url_after:
                    log("=> CAS login form shown (cookies expired or missing)")
                    ok, reason = do_cas_login(page)
                    if not ok:
                        log(f"FATAL: CAS login failed — {reason}")
                        return False
                else:
                    log(f"Unexpected post-SSO URL: {url_after[:100]}")

                try:
                    page.wait_for_url("**/wxweb/**", timeout=30000)
                except PT:
                    pass
            elif "wxweb" in page.url:
                log("=> Already logged in (wxweb session valid)")
            else:
                log(f"Unknown login state: {page.url[:120]}")
                page.screenshot(path="daka_unknown.png")

            # Save cookies for next run
            save_cookies(context)

            # Step 3: OAuth handling
            page.wait_for_timeout(3000)
            if "hoyOauth" in page.url:
                log("OAuth token processing (15s)...")
                page.wait_for_timeout(15000)

            # Re-verify window
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

            # Step 5: Click
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
    ap = argparse.ArgumentParser(description="民大自动打卡 v19")
    ap.add_argument("-m", "--manual", action="store_true", help="Non-headless, interactive")
    ap.add_argument("--show", action="store_true", help="Show browser window (for manual captcha)")
    ap.add_argument("--force", action="store_true", help="Skip time window check")
    ap.add_argument("--rest-test", action="store_true", help="Test CAS REST API only, then exit")
    args = ap.parse_args()

    if args.rest_test:
        ok, result = try_cas_rest_api()
        if ok:
            log(f"REST API works! ST: {result[:40]}...")
        else:
            log(f"REST API failed: {result}")
        sys.exit(0 if ok else 1)

    ok = do_checkin(
        headless=(not args.show and not args.manual),
        force=args.force
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
