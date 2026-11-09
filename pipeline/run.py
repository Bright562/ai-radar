"""入口：抓取 -> 过滤 -> 组装 -> 写入 data/digest.json。

用法：
  python pipeline/run.py            # 正式运行（联网抓取，不消耗任何 API token）
  python pipeline/run.py --fixture  # 离线测试：用 tests/sample_items.json 演示过滤效果
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from build_digest import build, now_cn  # noqa: E402
from fetcher import fetch_url, parse_feed, parse_html_list  # noqa: E402
from fetchers_extra import fetch_github_repos, fetch_learning, fetch_tencent_jobs  # noqa: E402
from filter import load_config, process  # noqa: E402
from translate import has_cjk, translate_texts  # noqa: E402

SOURCES_PATH = ROOT / "pipeline" / "config" / "sources.json"
KEYWORDS_PATH = ROOT / "pipeline" / "config" / "keywords.json"
MODELS_PATH = ROOT / "data" / "models.json"
JOBS_PATH = ROOT / "data" / "jobs.manual.json"
OUT_PATH = ROOT / "data" / "digest.json"
HISTORY_DIR = ROOT / "data" / "history"
HISTORY_KEEP_DAYS = 45  # 存档保留天数：错过几天也能回看（用户要求至少半个月，留 3 倍余量）


def collect(sources: list):
    """并发抓所有源；单个源失败不影响其它源。"""
    raw, failures = [], []

    def fetch_one(src):
        text = fetch_url(src["url"], timeout=src.get("timeout", 15))
        if src.get("type") == "html":  # 没有 RSS 的官网新闻页
            items = parse_html_list(text, src["url"], src["parse"], src["name"])
        else:
            items = parse_feed(text, src["name"])
        if src.get("maxAgeDays"):
            for it in items:
                it["maxAgeDays"] = src["maxAgeDays"]
        if src.get("official"):
            for it in items:
                it["official"] = True
        return items

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(fetch_one, s): s for s in sources}
        for fut in as_completed(futures):
            src = futures[fut]
            try:
                got = fut.result()
                raw.extend(got)
                print(f"  [ok]   {src['name']}: {len(got)} 条")
            except Exception as e:  # noqa: BLE001
                failures.append({"source": src["name"], "error": str(e)[:120]})
                print(f"  [skip] {src['name']}: {str(e)[:80]}")
    return raw, failures


def pick_official(raw: list, per_source: int = 4) -> list:
    """官网新闻中心的最新动态：不走时间窗过滤，单独成栏（官网更新慢，几个月一条也正常）。
    按来源轮流取，避免更新勤的那家把另一家挤掉。"""
    by_src = {}
    for it in raw:
        if it.get("official"):
            by_src.setdefault(it["source"], []).append(it)
    picked = []
    for items in by_src.values():
        items.sort(key=lambda x: x.get("publishedAt") or "", reverse=True)
        picked.extend(items[:per_source])
    picked.sort(key=lambda x: x.get("publishedAt") or "", reverse=True)
    return [{
        "title": it["title"],
        "url": it["url"],
        "publishedAt": it.get("publishedAt") or "",
        "source": it["source"],
    } for it in picked]


def save_history(digest: dict):
    """按天存档 + 只保留最近 N 天 + 生成日期索引（网页「往期」读它）。"""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    (HISTORY_DIR / f"{digest['date']}.json").write_text(
        json.dumps(digest, ensure_ascii=False), encoding="utf-8")
    files = sorted(HISTORY_DIR.glob("20*.json"), reverse=True)
    for old in files[HISTORY_KEEP_DAYS:]:
        old.unlink()
    dates = [f.stem for f in sorted(HISTORY_DIR.glob("20*.json"), reverse=True)]
    (HISTORY_DIR / "index.json").write_text(json.dumps({
        "dates": dates,
        "keepDays": HISTORY_KEEP_DAYS,
        "updatedAt": now_cn().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", action="store_true", help="离线模式：使用内置样例数据")
    args = ap.parse_args()

    cfg = load_config()
    sources = [s for s in json.loads(SOURCES_PATH.read_text(encoding="utf-8"))["sources"] if s.get("enabled", True)]

    failures = []
    if args.fixture:
        fixture = ROOT / "pipeline" / "tests" / "sample_items.json"
        raw = json.loads(fixture.read_text(encoding="utf-8"))
        print(f"[fixture] 使用样例数据 {len(raw)} 条（不联网）")
    else:
        print(f"[fetch] {len(sources)} 个源，开始抓取 ...")
        raw, failures = collect(sources)
        print(f"[fetch] 共 {len(raw)} 条原始条目")

    news, stats = process(raw, cfg)
    stats["sourcesOk"] = 0 if args.fixture else len(sources) - len(failures)
    stats["sourcesFailed"] = 0 if args.fixture else len(failures)

    models = json.loads(MODELS_PATH.read_text(encoding="utf-8"))["models"]
    manual_jobs = json.loads(JOBS_PATH.read_text(encoding="utf-8"))["jobs"]

    # 扩展抓取：岗位与开源仓库（各自独立降级，失败不影响主流程）
    ext_errors = []
    try:
        jobs_auto = fetch_tencent_jobs(keyword="前端")
        print(f"[jobs] 腾讯招聘官网 {len(jobs_auto)} 个前端岗位（实习优先）")
    except Exception as e:  # noqa: BLE001
        jobs_auto = []
        ext_errors.append(f"腾讯岗位: {str(e)[:80]}")
        print(f"[jobs] 腾讯岗位抓取失败: {str(e)[:80]}")
    try:
        repos = fetch_github_repos()
        print(f"[repos] GitHub 热门 AI 仓库 {len(repos)} 个")
    except Exception as e:  # noqa: BLE001
        repos = []
        ext_errors.append(f"GitHub 仓库: {str(e)[:80]}")
        print(f"[repos] GitHub 抓取失败: {str(e)[:80]}")
    try:
        learning = fetch_learning()
        print(f"[learning] GitHub AI 教程资源 {len(learning)} 个")
    except Exception as e:  # noqa: BLE001
        learning = []
        ext_errors.append(f"学习资源: {str(e)[:80]}")
        print(f"[learning] 学习资源抓取失败: {str(e)[:80]}")

    stats["jobsAuto"] = len(jobs_auto)
    stats["repos"] = len(repos)
    official = pick_official(raw)
    stats["official"] = len(official)

    # 英文自动中译：中文为主、英文原文保留在页面上（零 token，走公开翻译接口；
    # 失败时 titleZh/summaryZh 留空，页面回落英文原文，不阻塞管道）
    try:
        todo = {}
        for n in news:
            if not has_cjk(n["title"]):
                todo.setdefault(n["title"])
            if n.get("summary") and not has_cjk(n["summary"]):
                todo.setdefault(n["summary"])
        for o in official:
            if not has_cjk(o["title"]):
                todo.setdefault(o["title"])
        pairs = translate_texts(list(todo)[:80])
        for n in news:
            n["titleZh"] = pairs.get(n["title"], "")
            n["summaryZh"] = pairs.get(n["summary"], "") if n.get("summary") else ""
        for o in official:
            o["titleZh"] = pairs.get(o["title"], "")
        stats["translated"] = sum(1 for v in pairs.values() if v)
        print(f"[translate] 英文中译 {stats['translated']} 条")
    except Exception as e:  # noqa: BLE001
        stats["translated"] = 0
        print(f"[translate] 翻译失败，全部回落英文: {str(e)[:80]}")

    digest = build(news, models, jobs_auto + manual_jobs, stats, repos, learning, official)
    digest["notes"]["extErrors"] = ext_errors

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
    save_history(digest)

    print(f"[done] {digest['date']} 入选 {stats['kept']} 条 "
          f"(丢弃: 不相关 {stats['droppedIrrelevant']} / 黑名单 {stats['droppedBlacklist']} / "
          f"过期 {stats['droppedOld']} / 重复 {stats['droppedDuplicate']})")
    print(f"[done] 写入 {OUT_PATH.relative_to(ROOT)}，存档保留 {HISTORY_KEEP_DAYS} 天")


if __name__ == "__main__":
    main()
