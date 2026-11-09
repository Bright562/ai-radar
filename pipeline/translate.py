"""英文 → 中文机器翻译（零 token：不走任何大模型 API，不用任何 key）。

用 Google 翻译的公开 gtx 接口。GitHub Actions（境外网络）直连即可；
本地直连不通时自动退回本机常见代理端口 127.0.0.1:7890；
仍失败就放弃该条，页面回落显示英文原文——翻译是锦上添花，不能阻塞管道。
"""
import json
import re
import time
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

UA = "ai-radar/0.1 (personal news dashboard)"
CJK = re.compile(r"[\u4e00-\u9fff]")
LOCAL_PROXY = "http://127.0.0.1:7890"


def has_cjk(text: str) -> bool:
    """标题里已有中文的（中文源）不需要翻译。"""
    return bool(CJK.search(text or ""))


def _call(opener, text: str) -> str:
    url = ("https://translate.googleapis.com/translate_a/single"
           "?client=gtx&sl=auto&tl=zh-CN&dt=t&q=" + quote(text))
    req = Request(url, headers={"User-Agent": UA})
    with opener.open(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    segs = data[0] or []
    return "".join(s[0] for s in segs if s and s[0]).strip()


def translate_texts(texts: list, delay: float = 0.12) -> dict:
    """把一批英文文本翻成中文，返回 {原文: 译文}。

    通道顺序：上次成功的通道 → 直连 → 本机代理；单条失败跳过，
    连续 5 条失败就提前收工（断网/被限流时不空耗）。
    """
    direct = build_opener(ProxyHandler({}))          # 强制不走代理
    via_proxy = build_opener(ProxyHandler({"http": LOCAL_PROXY, "https": LOCAL_PROXY}))
    good = None
    out, misses = {}, 0
    for text in texts:
        if not text or has_cjk(text):
            continue
        got = ""
        candidates = [good] if good else []
        candidates += [op for op in (direct, via_proxy) if op is not good]
        for op in candidates:
            try:
                got = _call(op, text)
                good = op
                break
            except Exception:  # noqa: BLE001
                continue
        time.sleep(delay)
        if got:
            out[text] = got
            misses = 0
        else:
            misses += 1
            if misses >= 5:
                break
    return out
