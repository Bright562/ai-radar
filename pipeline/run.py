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
from fetcher import fetch_url, parse_feed  # noqa: E402
from fetchers_extra import fetch_github_repos, fetch_learning, fetch_tencent_jobs  # noqa: E402
from filter import load_config, process  # noqa: E402

SOURCES_PATH = ROOT / "pipeline" / "config" / "sources.json"
KEYWORDS_PATH = ROOT / "pipeline" / "config" / "keywords.json"
MODELS_PATH = ROOT / "data" / "models.json"
JOBS_PATH = ROOT / "data" / "jobs.manual.json"
OUT_PATH = ROOT / "data" / "digest.json"
HISTORY_DIR = ROOT / "data" / "history"


def collect(sources: list):
    """并发抓所有源；单个源失败不影响其它源。"""
    raw, failures = [], []

    def fetch_one(src):
        return parse_feed(fetch_url(src["url"], timeout=src.get("timeout", 15)), src["name"])

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
    digest = build(news, models, jobs_auto + manual_jobs, stats, repos, learning)
    digest["notes"]["extErrors"] = ext_errors

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    (HISTORY_DIR / f"{digest['date']}.json").write_text(
        json.dumps(digest, ensure_ascii=False), encoding="utf-8")

    print(f"[done] {digest['date']} 入选 {stats['kept']} 条 "
          f"(丢弃: 不相关 {stats['droppedIrrelevant']} / 黑名单 {stats['droppedBlacklist']} / "
          f"过期 {stats['droppedOld']} / 重复 {stats['droppedDuplicate']})")
    print(f"[done] 写入 {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
