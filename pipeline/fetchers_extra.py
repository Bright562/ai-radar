"""扩展抓取：招聘岗位（腾讯官网公开接口）与 GitHub 热门 AI 仓库。

现实约束（不要硬碰反爬）：
  - 腾讯招聘官网有公开 GET 检索接口 → 支持自动抓取；
  - 字节/阿里等官网接口需要签名或 Cookie → 失败自动跳过，不影响其它数据；
  - Boss直聘 / 智联没有公开接口、反爬严格 → 暂只能手动补充（data/jobs.manual.json）。
"""
import json
import re
from datetime import timedelta
from urllib.parse import quote
from urllib.request import Request, urlopen

from build_digest import now_cn

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ai-radar/0.1"}


def _get_json(url, data=None, timeout=12):
    headers = dict(UA, Accept="application/json")
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _clean(text, limit=140):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def fetch_tencent_jobs(keyword="前端", pages=2, cap=12):
    """腾讯招聘官网公开检索接口，实习岗位排前。"""
    jobs = []
    for page in range(1, pages + 1):
        url = ("https://careers.tencent.com/tencentcareer/api/post/Query"
               f"?keyword={quote(keyword)}&pageIndex={page}&pageSize=10&language=zh-cn")
        data = _get_json(url)
        posts = (data.get("Data") or {}).get("Posts") or []
        if not posts:
            break
        for p in posts:
            name = p.get("RecruitPostName") or ""
            pid = p.get("PostId")
            if not name or not pid:
                continue
            tags = ["实习" if "实习" in name else "社招"]
            if re.search(r"AI|大模型|LLM|Agent|混元", name, re.I):
                tags.append("AI")
            jobs.append({
                "company": "腾讯",
                "team": p.get("BusinessUnitName") or "",
                "role": name,
                "location": p.get("LocationName") or "",
                "tags": tags,
                "what": _clean(p.get("Responsibility")),
                "url": f"https://careers.tencent.com/jobdesc.html?postId={pid}",
                "postedAt": p.get("LastUpdateTime") or "",
                "auto": True,
                "source": "腾讯招聘官网",
                "_intern": 1 if "实习" in name else 0,
            })
    jobs.sort(key=lambda j: (-j.pop("_intern", 0), j["role"]))
    return jobs[:cap]


def fetch_learning(cap=5, days=21):
    """GitHub 公开搜索接口：近 N 天新出的高星 AI 学习资源（教程/课程仓库）。"""
    since = (now_cn() - timedelta(days=days)).strftime("%Y-%m-%d")
    url = (f"https://api.github.com/search/repositories"
           f"?q=topic:tutorial+created:>{since}&sort=stars&order=desc&per_page=20")
    data = _get_json(url)
    pat = re.compile(r"\b(ai|llm|agents?|gpt|rag|mcp|vllm)\b|大模型|人工智能|机器学习|深度学习", re.I)
    out = []
    for r in (data.get("items") or []):
        text = f"{r.get('name') or ''} {r.get('description') or ''}"
        if not pat.search(text):
            continue
        out.append({
            "name": f"{(r.get('owner') or {}).get('login')}/{r.get('name')}",
            "desc": _clean(r.get("description"), 120),
            "stars": r.get("stargazers_count") or 0,
            "language": r.get("language") or "",
            "url": r.get("html_url"),
        })
    return out[:cap]


def fetch_github_repos(cap=8, days=21):
    """GitHub 公开搜索接口：近 N 天新出的热门 AI 相关仓库（按 star 排序）。"""
    since = (now_cn() - timedelta(days=days)).strftime("%Y-%m-%d")
    repos = []
    for topic in ("llm", "agent", "robotics"):
        url = (f"https://api.github.com/search/repositories"
               f"?q=topic:{topic}+created:>{since}&sort=stars&order=desc&per_page=5")
        try:
            data = _get_json(url)
        except Exception:
            continue
        for r in (data.get("items") or []):
            repos.append({
                "name": f"{(r.get('owner') or {}).get('login')}/{r.get('name')}",
                "desc": _clean(r.get("description"), 120),
                "stars": r.get("stargazers_count") or 0,
                "language": r.get("language") or "",
                "url": r.get("html_url"),
                "topic": topic,
            })
    seen, out = set(), []
    for r in sorted(repos, key=lambda x: -x["stars"]):
        if r["name"] in seen:
            continue
        seen.add(r["name"])
        out.append(r)
    return out[:cap]
