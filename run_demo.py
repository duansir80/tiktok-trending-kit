#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TikTok 热榜采集器 (本地跑) —— 持久登录 + 自动卡片识别 + 多区域热榜。
云端只产脚本, 本地执行(遵守"云端不装浏览器内核"铁律)。

用法:
  python run_demo.py                  # 读 config.json, 用默认(headed, 有头)启动
  python run_demo.py --headless       # 无头(登录态已存后可无人值守)
  python run_demo.py --config x.json
  python run_demo.py --login          # 仅启动浏览器让你登录, 登录态存入 profile 后按回车

产物: out/trending.json · out/trending.md · out/screen_*.png · out/raw_*.html
说明: TikTok DOM 常变, 脚本用"自动卡片识别"兜底; 若识别不准, 在 config.json 里
      填死 card_selector, 即可精确命中。
"""
import argparse, json, sys, time, socket, urllib.request, urllib.parse
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.stderr.write("[FATAL] 未装 playwright:  pip install -r requirements.txt && playwright install chromium\n")
    sys.exit(1)

HERE = Path(__file__).resolve().parent

# 区域代码 → TikTok Creative Center region 参数
REGION_MAP = {"ID": "ID", "TH": "TH", "VN": "VN", "MY": "MY", "PH": "PH", "SG": "SG",
              "US": "US", "GB": "GB", "DE": "DE", "FR": "FR", "BR": "BR", "MX": "MX", "JP": "JP"}

# 预设热榜入口
PRESETS = {
    "creative_center_products": "https://ads.tiktok.com/business/creativecenter/top-products/pc/en?region={R}",
    "creative_center_hashtags": "https://ads.tiktok.com/business/creativecenter/hashtag/pc/en?region={R}",
    "creative_center_songs":    "https://ads.tiktok.com/business/creativecenter/top-songs/pc/en?region={R}",
    "tiktok_discover":          "https://www.tiktok.com/discover",
    "tiktok_search":            "https://www.tiktok.com/search?q={Q}",
}


def load_config(p: Path) -> dict:
    if not p.exists():
        sys.stderr.write(f"[FATAL] 找不到配置: {p}\n"); sys.exit(2)
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        sys.stderr.write(f"[FATAL] 配置解析失败: {e}\n"); sys.exit(2)
    cfg.setdefault("preset", "creative_center_products")
    cfg.setdefault("url", "")
    cfg.setdefault("query", "kaos oversize")
    cfg.setdefault("region", "ID")
    cfg.setdefault("headless", False)          # 首次务必有头, 便于登录/过验证
    cfg.setdefault("profile_dir", "tk_profile")  # 持久登录态目录
    cfg.setdefault("viewport", {"width": 1400, "height": 900})
    cfg.setdefault("timeout_ms", 45000)
    cfg.setdefault("wait_after_load_ms", 6000)
    cfg.setdefault("scroll_times", 8)
    cfg.setdefault("scroll_pause_ms", 1500)
    cfg.setdefault("card_selector", "")        # 留空=自动识别
    cfg.setdefault("max_items", 40)
    cfg.setdefault("locale", "en-US")
    cfg.setdefault("report_url", "")
    cfg.setdefault("report_token", "")
    return cfg


def resolve_url(cfg) -> str:
    if cfg["url"]:
        return cfg["url"]
    tmpl = PRESETS.get(cfg["preset"], PRESETS["creative_center_products"])
    r = REGION_MAP.get(cfg["region"].upper(), cfg["region"].upper())
    return tmpl.format(R=r, Q=urllib.parse.quote(cfg["query"]))


# 自动卡片识别: 找"重复次数 5~80、含图片、文本长度>4"的同类元素
AUTO_EXTRACT_JS = r"""
() => {
  const cand = {};
  const all = document.querySelectorAll('div,li,article,a');
  for (const el of all) {
    if (el.querySelectorAll('img').length === 0) continue;
    const t = (el.innerText || '').trim();
    if (t.length < 4 || t.length > 400) continue;
    const key = el.tagName + '|' + (el.className || '').toString().slice(0, 60);
    (cand[key] = cand[key] || []).push(el);
  }
  let best = null;
  for (const [k, arr] of Object.entries(cand)) {
    if (arr.length >= 5 && arr.length <= 80) {
      if (!best || arr.length > best.arr.length) best = {k, arr};
    }
  }
  if (!best) return {selector: '', items: []};
  const items = best.arr.map((el, i) => {
    const img = el.querySelector('img');
    const a = el.closest('a') || el.querySelector('a');
    let txt = (el.innerText || '').trim().replace(/\n{2,}/g, '\n');
    // 尝试抽点赞/播放等数字
    const like = (txt.match(/([\d.,]+\s*[KMB万亿]?)\s*(likes?|thích|suka|播放|赞|views?)/i) || [])[1] || '';
    return {
      rank: i + 1,
      title: txt.split('\n')[0].slice(0, 160),
      text: txt.slice(0, 400),
      metric: like,
      img: img ? (img.src || img.getAttribute('data-src') || '') : '',
      href: a ? a.href : ''
    };
  }).filter(x => x.title);
  return {selector: best.k, items};
}
"""

EXTRACT_WITH_SELECTOR_JS = r"""
(sel) => {
  const arr = Array.from(document.querySelectorAll(sel));
  return arr.map((el, i) => {
    const img = el.querySelector('img');
    const a = el.closest('a') || el.querySelector('a');
    let txt = (el.innerText || '').trim().replace(/\n{2,}/g, '\n');
    const like = (txt.match(/([\d.,]+\s*[KMB万亿]?)\s*(likes?|thích|suka|播放|赞|views?)/i) || [])[1] || '';
    return {rank: i + 1, title: txt.split('\n')[0].slice(0, 160), text: txt.slice(0, 400),
            metric: like, img: img ? (img.src || img.getAttribute('data-src') || '') : '', href: a ? a.href : ''};
  }).filter(x => x.title);
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="TikTok 热榜采集器(本地)")
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--login", action="store_true", help="仅打开浏览器供登录, 存登录态")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    url = resolve_url(cfg)
    outdir = HERE / "out"; outdir.mkdir(exist_ok=True)
    profile = HERE / cfg["profile_dir"]
    headless = (cfg["headless"] or args.headless)
    # 登录态目录存在才允许无头(否则必然被拦)
    if headless and not profile.exists():
        sys.stderr.write("[WARN] 尚无登录态 profile, 强制有头启动(先登录一次)。\n")
        headless = False

    print(f"[INFO] 目标: {url}")
    print(f"[INFO] 区域: {cfg['region']} | 模式: {cfg['preset']} | 有头: {not headless}")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=headless,
            viewport=cfg["viewport"],
            locale=cfg["locale"],
            slow_mo=120,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=cfg["timeout_ms"])
            page.wait_for_timeout(cfg["wait_after_load_ms"])

            if args.login:
                print("[LOGIN] 浏览器已打开, 请登录 TikTok。完成后回到本终端按回车...")
                input()
                print("[LOGIN] 登录态已保存到", profile)
                ctx.close(); return 0

            # 滚动加载
            for i in range(cfg["scroll_times"]):
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(cfg["scroll_pause_ms"])
            page.wait_for_timeout(1500)

            page.screenshot(path=str(outdir / "screen_full.png"), full_page=False)
            (outdir / "raw_page.html").write_text(page.content(), encoding="utf-8")

            # 提取
            data = {"selector": "", "items": []}
            if cfg["card_selector"]:
                items = page.evaluate(EXTRACT_WITH_SELECTOR_JS, cfg["card_selector"])
                data = {"selector": cfg["card_selector"], "items": items}
            if not data["items"]:
                data = page.evaluate(AUTO_EXTRACT_JS)
            items = data["items"][: cfg["max_items"]]

            result = {
                "status": "OK", "url": url, "region": cfg["region"], "mode": cfg["preset"],
                "detected_selector": data.get("selector", ""), "count": len(items),
                "host": socket.gethostname(), "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "items": items,
            }
            (outdir / "trending.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

            # Markdown 报告
            md = [f"# TikTok 热榜 · {cfg['region']} · {cfg['preset']}",
                  f"> 采集时间: {result['ts']} | URL: {url} | 命中卡片: {len(items)} (选择器: {data.get('selector','(自动)')})", ""]
            for it in items:
                md.append(f"**#{it['rank']}** {it['title']}" + (f"  — 🔥{it['metric']}" if it['metric'] else ""))
                if it.get("href"): md.append(f"  - {it['href']}")
            (outdir / "trending.md").write_text("\n".join(md), encoding="utf-8")

            print(f"\n=== 采集完成: {len(items)} 条 ===")
            print(f"  自动识别选择器: {data.get('selector','(无)')}")
            for it in items[:10]:
                print(f"  #{it['rank']} {it['title'][:70]}")

            if cfg.get("report_url"):
                try:
                    req = urllib.request.Request(cfg["report_url"],
                        data=json.dumps(result, ensure_ascii=False).encode(),
                        headers={"Content-Type": "application/json"}, method="POST")
                    if cfg.get("report_token"): req.add_header("X-Report-Token", cfg["report_token"])
                    urllib.request.urlopen(req, timeout=10)
                    print("  [INFO] 已回传云端")
                except Exception as e:
                    print(f"  [WARN] 回传失败(不影响): {e}")
            print(f"\n产物: {outdir}/trending.json · trending.md · screen_full.png · raw_page.html")
            return 0
        finally:
            try: ctx.close()
            except Exception: pass


if __name__ == "__main__":
    sys.exit(main())
