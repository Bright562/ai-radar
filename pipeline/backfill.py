"""一次性回填：把各源仍携带的更早条目按日期分组，补进往期存档。

背景：系统 2026-11-04 才上线，之前的日期没有存档。RSS 源对历史的保留深度不一
（多数中文源只有最近几十条 ≈ 几天；OpenAI / DeepMind 等官方源带几个月存档），所以
近几天补得较全、越早越稀，超过源保留期的日期完全抓不到、不会生成文件。

只写缺档的日期，绝不覆盖已生成的真实存档。用法：python pipeline/backfill.py
"""
import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from build_digest import build, now_cn, TZ_CN  # noqa: E402
from fetcher import fetch_url, parse_feed, parse_html_list  # noqa: E402
from filter import _parse_iso, load_config, process  # noqa: E402
from translate import has_cjk, translate_texts  # noqa: E402

SOURCES_PATH = ROOT / "pipeline" / "config" / "sources.json"
MODELS_PATH = ROOT / "data" / "models.json"
HISTORY_DIR = ROOT / "data" / "history"
BACKFILL_DAYS = 45   # 回填窗口与存档保留期一致
CAP_PER_DAY = 80


def collect_raw() -> list:
    """并发抓所有源，时间窗统一放宽到 BACKFILL_DAYS 天。"""
    sources = [s for s in json.loads(SOURCES_PATH.read_text(encoding="utf-8"))["sources"]
               if s.get("enabled", True)]

    def fetch_one(src):
        text = fetch_url(src["url"], timeout=src.get("timeout", 30))
        if src.get("type") == "html":
            items = parse_html_list(text, src["url"], src["parse"], src["name"])
        else:
            items = parse_feed(text, src["name"])
        for it in items:
            it["maxAgeDays"] = BACKFILL_DAYS
        return items

    raw = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = {pool.submit(fetch_one, s): s for s in sources}
        for fut in as_completed(futs):
            src = futs[fut]
            try:
                got = fut.result()
                raw.extend(got)
                print(f"  [ok]   {src['name']}: {len(got)} 条")
            except Exception as e:  # noqa: BLE001
                print(f"  [skip] {src['name']}: {str(e)[:70]}")
    return raw


def rebuild_index():
    files = sorted(HISTORY_DIR.glob("20*.json"), reverse=True)
    for old in files[45:]:
        old.unlink()
    dates = [f.stem for f in sorted(HISTORY_DIR.glob("20*.json"), reverse=True)]
    (HISTORY_DIR / "index.json").write_text(json.dumps({
        "dates": dates,
        "keepDays": 45,
        "updatedAt": now_cn().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return dates


def main():
    cfg = load_config()
    cfg["maxAgeDays"] = BACKFILL_DAYS
    print(f"[backfill] 抓取 {sum(1 for _ in range(1))} 批源 ...")
    raw = collect_raw()
    print(f"[backfill] 原始 {len(raw)} 条，过滤（时间窗放宽到 {BACKFILL_DAYS} 天）")
    news, _stats = process(raw, cfg, max_keep=500)  # 回填不受每日 120 条上限约束
    print(f"[backfill] 入选 {len(news)} 条，按日期分组")

    by_date = defaultdict(list)
    for n in news:
        dt = _parse_iso(n.get("publishedAt") or "")
        if not dt:
            continue
        by_date[dt.astimezone(TZ_CN).strftime("%Y-%m-%d")].append(n)

    today = now_cn().strftime("%Y-%m-%d")
    existing = {f.stem for f in HISTORY_DIR.glob("20*.json")}
    targets = sorted(d for d in by_date if d not in existing and d < today)
    if not targets:
        print("[backfill] 源里没有可补的历史日期，结束")
        return

    # 英文标题翻译（只翻标题，控制请求数）
    todo, seen = [], set()
    for d in targets:
        for n in by_date[d][:CAP_PER_DAY]:
            if not has_cjk(n["title"]) and n["title"] not in seen:
                seen.add(n["title"])
                todo.append(n["title"])
    pairs = translate_texts(todo[:80]) if todo else {}
    print(f"[backfill] 标题中译 {len(pairs)} 条")

    models = json.loads(MODELS_PATH.read_text(encoding="utf-8"))["models"]
    written = []
    for d in targets:
        day_news = sorted(by_date[d][:CAP_PER_DAY], key=lambda x: -x["relevance"])
        for n in day_news:
            n["titleZh"] = pairs.get(n["title"], "")
            n["summaryZh"] = ""
        digest = build(day_news, models, [],
                       {"fetched": len(day_news), "kept": len(day_news)}, [], [], [])
        digest["date"] = d
        digest["notes"]["backfilled"] = (
            f"回填数据（{now_cn().strftime('%Y-%m-%d')} 生成）：源保留的历史有限，"
            "当天条目可能不全；岗位/开源板块是实时数据无法回溯，故为空")
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        (HISTORY_DIR / f"{d}.json").write_text(
            json.dumps(digest, ensure_ascii=False), encoding="utf-8")
        written.append((d, len(day_news)))
        print(f"  [write] {d}: {len(day_news)} 条")

    dates = rebuild_index()
    print(f"[backfill] 完成：补 {len(written)} 天 -> {dates[-1]} ~ {dates[0]}")


if __name__ == "__main__":
    main()
