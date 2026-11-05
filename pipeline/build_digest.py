"""组装模块：新闻 + 模型快照 + 岗位种子 → 单一的 digest.json。

digest.json 是整个项目的核心数据契约：
  - 网页仪表盘读它
  - 以后桌面通知端也只比对它的 version/hash
任何一方都不直接抓数据。
"""
from datetime import datetime, timedelta, timezone

SCHEMA = 1
TZ_CN = timezone(timedelta(hours=8))  # Asia/Shanghai


def now_cn() -> datetime:
    return datetime.now(TZ_CN)


def attach_model_news(models: list, news: list) -> None:
    """用 models.json 里的 matchKeywords 把今天的新闻挂到对应模型上。"""
    for m in models:
        kws = [k.lower() for k in m.get("matchKeywords", [m["name"]])]
        m["todayCount"] = sum(1 for n in news if any(k in n["title"].lower() for k in kws))


def build(news: list, models: list, jobs: list, stats: dict, repos: list = None,
          learning: list = None) -> dict:
    now = now_cn()
    models = [dict(m) for m in models]
    attach_model_news(models, news)
    return {
        "schema": 2,
        "date": now.strftime("%Y-%m-%d"),
        "generatedAt": now.isoformat(timespec="seconds"),
        "generator": "ai-radar pipeline 0.2 (zero-token)",
        "stats": stats,
        "news": news,
        "models": models,
        "jobs": jobs,
        "repos": repos or [],
        "learning": learning or [],
        "notes": {
            "modelsAsOf": next((m.get("asOf") for m in models if m.get("asOf")), None),
            "jobsSource": "腾讯招聘官网自动抓取 + 手动维护(data/jobs.manual.json)；Boss/智联无公开接口暂不支持",
            "llmLayer": "未启用；后续接入 LLM 后每条会多一个 why 字段（对前端意味着什么）",
        },
    }
