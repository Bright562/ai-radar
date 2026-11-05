"""过滤模块：白名单打分 + 黑名单拦截 + 时间窗 + 去重 + 分类。

这是整个项目里最贴合你需求的部分：
  - 命中黑名单（明星八卦、社会新闻）→ 直接丢弃
  - 超过时间窗的旧闻 → 丢弃（防止 RSS 存档混进今天的看板）
  - 相关度低于阈值 → 丢弃
  - 剩下的按相关度排序、打上分类和标签
所有规则都在 config/keywords.json 里，改配置即可调行为，不用改代码。
"""
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from build_digest import now_cn

CONFIG_PATH = Path(__file__).parent / "config" / "keywords.json"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _is_ascii(kw: str) -> bool:
    return all(ord(c) < 128 for c in kw)


def _contains(kw: str, text: str) -> bool:
    """英文词整词匹配（避免 'ai' 命中 said），中文子串匹配。"""
    if not text:
        return False
    if _is_ascii(kw):
        return re.search(r"\b" + re.escape(kw) + r"\b", text, re.IGNORECASE) is not None
    return kw in text


def _norm_title(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text.lower())


def _bigrams(text: str) -> set:
    if len(text) < 2:
        return {text} if text else set()
    return {text[i:i + 2] for i in range(len(text) - 1)}


def score_item(item: dict, cfg: dict):
    """返回 (relevance, category, tags, blocked)。"""
    title = item.get("title", "")
    summary = item.get("summary", "")

    # 黑名单：标题命中权重直接累计，达到阈值整条拦截
    blocked = sum(w for kw, w in cfg["blacklist"].items() if _contains(kw, title))
    if blocked >= cfg["blacklistBlock"]:
        return 0, "", [], True

    cat_scores = {}
    tags = []
    for cat, kws in cfg["whitelist"].items():
        s = 0.0
        for kw, w in kws.items():
            if _contains(kw, title):
                s += w
                if w >= 20 and kw not in tags:
                    tags.append(kw)
            elif _contains(kw, summary):
                s += w * 0.4  # 摘要命中打折，防止正文提一嘴就混进来
        cat_scores[cat] = s

    relevance = min(100.0, sum(cat_scores.values()))
    if relevance < cfg["minRelevance"]:
        return relevance, "", tags, False

    priority = ["model", "agent", "embodied", "aitools", "rank", "interview", "job", "company", "devtools"]
    category = max(cat_scores, key=lambda c: (cat_scores[c], -priority.index(c)))
    return relevance, category, tags[:4], False


def dedupe(items: list) -> list:
    """标题完全一致或相似度过高（字符二元组 Jaccard >= 0.65）视为同一条。"""
    kept = []
    kept_grams = []
    seen_exact = set()
    for item in items:  # 调用前已按相关度降序
        norm = _norm_title(item["title"])
        if not norm or norm in seen_exact:
            continue
        grams = _bigrams(norm)
        dup = False
        for g in kept_grams:
            inter = len(grams & g)
            if inter and inter / len(grams | g) >= 0.65:
                dup = True
                break
        if dup:
            continue
        seen_exact.add(norm)
        kept_grams.append(grams)
        kept.append(item)
    return kept


def _parse_iso(s: str):
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=now_cn().tzinfo)
    except (ValueError, AttributeError):
        return None


def process(raw_items: list, cfg: dict):
    """原始条目 → (入选新闻, 统计)。相关度降序。"""
    cutoff = now_cn() - timedelta(days=cfg.get("maxAgeDays", 3))
    scored, blocked_ct, low_ct, old_ct = [], 0, 0, 0
    for item in raw_items:
        # 时间窗：太旧的丢弃（没有日期的保留，宁滥勿缺由相关度兜底）
        dt = _parse_iso(item.get("publishedAt") or "")
        if dt and dt < cutoff:
            old_ct += 1
            continue
        rel, cat, tags, blocked = score_item(item, cfg)
        if blocked:
            blocked_ct += 1
            continue
        if rel < cfg["minRelevance"] or not cat:
            low_ct += 1
            continue
        item = dict(item)
        item["id"] = hashlib.sha1(item["url"].encode("utf-8")).hexdigest()[:10]
        item["relevance"] = round(rel)
        item["category"] = cat
        item["tags"] = tags
        scored.append(item)

    scored.sort(key=lambda x: x.get("publishedAt") or "", reverse=True)  # 时间新→旧
    scored.sort(key=lambda x: -x["relevance"])  # 稳定排序：相关度优先，同分内保持时间序
    kept = dedupe(scored)[:120]

    stats = {
        "fetched": len(raw_items),
        "kept": len(kept),
        "droppedIrrelevant": low_ct,
        "droppedBlacklist": blocked_ct,
        "droppedOld": old_ct,
        "droppedDuplicate": len(scored) - len(kept),
    }
    return kept, stats
