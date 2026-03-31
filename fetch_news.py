"""
全球国际商务资讯日报抓取与生成脚本
每天 09:00 自动运行，抓取资讯并生成 HTML 日报，通过 WxPusher 推送到微信
"""

import json
import os
import re
import sys
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Windows 兼容：强制 stdout/stderr 使用 UTF-8
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ─────────────────────────────────────────────
# 配置区（首次使用请修改这里）
# ─────────────────────────────────────────────
CONFIG = {
    # WxPusher 配置（注册后填入）
    "wxpusher_app_token": os.environ.get("WXPUSHER_APP_TOKEN", ""),
    "wxpusher_uid": os.environ.get("WXPUSHER_UID", ""),

    # NewsAPI 配置（可选，免费注册 https://newsapi.org）
    "newsapi_key": os.environ.get("NEWSAPI_KEY", ""),

    # 日报输出目录
    "output_dir": str(Path(__file__).parent / "reports"),
}

# 北京时间
CN_TZ = timezone(timedelta(hours=8))

# ─────────────────────────────────────────────
# 资讯抓取模块
# ─────────────────────────────────────────────

def fetch_from_newsapi(api_key: str) -> list[dict]:
    """通过 NewsAPI 抓取国际商务资讯"""
    if not api_key:
        return []

    queries = [
        "international trade business",
        "global economy finance",
        "tech business AI merger acquisition",
    ]
    articles = []
    seen_titles = set()

    for query in queries:
        url = (
            "https://newsapi.org/v2/everything?"
            + urllib.parse.urlencode({
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 5,
                "apiKey": api_key,
            })
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                for art in data.get("articles", []):
                    title = art.get("title", "")
                    if title and title not in seen_titles and "[Removed]" not in title:
                        seen_titles.add(title)
                        articles.append({
                            "title": title,
                            "description": art.get("description", ""),
                            "url": art.get("url", ""),
                            "source": art.get("source", {}).get("name", "NewsAPI"),
                            "published_at": art.get("publishedAt", ""),
                            "category": classify_article(title),
                        })
        except Exception as e:
            print(f"[NewsAPI] 抓取失败: {e}")

    return articles[:20]


def fetch_rss(feed_url: str, source_name: str, category: str) -> list[dict]:
    """抓取 RSS 源"""
    articles = []
    try:
        req = urllib.request.Request(
            feed_url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)",
                "Accept": "application/rss+xml, application/xml, text/xml",
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="replace")

        # 简单 XML 解析（不依赖 lxml）
        items = re.findall(r"<item>(.*?)</item>", content, re.DOTALL)
        for item in items[:5]:
            title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, re.DOTALL)
            link = re.search(r"<link>(.*?)</link>", item, re.DOTALL)
            desc = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", item, re.DOTALL)
            pub = re.search(r"<pubDate>(.*?)</pubDate>", item, re.DOTALL)

            if title:
                t = re.sub(r"<[^>]+>", "", title.group(1)).strip()
                d = re.sub(r"<[^>]+>", "", desc.group(1) if desc else "").strip()[:200]
                l = (link.group(1) if link else "").strip()
                p = (pub.group(1) if pub else "").strip()
                if t:
                    articles.append({
                        "title": t,
                        "description": d,
                        "url": l,
                        "source": source_name,
                        "published_at": p,
                        "category": category,
                    })
    except Exception as e:
        print(f"[RSS] {source_name} 抓取失败: {e}")

    return articles


# ─────────────────────────────────────────────
# 翻译模块（MyMemory 免费 API，国内可访问，无需 Key）
# ─────────────────────────────────────────────

import time

_translate_cache: dict[str, str] = {}

def translate_to_zh(text: str) -> str:
    """将英文文本翻译为中文（MyMemory 免费 API）"""
    if not text or not text.strip():
        return text
    # 已有中文字符则直接返回
    if any('\u4e00' <= c <= '\u9fff' for c in text):
        return text
    text = text.strip()
    if text in _translate_cache:
        return _translate_cache[text]

    # MyMemory 单次限制 500 字符，超过截断
    query = text[:480]

    try:
        params = urllib.parse.urlencode({
            "q": query,
            "langpair": "en|zh",
            "de": "newsbot@example.com",  # 匿名邮箱，提升限额
        })
        url = f"https://api.mymemory.translated.net/get?{params}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            translated = data.get("responseData", {}).get("translatedText", "")
            # MyMemory 超限时会返回英文或 MYMEMORY WARNING
            if translated and "MYMEMORY WARNING" not in translated and translated != query:
                _translate_cache[text] = translated
                return translated
    except Exception:
        pass

    # 备用方案：有道翻译 Web 接口
    try:
        import hashlib, random, base64
        salt = str(random.randint(1, 99999))
        params2 = urllib.parse.urlencode({
            "q": query,
            "from": "en",
            "to": "zh-CHS",
            "appKey": "",
            "salt": salt,
        })
        url2 = f"https://fanyi.youdao.com/translate?{params2}&smartresult=dict&smartresult=rule"
        req2 = urllib.request.Request(
            url2,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://fanyi.youdao.com/",
            },
        )
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            data2 = json.loads(resp2.read().decode("utf-8"))
            lines = data2.get("translateResult", [[]])[0]
            result = "".join(item.get("tgt", "") for item in lines)
            if result:
                _translate_cache[text] = result
                return result
    except Exception:
        pass

    # 两种翻译都失败，保留原文
    return text


def translate_articles(articles: list[dict]) -> list[dict]:
    """批量翻译文章标题和摘要"""
    print("  🌐 正在翻译标题和摘要（MyMemory API）...")
    total = len(articles)
    for i, art in enumerate(articles):
        art["title"] = translate_to_zh(art.get("title", ""))
        if art.get("description"):
            art["description"] = translate_to_zh(art["description"])
        # 每翻译3条暂停，避免频繁请求
        if (i + 1) % 3 == 0:
            time.sleep(0.5)
        print(f"    {i+1}/{total} 已翻译", end="\r")
    print(f"  ✅ 翻译完成，共 {total} 条          ")
    return articles


def classify_article(title: str) -> str:
    """简单关键词分类"""
    title_lower = title.lower()
    if any(k in title_lower for k in ["trade", "tariff", "wto", "export", "import", "货币", "汇率", "currency"]):
        return "macro"
    if any(k in title_lower for k in ["ai", "tech", "startup", "ipo", "merger", "acquisition", "funding"]):
        return "tech"
    if any(k in title_lower for k in ["stock", "market", "bond", "fed", "rate", "invest", "gdp", "inflation"]):
        return "finance"
    return "general"


def gather_all_news() -> list[dict]:
    """聚合所有资讯来源"""
    all_articles = []

    # RSS 资讯源（不需要 API key）
    rss_sources = [
        # 宏观 & 贸易
        ("https://feeds.reuters.com/reuters/businessNews", "Reuters Business", "macro"),
        ("https://www.ft.com/rss/home/uk", "Financial Times", "finance"),
        ("https://feeds.bbci.co.uk/news/business/rss.xml", "BBC Business", "general"),
        # 科技商业
        ("https://feeds.feedburner.com/TechCrunch", "TechCrunch", "tech"),
        ("https://www.wired.com/feed/rss", "Wired", "tech"),
        # 金融市场
        ("https://www.cnbc.com/id/10000664/device/rss/rss.html", "CNBC Finance", "finance"),
        ("https://www.marketwatch.com/rss/realtimeheadlines", "MarketWatch", "finance"),
    ]

    for url, name, cat in rss_sources:
        articles = fetch_rss(url, name, cat)
        all_articles.extend(articles)
        print(f"  ✓ {name}: 获取 {len(articles)} 条")

    # NewsAPI（如果配置了 key）
    if CONFIG["newsapi_key"]:
        api_articles = fetch_from_newsapi(CONFIG["newsapi_key"])
        all_articles.extend(api_articles)
        print(f"  ✓ NewsAPI: 获取 {len(api_articles)} 条")

    # 去重（按标题）
    seen = set()
    unique = []
    for art in all_articles:
        key = art["title"][:50].lower()
        if key not in seen:
            seen.add(key)
            unique.append(art)

    # 按分类排序
    order = {"macro": 0, "finance": 1, "tech": 2, "general": 3}
    unique.sort(key=lambda x: order.get(x["category"], 4))

    result = unique[:30]

    # 翻译标题和摘要为中文
    result = translate_articles(result)

    return result


# ─────────────────────────────────────────────
# HTML 日报生成模块
# ─────────────────────────────────────────────

CATEGORY_CONFIG = {
    "macro":   {"label": "🌍 宏观与贸易", "color": "#3b82f6", "bg": "#eff6ff"},
    "finance": {"label": "📈 金融市场",   "color": "#10b981", "bg": "#ecfdf5"},
    "tech":    {"label": "💡 科技商业",   "color": "#8b5cf6", "bg": "#f5f3ff"},
    "general": {"label": "📰 综合资讯",   "color": "#f59e0b", "bg": "#fffbeb"},
}

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>🌐 国际商务日报 · {date}</title>
<style>
  :root {{
    --primary: #1e293b;
    --accent:  #3b82f6;
    --surface: #f8fafc;
    --card-bg: #ffffff;
    --text:    #334155;
    --muted:   #94a3b8;
    --border:  #e2e8f0;
    --radius:  12px;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif;
    background: var(--surface);
    color: var(--text);
    font-size: 15px;
    line-height: 1.6;
  }}

  /* 顶部 Hero */
  .hero {{
    background: linear-gradient(135deg, #1e3a5f 0%, #1e293b 60%, #0f172a 100%);
    padding: 32px 20px 28px;
    text-align: center;
    position: relative;
    overflow: hidden;
  }}
  .hero::before {{
    content: "";
    position: absolute; inset: 0;
    background: radial-gradient(ellipse at 30% 50%, rgba(59,130,246,0.15) 0%, transparent 60%),
                radial-gradient(ellipse at 70% 30%, rgba(139,92,246,0.1) 0%, transparent 50%);
  }}
  .hero-content {{ position: relative; }}
  .hero-tag {{
    display: inline-block;
    background: rgba(59,130,246,0.2);
    border: 1px solid rgba(59,130,246,0.4);
    color: #93c5fd;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1.5px;
    padding: 4px 12px;
    border-radius: 20px;
    text-transform: uppercase;
    margin-bottom: 12px;
  }}
  .hero h1 {{
    color: #ffffff;
    font-size: 24px;
    font-weight: 700;
    margin-bottom: 6px;
    letter-spacing: -0.3px;
  }}
  .hero-date {{
    color: #94a3b8;
    font-size: 13px;
  }}
  .hero-stats {{
    display: flex;
    justify-content: center;
    gap: 20px;
    margin-top: 20px;
  }}
  .stat {{
    text-align: center;
  }}
  .stat-num {{
    color: #60a5fa;
    font-size: 22px;
    font-weight: 700;
    line-height: 1;
  }}
  .stat-label {{
    color: #64748b;
    font-size: 11px;
    margin-top: 3px;
  }}

  /* 分类导航 */
  .nav-tabs {{
    display: flex;
    gap: 8px;
    padding: 16px 16px 0;
    overflow-x: auto;
    scrollbar-width: none;
    -webkit-overflow-scrolling: touch;
  }}
  .nav-tabs::-webkit-scrollbar {{ display: none; }}
  .nav-tab {{
    flex-shrink: 0;
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    border: 1.5px solid transparent;
    background: var(--card-bg);
    color: var(--muted);
    border-color: var(--border);
    transition: all 0.2s;
    white-space: nowrap;
  }}
  .nav-tab.active, .nav-tab:hover {{
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
  }}

  /* 内容区 */
  .container {{ padding: 16px; max-width: 800px; margin: 0 auto; }}
  .section {{ margin-bottom: 24px; }}
  .section-header {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
  }}
  .section-badge {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 12px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 700;
  }}
  .section-count {{
    background: rgba(0,0,0,0.08);
    border-radius: 10px;
    padding: 1px 7px;
    font-size: 11px;
    font-weight: 600;
  }}

  /* 新闻卡片 */
  .card {{
    background: var(--card-bg);
    border-radius: var(--radius);
    border: 1px solid var(--border);
    padding: 14px 16px;
    margin-bottom: 10px;
    transition: box-shadow 0.2s, transform 0.2s;
    cursor: pointer;
    text-decoration: none;
    display: block;
    color: inherit;
    -webkit-tap-highlight-color: transparent;
  }}
  .card:active {{ transform: scale(0.985); box-shadow: none; }}
  @media (hover: hover) {{
    .card:hover {{ box-shadow: 0 4px 20px rgba(0,0,0,0.08); transform: translateY(-1px); }}
  }}
  .card-source {{
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 6px;
  }}
  .source-dot {{
    width: 6px; height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }}
  .source-name {{
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--muted);
  }}
  .source-time {{
    font-size: 11px;
    color: var(--muted);
    margin-left: auto;
  }}
  .card-title {{
    font-size: 14px;
    font-weight: 600;
    color: var(--primary);
    line-height: 1.5;
    margin-bottom: 6px;
  }}
  .card-desc {{
    font-size: 13px;
    color: var(--muted);
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}
  .card-link {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-top: 8px;
    font-size: 12px;
    font-weight: 600;
    color: var(--accent);
  }}

  /* 底部 */
  .footer {{
    text-align: center;
    padding: 20px 16px 32px;
    color: var(--muted);
    font-size: 12px;
    border-top: 1px solid var(--border);
    margin-top: 8px;
  }}
  .footer a {{ color: var(--accent); text-decoration: none; }}
</style>
</head>
<body>

<div class="hero">
  <div class="hero-content">
    <div class="hero-tag">Global Business Intelligence</div>
    <h1>🌐 国际商务日报</h1>
    <div class="hero-date">{date_cn} · 早间版</div>
    <div class="hero-stats">
      <div class="stat"><div class="stat-num">{total_count}</div><div class="stat-label">条资讯</div></div>
      <div class="stat"><div class="stat-num">{source_count}</div><div class="stat-label">个来源</div></div>
      <div class="stat"><div class="stat-num">{category_count}</div><div class="stat-label">个领域</div></div>
    </div>
  </div>
</div>

<div class="container">
{sections}
</div>

<div class="footer">
  <p>由 WorkBuddy 自动生成 · {date_cn} 09:00</p>
  <p style="margin-top:4px">来源：Reuters · FT · BBC · CNBC · TechCrunch 等</p>
</div>

</body>
</html>"""

SECTION_TEMPLATE = """name: Daily News Push

on:
  schedule:
    - cron: '0 1 * * *'
  workflow_dispatch:

jobs:
  push-news:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Run news fetch and push
        run: python ./fetch_news.py
        env:
          WXPUSHER_APP_TOKEN: ${{ secrets.WXPUSHER_APP_TOKEN }}
          WXPUSHER_UID: ${{ secrets.WXPUSHER_UID }}

    main()
