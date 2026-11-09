"use strict";

/* AI 雷达前端：只读 data/digest.json，不含任何抓取逻辑。
   支持 ?d=YYYY-MM-DD 查看历史存档（为以后的桌面通知深链预留）。 */

const $ = (sel) => document.querySelector(sel);

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const CATEGORY_LABEL = {
  model: "模型", agent: "Agent", embodied: "具身智能", job: "就业",
  company: "公司", devtools: "前端工程", aitools: "AI 编程", rank: "榜单", interview: "面经",
};

const FILTERS = [
  { id: "all", label: "全部" },
  { id: "model", label: "模型" },
  { id: "agent", label: "Agent" },
  { id: "embodied", label: "具身智能" },
  { id: "aitools", label: "AI 编程工具" },
  { id: "rank", label: "榜单评测" },
  { id: "work", label: "公司与就业" },
  { id: "interview", label: "面经求职" },
  { id: "devtools", label: "前端工程" },
];

const state = { digest: null, filter: "all", showAll: false, isHistory: false, history: [], keepDays: 45, page: 0, showStub: false };
const PREVIEW_COUNT = 30;
const ARCHIVE_PAGE_SIZE = 7; // 存档页标：一页 7 天

/* 大厂动态：从今日新闻流按公司聚合，match 为标题/摘要匹配词 */
const COMPANIES = [
  { key: "字节跳动", match: ["字节", "ByteDance", "豆包", "Seed"] },
  { key: "阿里巴巴", match: ["阿里", "通义", "千问", "Qwen", "夸克"] },
  { key: "腾讯", match: ["腾讯", "混元", "元宝"] },
  { key: "百度", match: ["百度", "文心", "Apollo"] },
  { key: "华为", match: ["华为", "昇腾", "鸿蒙"] },
  { key: "美团", match: ["美团", "LongCat"] },
  { key: "英伟达", match: ["英伟达", "NVIDIA", "CUDA"] },
  { key: "OpenAI", match: ["OpenAI", "ChatGPT"] },
  { key: "谷歌", match: ["谷歌", "Gemini", "DeepMind", "Google"] },
  { key: "Anthropic", match: ["Anthropic", "Claude"] },
  { key: "Meta", match: ["Meta", "Llama"] },
  { key: "宇树科技", match: ["宇树", "Unitree"] },
];

function matchFilter(cat) {
  if (state.filter === "all") return true;
  if (state.filter === "work") return cat === "company" || cat === "job";
  return cat === state.filter;
}

function repoRowHtml(r) {
  const fmt = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
  return `<a class="repo" href="${esc(r.url)}" target="_blank" rel="noopener">
    <div class="repo-top"><span class="repo-name">${esc(r.name)}</span><span class="repo-stars">★ ${fmt(r.stars)}</span></div>
    ${r.desc ? `<div class="repo-desc">${esc(r.desc)}</div>` : ""}
    <div class="repo-meta">${esc(r.language || "")}${r.language ? " · " : ""}${esc(r.meta || "近三周新发布")}</div>
  </a>`;
}

function fmtTime(iso) {
  if (!iso) return "";
  if (state.digest && iso.startsWith(state.digest.date)) return iso.slice(11, 16);
  const parts = iso.slice(0, 10).split("-");
  return parts.length === 3 ? `${+parts[1]}月${+parts[2]}日` : "";
}

/* ---------- 渲染 ---------- */

function render() {
  renderHeader();
  renderChips();
  renderNews();
  renderJobs();
  renderCompanies();
  renderOfficial();
  renderModels();
  renderRepos();
  renderLearning();
  renderArchive();
  renderFoot();
}

function renderHeader() {
  const d = state.digest;
  $("#updated-at").textContent = d ? `更新于 ${d.generatedAt.slice(11, 16)}` : "加载数据…";
  $("#back-today").hidden = !state.isHistory;
  $("#subline").innerHTML = d
    ? `${esc(d.date)} · <b>${d.stats.kept} 条</b>今日动态 · <b>${d.jobs.length}</b> 个在招岗位 · <b>${(d.repos || []).length}</b> 个热门开源 · 共抓取 ${d.stats.fetched} 过滤 ${d.stats.fetched - d.stats.kept}`
    : "正在读取数据…";
}

function renderChips() {
  const d = state.digest;
  const box = $("#chips");
  if (!d) { box.innerHTML = ""; return; }
  box.innerHTML = FILTERS.map((f) => {
    const n = d.news.filter((x) => matchFilterFor(f, x.category)).length;
    const pressed = state.filter === f.id;
    return `<button type="button" class="chip" data-filter="${f.id}" aria-pressed="${pressed}">${f.label}<span class="n">${n}</span></button>`;
  }).join("");
  box.querySelectorAll(".chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.filter = btn.dataset.filter;
      state.showAll = false;
      renderChips();
      renderNews();
    });
  });
}

function matchFilterFor(f, cat) {
  if (f.id === "all") return true;
  if (f.id === "work") return cat === "company" || cat === "job";
  return cat === f.id;
}

function newsItemHtml(n) {
  const tags = (n.tags || []).map((t) => `<span>${esc(t)}</span>`).join("");
  const title = n.titleZh || n.title;
  const enLine = n.titleZh ? `<div class="title-en">${esc(n.title)}</div>` : "";
  const sum = n.summaryZh || n.summary;
  return `<article class="news">
    <div class="meta">
      <span class="src">${esc(n.source)}</span><span>·</span><span>${fmtTime(n.publishedAt)}</span>
      <span class="cat">${CATEGORY_LABEL[n.category] || esc(n.category)}</span>
      <span class="rel" title="相关度 ${n.relevance}/100">${n.relevance}</span>
    </div>
    <a class="title" href="${esc(n.url)}" target="_blank" rel="noopener">${esc(title)}</a>
    ${enLine}
    ${sum && !n.why ? `<p class="sum">${esc(sum)}</p>` : ""}
    ${tags ? `<div class="tags">${tags}</div>` : ""}
  </article>`;
}

function renderNews() {
  const d = state.digest;
  const box = $("#news");
  if (!d) {
    box.innerHTML = `<div class="panel-head"><span class="panel-title">今日要闻</span></div>
      <div class="empty">正在读取数据…</div>`;
    return;
  }
  const head = `<div class="panel-head">
    <span class="panel-title">今日要闻</span>
    <span class="panel-more">按相关度排序</span>
  </div>`;

  if (!d.news.length) {
    box.innerHTML = `${head}<div class="empty">今天暂时没有命中关注范围的内容<br><span class="p-note">没有消息也是一种消息</span></div>`;
    return;
  }
  const list = d.news.filter((n) => matchFilter(n.category));
  if (!list.length) {
    box.innerHTML = `${head}<div class="empty">这个方向今天没有新内容</div>`;
    return;
  }
  const shown = state.showAll ? list : list.slice(0, PREVIEW_COUNT);
  const moreBtn = list.length > shown.length
    ? `<button type="button" class="more-btn" id="more-btn">展开其余 ${list.length - shown.length} 条</button>`
    : "";
  box.innerHTML = head + shown.map(newsItemHtml).join("") + moreBtn;
  const btn = $("#more-btn");
  if (btn) btn.addEventListener("click", () => { state.showAll = true; renderNews(); });
}

function priceRows(m) {
  if (!m.pricing || !m.pricing.length) return `<div class="p-empty">价格以官网为准</div>`;
  const money = (v, cur) => (cur === "CNY" ? `${v} 元` : `$${v}`);
  const rows = m.pricing.map((p) => {
    return `<div class="p-row">
      <span class="p-name">${esc(p.model)}</span>
      <span class="p-val">${money(p.input, p.currency)} / ${money(p.output, p.currency)}</span>
      <span class="p-unit">每百万tokens</span>
    </div>${p.note ? `<div class="p-note">${esc(p.note)}</div>` : ""}`;
  });
  return `<div class="p-rows">${rows.join("")}</div>`;
}

function renderModels() {
  const d = state.digest;
  const box = $("#models");
  if (!d) { box.innerHTML = `<div class="panel-head"><span class="panel-title">模型动向</span></div><div class="empty">…</div>`; return; }
  const asOf = d.notes && d.notes.modelsAsOf ? `快照 ${d.notes.modelsAsOf}` : "";
  const cards = d.models.map((m) => {
    const cls = m.status === "quiet" ? "" : m.status === "milestone" ? "hot" : "live";
    const summary = m.highlights || m.note;
    return `<div class="model">
      <span class="state ${cls}"></span>
      <div class="m-body">
        <div class="m-top"><b>${esc(m.name)}</b><span class="m-pos">${esc(m.positioning)}</span></div>
        <div class="m-latest">旗舰 ${esc(m.latest || "—")} · ${esc(summary)}</div>
        ${priceRows(m)}
        <div class="m-foot">
          ${m.openSource ? `<span class="badge">开源</span>` : ""}
          <span>上下文 ${esc(m.contextWindow)}</span>
          <a href="${esc(m.officialUrl)}" target="_blank" rel="noopener">官网 ↗</a>
          ${m.todayCount ? `<span class="today">今日 ${m.todayCount} 条</span>` : ""}
        </div>
      </div>
    </div>`;
  }).join("");
  box.innerHTML = `<div class="panel-head"><span class="panel-title">模型动向</span><span class="panel-more">${asOf}</span></div>${cards}`;
}

function renderJobs() {
  const d = state.digest;
  const box = $("#jobs");
  if (!d) { box.innerHTML = `<div class="panel-head"><span class="panel-title">岗位雷达</span></div><div class="empty">…</div>`; return; }
  const autoCount = (d.jobs || []).filter((j) => j.auto).length;
  const more = `实习优先 · ${autoCount ? `腾讯官网自动 +` : ""}手动维护`;
  const cards = (d.jobs || []).map((j) => `<div class="job">
    <div class="j-top">
      <b>${esc(j.company)}</b>${j.team ? `<span class="j-team">${esc(j.team)}</span>` : ""}
      ${j.sample ? `<span class="sample">示例</span>` : ""}
      ${(j.tags || []).includes("实习") ? `<span class="intern">实习</span>` : ""}
      ${(j.tags || []).includes("AI") ? `<span class="badge">AI</span>` : ""}
    </div>
    <div class="j-role">${esc(j.role)}<span class="j-loc">${esc(j.location || "")}</span></div>
    ${j.what ? `<div class="j-what">${esc(j.what)}</div>` : ""}
    ${j.url ? `<a class="j-link" href="${esc(j.url)}" target="_blank" rel="noopener">JD 原文 ↗</a>` : ""}
    ${(j.tags || []).length > 1 ? `<div class="tags">${j.tags.filter((t) => t !== "实习" && t !== "AI").map((t) => `<span>${esc(t)}</span>`).join("")}</div>` : ""}
  </div>`).join("");
  box.innerHTML = `<div class="panel-head"><span class="panel-title">岗位雷达</span><span class="panel-more">${more}</span></div>${cards}`;
}

function renderCompanies() {
  const d = state.digest;
  const box = $("#companies");
  if (!d) { box.innerHTML = `<div class="panel-head"><span class="panel-title">大厂动态</span></div><div class="empty">…</div>`; return; }
  const rows = COMPANIES.map((c) => {
    const hits = d.news.filter((n) =>
      c.match.some((k) => n.title.includes(k) || (n.summary || "").includes(k)));
    return { ...c, hits };
  }).filter((c) => c.hits.length)
    .sort((a, b) => b.hits.length - a.hits.length)
    .slice(0, 6);
  if (!rows.length) {
    box.innerHTML = `<div class="panel-head"><span class="panel-title">大厂动态</span></div><div class="empty">今天大厂没有新动态</div>`;
    return;
  }
  const html = rows.map((c) => `<div class="co">
    <div class="co-top"><b>${esc(c.key)}</b><span class="co-n">${c.hits.length} 条</span></div>
    ${c.hits.slice(0, 2).map((n) => `<a class="co-item" href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a>`).join("")}
  </div>`).join("");
  box.innerHTML = `<div class="panel-head"><span class="panel-title">大厂动态</span><span class="panel-more">来自今日新闻流</span></div>${html}`;
}

function renderOfficial() {
  const d = state.digest;
  const box = $("#official");
  if (!box) return;
  if (!d) { box.innerHTML = `<div class="panel-head"><span class="panel-title">官网动态</span></div><div class="empty">…</div>`; return; }
  const rows = (d.official || []).map((o) => `<a class="co-item" href="${esc(o.url)}" target="_blank" rel="noopener">
      <span class="o-src">${esc(o.source.replace(/官网$/, ""))}</span><span class="o-title">${esc(o.titleZh || o.title)}</span>
      <span class="o-date">${o.publishedAt ? esc(o.publishedAt.slice(5, 10)) : ""}</span>
    </a>`).join("");
  const head = `<div class="panel-head"><span class="panel-title">官网动态</span><span class="panel-more">宇树 / 智元 新闻中心</span></div>`;
  box.innerHTML = rows ? head + rows : `${head}<div class="empty">官网暂无新发布</div>`;
}

function renderRepos() {
  const d = state.digest;
  const box = $("#repos");
  if (!d) { box.innerHTML = `<div class="panel-head"><span class="panel-title">开源风向</span></div><div class="empty">…</div>`; return; }
  const rows = (d.repos || []).map(repoRowHtml).join("");
  const empty = `<div class="empty">GitHub 近三周暂无高星新 AI 仓库</div>`;
  box.innerHTML = `<div class="panel-head"><span class="panel-title">开源风向</span><span class="panel-more">GitHub 按星数</span></div>${rows || empty}`;
}

function renderLearning() {
  const d = state.digest;
  const box = $("#learning");
  if (!d) { box.innerHTML = `<div class="panel-head"><span class="panel-title">学习资源</span></div><div class="empty">…</div>`; return; }
  const rows = (d.learning || []).map((r) => repoRowHtml({ ...r, meta: "教程 · 近三周新发布" })).join("");
  const empty = `<div class="empty">暂无新的高星 AI 教程</div>`;
  box.innerHTML = `<div class="panel-head"><span class="panel-title">学习资源</span><span class="panel-more">GitHub AI 教程</span></div>${rows || empty}`;
}

function renderArchive() {
  const box = $("#archive");
  if (!box) return;
  if (!state.history.length) { box.innerHTML = ""; return; }
  const cur = state.digest ? state.digest.date : "";
  const fmtD = (d) => `${+d.slice(5, 7)}月${+d.slice(8, 10)}日`;
  const first = state.history[state.history.length - 1];

  const totalPages = Math.ceil(state.history.length / ARCHIVE_PAGE_SIZE);
  if (state.page >= totalPages) state.page = 0;
  const pageDates = state.history.slice(state.page * ARCHIVE_PAGE_SIZE, (state.page + 1) * ARCHIVE_PAGE_SIZE);

  // 页标：每页 7 天，新→旧；末尾固定一个「更早」页，点开就能看到为什么没有更早的数据
  const tabs = [];
  for (let i = 0; i < state.history.length; i += ARCHIVE_PAGE_SIZE) {
    const ds = state.history.slice(i, i + ARCHIVE_PAGE_SIZE);
    const p = Math.floor(i / ARCHIVE_PAGE_SIZE);
    const cls = !state.showStub && p === state.page ? "page-tab on" : "page-tab";
    tabs.push(`<button type="button" class="${cls}" data-page="${p}">${fmtD(ds[ds.length - 1])} – ${fmtD(ds[0])}</button>`);
  }
  tabs.push(`<button type="button" class="${state.showStub ? "page-tab on muted" : "page-tab muted"}" data-page="stub">更早 · 无存档</button>`);

  const chips = state.showStub
    ? `<div class="empty">这一页还没有存档：系统 ${fmtD(first)} 才开始记录，更早的日期不存在、也没法补。<br>每天自动 +1，这些格子以后会自动填上。</div>`
    : pageDates.map((d) => {
        const cls = d === cur ? "date-chip on" : "date-chip";
        return `<a class="${cls}" href="?d=${d}" title="${d}">${fmtD(d)}</a>`;
      }).join("");

  box.innerHTML = `<div class="archive-head">
      <span>往期存档</span>
      <span class="archive-note">现有 ${state.history.length} 天可回看 · 每天自动 +1，攒满 ${state.keepDays} 天后滚动更新</span>
    </div>
    <div class="page-tabs">${tabs.join("")}</div>
    <div class="date-list">${chips}</div>`;

  box.querySelectorAll(".page-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.page === "stub") {
        state.showStub = true;
      } else {
        state.showStub = false;
        state.page = +btn.dataset.page;
      }
      renderArchive();
    });
  });
}

function renderFoot() {
  const d = state.digest;
  $("#foot").textContent = d
    ? `零 token：抓取、过滤、摘要全部在本地管道完成 · 源 ${d.stats.sourcesOk} 成功 / ${d.stats.sourcesFailed} 失败 · ${d.generator}`
    : "";
}

/* ---------- 错误视图 ---------- */

function renderError(err) {
  $("#updated-at").textContent = "数据未生成";
  $("#subline").textContent = "";
  $("#chips").innerHTML = "";
  $("#news").innerHTML = `<div class="panel-head"><span class="panel-title">今日要闻</span></div>
    <div class="empty">
      <b>还没有生成今日数据</b>
      <p>在项目根目录运行一次管道：</p>
      <code>python pipeline/run.py</code>
      <p>完成后刷新本页即可。</p>
    </div>`;
  $("#jobs").innerHTML = `<div class="panel-head"><span class="panel-title">岗位雷达</span></div><div class="empty">等待数据</div>`;
  $("#companies").innerHTML = `<div class="panel-head"><span class="panel-title">大厂动态</span></div><div class="empty">等待数据</div>`;
  $("#models").innerHTML = `<div class="panel-head"><span class="panel-title">模型动向</span></div><div class="empty">等待数据</div>`;
  $("#repos").innerHTML = `<div class="panel-head"><span class="panel-title">开源风向</span></div><div class="empty">等待数据</div>`;
  $("#learning").innerHTML = `<div class="panel-head"><span class="panel-title">学习资源</span></div><div class="empty">等待数据</div>`;
  $("#official").innerHTML = `<div class="panel-head"><span class="panel-title">官网动态</span></div><div class="empty">等待数据</div>`;
  $("#archive").innerHTML = "";
  $("#foot").textContent = `加载失败：${err.message}`;
}

/* ---------- 入口 ---------- */

async function loadHistoryIndex() {
  try {
    const res = await fetch("data/history/index.json", { cache: "no-store" });
    if (!res.ok) return;
    const idx = await res.json();
    state.history = (idx.dates || []).slice(0, 40);
    if (idx.keepDays) state.keepDays = idx.keepDays;
  } catch (_) {
    /* 没有索引就只显示今天，不影响主视图 */
  }
}

async function load() {
  const d = new URLSearchParams(location.search).get("d");
  state.isHistory = Boolean(d);
  const url = d ? `data/history/${encodeURIComponent(d)}.json` : "data/digest.json";
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}（${url}）`);
    state.digest = await res.json();
    document.title = state.isHistory ? `AI 雷达 · ${state.digest.date}` : "AI 雷达";
    await loadHistoryIndex();
    render();
  } catch (err) {
    renderError(err);
  }
}

load();
