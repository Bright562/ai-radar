"""抓取模块：下载并解析 RSS / Atom 源，以及没有 RSS 的新闻列表页（仅用标准库，零依赖）。"""
import gzip
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
from urllib.request import Request, urlopen

UA = "ai-radar/0.1 (personal news dashboard)"


def fetch_url(url: str, timeout: int = 15) -> str:
    """下载一个 URL，处理 gzip，返回解码后的文本。失败由调用方捕获。"""
    req = Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        "Accept-Encoding": "gzip",
    })
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _local(tag: str) -> str:
    """去掉命名空间前缀：{http://...}entry -> entry"""
    return tag.rsplit("}", 1)[-1].lower()


def _clean(text: str) -> str:
    """去内嵌 HTML 标签、解码常见实体、压平空白。"""
    if not text:
        return ""
    text = re.sub(r"<!\[CDATA\[([\s\S]*?)\]\]>", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                 ("&#39;", "'"), ("&apos;", "'"), ("&nbsp;", " ")):
        text = text.replace(a, b)
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(text: str):
    if not text:
        return None
    text = text.strip()
    try:  # RFC 822：RSS2 常见
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (TypeError, ValueError):
        pass
    try:  # ISO 8601：Atom 常见
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return None


def parse_feed(xml_text: str, source_name: str):
    """兼容 RSS2 / Atom / RDF；标准解析失败时退回正则兜底（部分站点的 XML 不规范）。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return _parse_feed_lenient(xml_text, source_name)
    items = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        title = link = date = ""
        summary = ""
        for child in node:
            name = _local(child.tag)
            if name == "title" and not title:
                title = _clean(child.text or "")
            elif name == "link":
                href = (child.get("href") or "").strip()
                if href and (not link or child.get("rel") in (None, "alternate")):
                    link = href
                elif not href and not link and child.text:
                    link = _clean(child.text)
            elif name in ("pubdate", "published") and not date:
                date = _parse_date(child.text) or ""
            elif name in ("updated", "date") and not date:
                date = _parse_date(child.text) or ""
            elif name in ("description", "summary") and not summary:
                summary = _clean(child.text or "")[:400]
            elif name in ("content", "encoded") and not summary:
                summary = _clean(child.text or "")[:400]
        if title and link:
            items.append({
                "title": title,
                "url": link,
                "publishedAt": date,
                "summary": summary,
                "source": source_name,
            })
    return items


def parse_html_list(html_text: str, base_url: str, spec: dict, source_name: str):
    """解析「没有 RSS」的新闻列表页（官网新闻中心等）。

    spec 全在 sources.json 里，站点改版时只改正则、不动代码：
      item  —— 每条新闻的外层块，必须含命名组 url，可选 title/block
      title —— 可选，从块内再提一次标题（用于链接本身没有 title 的站点）
      date  —— 可选，从块内提发布日期
    """
    items, seen = [], set()
    for m in re.finditer(spec["item"], html_text, re.S):
        groups = m.groupdict()
        block = groups.get("block") or m.group(0)
        url = (groups.get("url") or "").strip()
        title = groups.get("title") or ""
        if spec.get("title"):
            t = re.search(spec["title"], block, re.S)
            title = t.group("title") if t else ""
        date = ""
        if spec.get("date"):
            d = re.search(spec["date"], block, re.S)
            date = (_parse_date(_clean(d.group("date"))) or "") if d else ""
        title = _clean(title)
        url = urljoin(base_url, url)
        if not title or not url or url in seen:
            continue
        seen.add(url)
        items.append({
            "title": title,
            "url": url,
            "publishedAt": date,
            "summary": "",
            "source": source_name,
        })
    return items


def _parse_feed_lenient(xml_text: str, source_name: str):
    """正则兜底：只提取 title / link / 时间 / 摘要，容忍不规范的 XML。"""
    items = []
    for block in re.findall(r"<(?:item|entry)[\s>][\s\S]*?</(?:item|entry)>", xml_text):
        t = re.search(r"<title[^>]*>([\s\S]*?)</title>", block)
        l = re.search(r"<link[^>]*href=[\"']([^\"']+)[\"']", block) \
            or re.search(r"<link[^>]*>([\s\S]*?)</link>", block)
        d = re.search(r"<(?:pubDate|published|updated|date)[^>]*>([\s\S]*?)</[^>]+>", block)
        s = re.search(r"<(?:description|summary|content)[^>]*>([\s\S]*?)</[^>]+>", block)
        title = _clean(t.group(1)) if t else ""
        link = (l.group(1) if l else "").strip()
        if title and link:
            items.append({
                "title": title,
                "url": link,
                "publishedAt": _parse_date(_clean(d.group(1))) or "" if d else "",
                "summary": _clean(s.group(1))[:400] if s else "",
                "source": source_name,
            })
    return items
