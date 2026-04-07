"""
小红书笔记采集器 - Playwright 核心逻辑
支持持久化登录 session，首次使用需扫码登录
"""

import os
import re
import json
import time
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

SESSION_DIR = Path(__file__).parent / "session"
SESSION_DIR.mkdir(exist_ok=True)

LOGIN_STATE_FILE = SESSION_DIR / "login_state.json"


def is_logged_in(page) -> bool:
    """检查当前页面是否处于登录状态"""
    try:
        cookies = page.context.cookies()
        for c in cookies:
            if c.get("name") == "web_session" and c.get("value"):
                return True
        return False
    except Exception:
        return False


def check_login_from_storage() -> bool:
    """从本地 session 文件判断是否已有登录态"""
    if not LOGIN_STATE_FILE.exists():
        return False
    try:
        data = json.loads(LOGIN_STATE_FILE.read_text())
        cookies = data.get("cookies", [])
        for c in cookies:
            if c.get("name") == "web_session" and c.get("value"):
                return True
    except Exception:
        pass
    return False


def do_login(on_ready=None):
    """
    打开有头浏览器让用户扫码登录，登录成功后保存 session。
    直接导航到二维码登录页，避免默认显示手机号登录。
    返回 True 表示登录成功，False 表示超时或失败
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        # 不加载旧 session，确保弹出登录框
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = ctx.new_page()

        # 直接访问二维码登录页
        page.goto(
            "https://www.xiaohongshu.com/explore",
            wait_until="domcontentloaded",
            timeout=30000,
        )

        # 等待页面加载后尝试点击「扫码登录」tab（如果默认是手机号登录）
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
            qr_tab = page.locator(
                "text=扫码登录, "
                "[data-id='qrcode'], "
                ".qrcode-tab, "
                ".login-qrcode"
            ).first
            if qr_tab.is_visible(timeout=3000):
                qr_tab.click()
        except Exception:
            pass  # 找不到 tab 也没关系，用户自己切换

        if on_ready:
            on_ready()

        # 等待登录成功（最多 3 分钟）
        deadline = time.time() + 180
        logged_in = False
        while time.time() < deadline:
            if is_logged_in(page):
                logged_in = True
                break
            time.sleep(2)

        if logged_in:
            ctx.storage_state(path=str(LOGIN_STATE_FILE))

        browser.close()
        return logged_in


def scrape_note(url: str) -> dict:
    """
    采集一条小红书笔记，返回结构化数据字典。
    使用持久化 session（已登录状态下能获取正文内容）。
    """
    storage = str(LOGIN_STATE_FILE) if LOGIN_STATE_FILE.exists() else None

    # 反检测启动参数
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=launch_args)
        ctx = browser.new_context(
            storage_state=storage,
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        # 隐藏 webdriver 标识
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = ctx.new_page()

        try:
            # Step 1: 跟随短链跳转，等待完整加载
            page.goto(url, wait_until="load", timeout=30000)

            # Step 2: 等待 SPA 二次路由完成
            try:
                page.wait_for_url("**/xiaohongshu.com/**", timeout=15000)
            except PlaywrightTimeout:
                pass

            # Step 3: 等待网络空闲
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeout:
                pass

            # Step 4: 检测是否落地到登录页（session 失效或未登录）
            current_url = page.url
            page_title = page.title()
            LOGIN_SIGNALS = ["login", "signin", "passport", "手机号登录", "验证码登录"]
            if any(s in current_url.lower() or s in page_title for s in LOGIN_SIGNALS):
                # session 已失效，删除本地文件，让前端状态同步变回未登录
                if LOGIN_STATE_FILE.exists():
                    LOGIN_STATE_FILE.unlink()
                return {
                    "success": False,
                    "error": "⚠️ 登录已过期，请重新点击「扫码登录」完成授权",
                }

            # Step 5: 等待笔记核心 DOM 出现
            try:
                page.wait_for_selector(
                    "#detail-title, .note-content, .author-wrapper, .interactions",
                    timeout=10000,
                )
            except PlaywrightTimeout:
                pass

            # Step 6: 提取数据（失败时重试一次）
            result = _safe_evaluate(page)

            # 如果 JS 选择器没抓到互动数据，尝试从 DOM 文本节点补充
            if not result.get("likes"):
                result.update(_fallback_extract(page))

            result["hook_type"] = classify_hook_type(
                result.get("title", ""), result.get("content", "")
            )
            result["scraped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            result["original_url"] = url
            return {"success": True, "data": result}

        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            browser.close()


_EXTRACT_JS = """
() => {
    const getText = (sel) => {
        const el = document.querySelector(sel);
        return el ? el.innerText.trim() : '';
    };

    const title = getText('#detail-title')
        || getText('.title')
        || document.title.replace(' - 小红书', '').trim();

    const author = getText('.author-wrapper .name')
        || getText('.username')
        || getText('.user-nickname')
        || '';

    const date = getText('.date') || getText('.publish-date') || getText('.time') || '';

    const content = getText('#detail-desc .note-text')
        || getText('.note-content .note-text')
        || getText('#detail-desc')
        || getText('.note-content')
        || '';

    const tagEls = document.querySelectorAll(
        '#detail-desc .tag, .note-content .tag, a[href*="search_result"]'
    );
    const tags = Array.from(tagEls)
        .map(el => el.innerText.trim())
        .filter(t => t.startsWith('#'))
        .join(' ');

    // 必须限定在 engage-bar-style 内，否则会取到评论区的点赞数（页面有多个 .like-wrapper）
    const bar = document.querySelector('.engage-bar-style, .buttons.engage-bar-style');
    const likeEl    = bar ? bar.querySelector('.like-wrapper .count')    : null;
    const collectEl = bar ? bar.querySelector('.collect-wrapper .count') : null;
    const commentEl = bar ? bar.querySelector('.chat-wrapper .count')    : null;

    return {
        title, author, date, content, tags,
        likes:    likeEl    ? likeEl.innerText.trim()    : '',
        collects: collectEl ? collectEl.innerText.trim() : '',
        comments: commentEl ? commentEl.innerText.trim() : '',
        final_url: window.location.href,
    };
}
"""


def _safe_evaluate(page) -> dict:
    """执行 JS 提取，若执行上下文被销毁则等待页面稳定后重试一次"""
    try:
        return page.evaluate(_EXTRACT_JS)
    except Exception as first_err:
        if "context was destroyed" not in str(first_err).lower():
            raise
        # 页面正在跳转，等待稳定后重试
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PlaywrightTimeout:
            pass
        time.sleep(1)
        return page.evaluate(_EXTRACT_JS)


def _fallback_extract(page) -> dict:
    """备用提取：通过页面 accessibility tree 获取互动数据"""
    try:
        text = page.inner_text("body")
        lines = [l.strip() for l in text.split("\n") if l.strip()]

        # 在页面文本中找数字模式（点赞/收藏/评论紧跟在特定区域）
        likes = collects = comments = ""
        for i, line in enumerate(lines):
            if any(kw in line for kw in ["赞", "喜欢"]) and i + 1 < len(lines):
                candidate = lines[i + 1] if not lines[i].replace("赞", "").replace("喜欢", "").strip().isdigit() else lines[i].replace("赞", "").strip()
                if candidate.replace(",", "").isdigit():
                    likes = candidate
            if "收藏" in line and i + 1 < len(lines):
                candidate = lines[i + 1]
                if candidate.replace(",", "").isdigit():
                    collects = candidate
            if "评论" in line and i + 1 < len(lines):
                candidate = lines[i + 1]
                if candidate.replace(",", "").isdigit():
                    comments = candidate

        return {"likes": likes, "collects": collects, "comments": comments}
    except Exception:
        return {}


def parse_share_text(text: str) -> dict:
    """
    解析小红书分享文本，提取 URL、标题、作者。

    支持格式：
    1. App 分享完整文本：
       23 【标题 - 作者 | 小红书 - 你的生活兴趣社区】 😆 CODE 😆 https://...
    2. 网页分享完整文本（含换行）：
       标题\n作者\nhttps://www.xiaohongshu.com/...
    3. xhslink 短链：http://xhslink.com/...
    4. 纯完整链接：https://www.xiaohongshu.com/...
    """
    text = text.strip()
    result = {"url": "", "title": "", "author": ""}

    # ── URL 提取 ──────────────────────────────────────────────────
    # URL 合法字符：字母数字及 -._~:/?#[]@!$&'()*+,;=%
    # 明确排除：中文、全角字符、空白、常见结尾标点
    _URL_RE = re.compile(
        r'https?://'                         # scheme
        r'[A-Za-z0-9\-._~:/?#\[\]@!$&\'()*+,;=%]+'  # path + query
    )

    candidates = _URL_RE.findall(text)
    # 清理每个候选末尾可能误入的标点
    _TRAIL = re.compile(r'[.,;:)\]>\'\"]+$')
    candidates = [_TRAIL.sub('', u) for u in candidates]

    if candidates:
        # 优先选 xiaohongshu.com 完整链接；其次 xhslink 短链；最后任意
        def _rank(u):
            if 'xiaohongshu.com' in u:
                return 0
            if 'xhslink.com' in u:
                return 1
            return 2
        result["url"] = sorted(candidates, key=_rank)[0]

    # ── 标题 / 作者提取 ───────────────────────────────────────────
    # 优先解析 【标题 - 作者 | 小红书...】 格式
    bracket_match = re.search(r'【(.+?)】', text, re.DOTALL)
    if bracket_match:
        inner = bracket_match.group(1).replace('\n', ' ').strip()
        inner = re.sub(r'\s*\|\s*小红书.*$', '', inner).strip()
        parts = inner.rsplit(' - ', 1)
        if len(parts) == 2:
            result["title"] = parts[0].strip()
            result["author"] = parts[1].strip()
        else:
            result["title"] = inner.strip()

    return result


# ── Hook 类型分类 ─────────────────────────────────────────────────

def classify_hook_type(title: str, content: str = "") -> str:
    """
    基于规则对笔记标题（+正文）进行 Hook 类型分类，返回中文类型标签。
    规则按优先级顺序匹配，命中第一条即返回。
    """
    t = title or ""
    c = content or ""
    tc = t + c  # 标题+正文联合检索（干货型等需要）

    rules = [
        # (类型标签,  检查函数)
        ("疑问型",   lambda: bool(re.search(r'[？?]|为什么|是不是|有没有|怎么|怎样|如何|吗$|呢$|吗？|呢？', t))),
        ("数字型",   lambda: bool(re.search(r'\d+\s*[个种条步招点款件样]', t))),
        ("悬念型",   lambda: bool(re.search(r'竟然|没想到|原来|真相|秘密|揭秘|其实|你不知道', t))),
        ("痛点型",   lambda: bool(re.search(r'坑|千万别|不要|踩雷|后悔|失败|教训|避免|血泪', t))),
        ("干货型",   lambda: bool(re.search(r'方法|技巧|攻略|教程|指南|清单|步骤|干货|总结|汇总|必看|必备', tc))),
        ("故事型",   lambda: bool(re.search(r'我.{0,10}(经历|故事|亲身|感受|分享|遇到|发现)', t))),
        ("情绪型",   lambda: bool(re.search(r'爱了|绝了|惊了|哭了|笑了|太.*了|超.*了|！！|🔥|💥|😭|😍', t))),
        ("对比型",   lambda: bool(re.search(r'[vV][sS]|对比|比较|区别|差距|PK|pk', t))),
        ("反常识型", lambda: bool(re.search(r'颠覆|打破|别人不告诉你|99%|其实你错了|真的假的', t))),
        ("促销型",   lambda: bool(re.search(r'[¥$￥]|\d+元|折扣|优惠|买.*推荐|好物|种草', t))),
    ]

    for label, check in rules:
        try:
            if check():
                return label
        except Exception:
            continue

    return "通用型"
