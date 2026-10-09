# TikTok 热榜采集器 · 使用说明(本地跑)

**云端只产脚本, 本地执行**(遵守"云端不装浏览器内核"铁律)。
为 TikTok 反爬专门设计: **持久登录态 + 自动卡片识别 + 多区域**。

## 0. 文件清单
```
run_demo.py        # 主脚本(自包含, 无需其他 .py)
requirements.txt   # 依赖 (playwright)
config.json        # 配置(只改这里, 不改代码)
SETUP.md           # 本说明
```

## 1. 三行部署(本地)
```bash
pip install -r requirements.txt
playwright install chromium
python run_demo.py --login      # 首次: 打开浏览器, 登录 TikTok, 回来按回车
```
> 登录态会存进 `tk_profile/`, 之后无需再登录, 可用 `--headless` 无人值守。

## 2. 采集热榜
```bash
python run_demo.py                          # 默认: 有头 + 印尼热销品榜
python run_demo.py --headless               # 无头(登录态已存)
python run_demo.py --config th.json         # 换配置(如换泰国)
```

## 3. 配置字段(config.json)
| 键 | 说明 | 示例 |
|---|---|---|
| preset | 入口类型 | creative_center_products / creative_center_hashtags / creative_center_songs / tiktok_search / tiktok_discover |
| region | 区域码 | ID / TH / VN / MY / PH / SG / US / GB … |
| query | 搜索词(tiktok_search 用) | kaos oversize |
| url | 自定义网址(填了则覆盖 preset) | https://... |
| headless | 无头模式 | false(首次)/ true(已登录) |
| profile_dir | 登录态目录 | tk_profile |
| scroll_times | 向下滚动次数(加载更多) | 8 |
| card_selector | 卡片 CSS 选择器(**留空=自动识别**) | div[class*="product"] |
| max_items | 最多采集条数 | 40 |
| report_url / report_token | 结果回传云端(可选) | "" |

## 4. 产物(out/)
- `trending.json` — 结构化结果(rank/title/text/metric/img/href)
- `trending.md` — 可读榜单
- `screen_full.png` — 页面截图
- `raw_page.html` — 原始 HTML(识别不准时用来调选择器)

## 5. 识别不准怎么办?
脚本默认"自动卡片识别"(找重复出现、含图片的同类元素)。若结果不对:
1. 跑一次, 打开 `out/raw_page.html`, 用浏览器 F12 找到商品卡片的 class。
2. 把该选择器填进 `config.json` 的 `card_selector`, 重跑即可精确命中。

## 6. 常见问题
- **打不开/空白** → 先 `--login` 登录; TikTok 对未登录+无头极敏感。
- **被验证码拦** → 有头模式手动过; 过完登录态会留存。
- **Creative Center 加载慢** → 调大 `wait_after_load_ms` 与 `scroll_pause_ms`。
- **想采"点赞榜"** → 用 `creative_center_hashtags` 或 `tiktok_search`, 脚本会尽量抽取点赞数(metric 字段)。

## 7. 合规提醒
仅采集公开榜单用于选品分析; 遵守目标站 robots 与当地法规; 勿高频抓取。
