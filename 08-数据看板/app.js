/* 开源掌机 · 数据看板 前端 —— 除「网盘」页签的填 cookie / 管账号之外全部只读;
   读走 /api/*,唯一的写出口是 POST /api/netdisk/action(只有看板绑回环时服务端才收) */
'use strict';

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (n) => (n == null ? '' : Number(n).toLocaleString('zh-CN'));

const LS = {
  get(k, d) { try { const v = localStorage.getItem('kanban.' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('kanban.' + k, JSON.stringify(v)); } catch (e) { } }
};

const st = {
  view: LS.get('view', 'overview'),
  loaded: {},
  news: { offset: 0, limit: 200, total: 0, facets: null },
  games: { offset: 0, limit: 300, total: 0, ds: '', facets: null },
  repos: { offset: 0, limit: 300, total: 0, ds: '', facets: null },
  factory: { offset: 0, limit: 300, total: 0, ds: '', status: '', facets: null },
  reports: { list: null, path: '' },
};

function hint(msg) {
  const el = $('#loadHint');
  el.innerHTML = msg ? ('<span class="spin"></span> ' + esc(msg)) : '';
}

async function get(url) {
  hint('读取中');
  try {
    const r = await fetch(url, { cache: 'no-store' });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    return j;
  } catch (e) {
    hint('');
    alert('读取失败:' + e.message + '\n(服务是否还开着?)');
    throw e;
  } finally {
    hint('');
  }
}

const qs = (params) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== '' && v != null) p.set(k, v);
  return p.toString();
};

/* ---------------------------------------------------------------- 概览 */

async function loadOverview(force) {
  if (st.loaded.overview && !force) return;
  const [o, s] = await Promise.all([get('/api/overview'), get('/api/sources?only=')]);
  st.loaded.overview = true;

  const cards = [
    { k: '资讯条目', v: num(o.news.total), s: `源 <b>${num(o.news.sources)}</b> 个 · HOT <b>${num(o.news.hot)}</b> · 大作登陆 <b>${num(o.news.arrival)}</b> · 带聚焦标签 <b>${num(o.news.focus)}</b><br>发布日跨度 ${esc(o.news.date_min)} ~ ${esc(o.news.date_max)}` },
    { k: '订阅源', v: num(s.total), s: `启用 <b>${num(o.sources.enabled)}</b> · 本轮(${esc(localTime(s.run_utc))})新入库 <b>${num(s.run_new)}</b> · 失败 <b>${num((s.failures || []).length)}</b>` },
    { k: '游戏/成品包', v: num(o.games.total), s: `本地已落盘 <b>${num(o.games.local)}</b> · 台账有记录但缺文件 <b style="color:var(--bad)">${num(o.games.missing)}</b> · 记录体积约 <b>${bytes(o.games.bytes)}</b><br>${o.games.by_ds.map((d) => `${esc(dsName(d.ds))} ${num(d.count)}`).join(' · ')}` },
    { k: '仓库/项目', v: num(o.repos.total), s: `本地已落盘 <b>${num(o.repos.local)}</b> · 缺文件 <b style="color:var(--bad)">${num(o.repos.missing)}</b><br>${o.repos.by_ds.map((d) => `${esc(dsName(d.ds))} ${num(d.count)}`).join(' · ')}` },
    { k: '报告与文档', v: num(o.reports.total), s: '日报/周报/专题 + 教程与说明书,「报告」页里直接看' },
    { k: '移植工厂', v: num(o.factory.total), s: `接单 <b>${num(o.factory.jobs)}</b> · 函数判定 verified <b>${num(o.factory.verified_modules)}</b> · 产物在本地 <b>${num(o.factory.local)}</b> · 路径对不上 <b style="color:var(--bad)">${num(o.factory.missing)}</b><br>${o.factory.by_ds.map((d) => `${esc(dsName(d.ds))} ${num(d.count)}`).join(' · ')}` },
  ];
  $('#cards').innerHTML = cards.map((c) => `<div class="card"><div class="k">${c.k}</div><div class="v">${c.v}</div><div class="s">${c.s}</div></div>`).join('');

  const days = o.news.days || [];
  const max = Math.max(1, ...days.map((d) => d.count));
  $('#trend').innerHTML = days.map((d, i) =>
    `<div class="bar" style="height:${Math.max(2, Math.round(120 * d.count / max))}px" title="${esc(d.day)} ${d.count} 条">
       <span>${esc(d.day.slice(5))} · ${num(d.count)} 条</span>${i % 5 === 0 ? `<i>${esc(d.day.slice(5))}</i>` : ''}</div>`).join('');

  const rows = [];
  rows.push('<thead><tr><th>数据集</th><th>条数</th><th>本地在</th><th>本地缺</th><th>记录体积</th><th>事实源文件</th></tr></thead><tbody>');
  const pushSet = (arr, files) => arr.forEach((d) => {
    const f = files.find((x) => x.ds === d.ds) || {};
    rows.push(`<tr><td>${esc(dsName(d.ds))}</td><td class="num">${num(d.count)}</td>
      <td class="num">${d.local ? `<span class="tag ok">${num(d.local)}</span>` : '<span class="muted">—</span>'}</td>
      <td class="num">${d.missing ? `<span class="tag bad">${num(d.missing)}</span>` : '<span class="muted">—</span>'}</td>
      <td class="num">${d.bytes ? bytes(d.bytes) : '<span class="muted">—</span>'}</td>
      <td class="mono clamp" title="${esc(f.file || '')}">${esc(f.file || '-')}${f.exists === false ? ' <span class="tag bad">文件缺失</span>' : ''}</td></tr>`);
  });
  pushSet(o.games.by_ds, o.datasets_files.games);
  pushSet(o.repos.by_ds, o.datasets_files.repos);
  pushSet(o.factory.by_ds, o.datasets_files.factory);
  rows.push('</tbody>');
  $('#dsTable').innerHTML = rows.join('');

  $('#hotList').innerHTML = (o.recent_hot || []).map((n) => linkItem(n)).join('') || '<li class="muted">无</li>';
  $('#arrList').innerHTML = (o.recent_arrival || []).map((n) => linkItem(n)).join('') || '<li class="muted">无</li>';

  const f = s.failures || [];
  $('#failTable').innerHTML = '<thead><tr><th>源</th><th>HTTP</th><th>状态</th><th>解析</th></tr></thead><tbody>' +
    (f.length ? f.map((x) => `<tr><td>${esc(x.name)}</td><td class="num">${esc(x.http)}</td><td>${esc(x.status)}</td><td class="num">${esc(x.parsed)}</td></tr>`).join('')
      : '<tr><td colspan="4" class="muted">本轮没有失败源</td></tr>') + '</tbody>';
}

function linkItem(n) {
  return `<li><span class="meta">${esc(n.date)}</span><a href="${esc(n.url)}" target="_blank" rel="noreferrer">${esc(n.title)}</a>
    <span class="meta">— ${esc(n.source)}</span>${n.focus ? ` <span class="tag focus">${esc(n.focus)}</span>` : ''}</li>`;
}

function localTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return isNaN(d) ? String(iso) : d.toLocaleString('zh-CN', { hour12: false });
}

function bytes(n) {
  if (!n) return '0';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0, v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return (v >= 100 ? Math.round(v) : v.toFixed(1)) + ' ' + u[i];
}

function dsName(ds) {
  return (DS_LABELS[ds] || ds);
}
const DS_LABELS = {
  pm_r36s: 'PortMaster R36S 全清单', pm_pool: 'ports 全量合法池', pm_watch: 'PortMaster 端口快照',
  hot: '爆款收录(本地包)', rescue: '下架抢救(快照存档)', assets: '免费素材',
  ps5: 'PS5 移植商店目录', major: '移植大作(端口项目)',
  clone: '已 clone 到本地仓库', legal: '合法收录登记表', s2repo: 'Switch2 仓库登记',
  s2fetch: 'Switch2 抓取台账', s2bundle: 'Switch2 bundle 台账', ps5repo: 'PS5 仓库底账',
  ps5asset: 'PS5 成品包台账', rescue_reg: '下架抢救登记表', error: '读取失败',
  pf_jobs: '接单(移植任务)', pf_games: '收件登记(输入二进制)', pf_runs: '静态分析运行',
  pf_modules: '函数级判定', pf_attempts: 'AI 请求尝试', pf_gates: '闸门结果',
  pf_stages: '流水线阶段', pf_artifacts: '制品(成品包)', pf_devices: '设备', pf_events: '动作流水',
};

/* ---------------------------------------------------------------- 资讯 */

async function newsFacets(force) {
  if (st.news.facets && !force) return st.news.facets;
  const f = await get('/api/news_facets');
  st.news.facets = f;
  $('#nkind').innerHTML = '<option value="">全部类型</option>' + f.kinds.map((k) => `<option value="${esc(k.kind)}">${esc(k.kind)} (${num(k.count)})</option>`).join('');
  $('#nsource').innerHTML = '<option value="">全部源(237)</option>' + f.sources.map((s) =>
    `<option value="${esc(s.source_id)}">${esc(s.source || s.source_id)} (${num(s.count)})</option>`).join('');
  return f;
}

async function loadNews() {
  await newsFacets(st.loaded.newsFacets ? false : true);
  st.loaded.newsFacets = true;
  const p = {
    q: $('#nq').value.trim(), flag: $('#nflag').value, kind: $('#nkind').value,
    source: $('#nsource').value, since: $('#nsince').value, until: $('#nuntil').value,
    order: $('#norder').value, offset: st.news.offset, limit: st.news.limit,
  };
  const r = await get('/api/news?' + qs(p));
  st.news.total = r.total;
  const rows = r.rows.map((n) => `
    <tr>
      <td class="nowrap mono">${esc(n.date)}</td>
      <td class="nowrap">${n.hot ? '<span class="tag hot">HOT</span> ' : ''}${n.arrival ? '<span class="tag arr">ARR</span> ' : ''}${n.focus ? `<span class="tag focus">${esc(n.focus)}</span>` : ''}</td>
      <td class="nowrap">${esc(n.source)}</td>
      <td><a href="${esc(n.url)}" target="_blank" rel="noreferrer">${esc(n.title)}</a>
          ${n.note ? `<div class="sub muted">${esc(n.note)}</div>` : ''}</td>
      <td class="nowrap muted mono">${esc(n.seen)}</td>
    </tr>`).join('');
  $('#newsTable').innerHTML = `<thead><tr><th>发布日</th><th>标记</th><th>源</th><th>标题</th><th>入库</th></tr></thead><tbody>${rows || ''}</tbody>`
    + (r.rows.length ? '' : '<tbody><tr><td colspan="5" class="empty">这个筛选下没有条目</td></tr></tbody>');
  $('#nstat').innerHTML = `共 <b>${num(r.total)}</b> 条 · 显示 ${num(r.offset + 1)}–${num(r.offset + r.rows.length)}`;
  $('#npages').textContent = `第 ${Math.floor(r.offset / r.limit) + 1} 页 / 每页 ${r.limit}`;
}

/* ---------------------------------------------------------------- 游戏 / 库 */

function tableHead(kind) {
  const extra = kind === 'factory' ? '要求' : '自备';
  return `<thead><tr><th></th><th>名称</th><th>数据集</th><th>平台/类型</th><th>许可</th><th>体积</th><th>${extra}</th><th>状态</th><th>日期</th><th>去处</th></tr></thead>`;
}

function rowHtml(r, i) {
  const link = r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noreferrer">原文</a>` : '';
  const go = r.url ? link : (r.local ? `<span class="mono ext">${esc(r.local)}</span>` : '<span class="muted">—</span>');
  const needs = r.needs ? `<span class="tag needs">${esc(r.needs)}</span>` : '';
  let status = '';
  if (r.status) {
    const s = String(r.status);
    const bad = /MISMATCH|FAIL|不一致|缺失|blocked|unsupported|deferred|waiting_ai|未接真机/i.test(s);
    const ok = /OK|已下载|上架|启用|pass|verified|已真机验收/i.test(s);
    status = `<span class="tag ${bad ? 'bad' : ok ? 'ok' : ''}">${esc(s)}</span>`;
  }
  if (r.expect && !r.has) status += ` <span class="tag bad">本地缺文件</span>`;
  else if (r.has) status += ` <span class="tag ok">在本地</span>`;
  return `<tr data-i="${i}">
    <td class="rowtoggle" data-toggle="${i}">▸</td>
    <td class="name">${esc(r.name)}${r.title && r.title !== r.name ? `<div class="sub clamp">${esc(r.title)}</div>` : ''}</td>
    <td class="nowrap muted">${esc(dsName(r.ds))}</td>
    <td class="nowrap">${esc(r.platform || '')}</td>
    <td class="nowrap">${esc(r.license || '')}</td>
    <td class="num">${esc(r.size || '')}</td>
    <td class="needs">${needs}</td>
    <td class="status">${status}</td>
    <td class="nowrap mono">${esc(r.date || '')}</td>
    <td class="nowrap">${go}</td>
  </tr>`;
}

function detailHtml(r) {
  const kv = [];
  if (r.note) kv.push(['说明', esc(r.note)]);
  if (r.local) kv.push(['本地', `<span class="mono">${esc(r.local)}</span>`]);
  for (const [k, v] of Object.entries(r.x || {})) {
    if (v === '' || v == null) continue;
    kv.push([k, esc(String(v))]);
  }
  if (r.url) kv.push(['URL', `<a href="${esc(r.url)}" target="_blank" rel="noreferrer">${esc(r.url)}</a>`]);
  if (!kv.length) kv.push(['—', '这张表没有额外字段']);
  return `<tr class="detail"><td colspan="10"><table>${kv.map(([k, v]) => `<tr><th>${esc(k)}</th><td class="kv">${v}</td></tr>`).join('')}</table></td></tr>`;
}

function bindToggle(tbl, rows) {
  tbl.onclick = (e) => {
    const cell = e.target.closest('[data-toggle]');
    if (!cell) return;
    const i = Number(cell.dataset.toggle);
    const tr = cell.closest('tr');
    const next = tr.nextElementSibling;
    if (next && next.classList.contains('detail')) { next.remove(); cell.textContent = '▸'; return; }
    tbl.querySelectorAll('.detail').forEach((d) => d.remove());
    tbl.querySelectorAll('.rowtoggle').forEach((c) => (c.textContent = '▸'));
    tr.insertAdjacentHTML('afterend', detailHtml(rows[i]));
    cell.textContent = '▾';
  };
}

const KIND = {
  games: { q: '#gq', flag: '#gflag', sort: '#gsort', reset: '#greset', chips: '#gchips', tbl: '#gamesTable', stat: '#gstat', pages: '#gpages', prev: '#gprev', next: '#gnext' },
  repos: { q: '#rq', flag: '#rflag', sort: '#rsort', reset: '#rreset', chips: '#rchips', tbl: '#reposTable', stat: '#rstat', pages: '#rpages', prev: '#rprev', next: '#rnext' },
  factory: { q: '#fq', flag: '#fflag', sort: '#fsort', reset: '#freset', chips: '#fchips', tbl: '#factoryTable', stat: '#fstat', pages: '#fpages', prev: '#fprev', next: '#fnext', status: '#fstatus' },
};

async function loadTable(kind) {
  const cfg = st[kind], el = KIND[kind];
  const p = {
    q: $(el.q).value.trim(),
    flag: $(el.flag).value,
    sort: $(el.sort).value,
    desc: $(el.sort).value === 'name' ? '0' : '1',
    status: el.status ? $(el.status).value : '',
    ds: cfg.ds, offset: cfg.offset, limit: cfg.limit,
  };
  const fresh = !cfg.facets;
  const [fac, r] = await Promise.all([
    cfg.facets ? Promise.resolve(cfg.facets) : get(`/api/${kind}_facets`),
    get(`/api/${kind}?` + qs(p)),
  ]);
  cfg.facets = fac;
  cfg.total = r.total;
  if (el.status && fresh) {
    const keep = $(el.status).value;
    $(el.status).innerHTML = '<option value="">全部状态</option>' +
      fac.statuses.map((s) => `<option value="${esc(s.status)}">${esc(s.status)} (${num(s.count)})</option>`).join('');
    $(el.status).value = keep;
  }
  const jumps = kind === 'factory'
    ? [['local', '有产物'], ['missing', '路径对不上']]
    : [['needs', '要自备'], ['local', '已落盘'], ['missing', '本地缺文件'], ['broken', '校验不一致']];
  const chips = `<span class="chip ${cfg.ds === '' ? 'on' : ''}" data-ds="">全部 <b>${num(fac.total)}</b></span>` +
    fac.ds.map((d) => `<span class="chip ${cfg.ds === d.ds ? 'on' : ''}" data-ds="${esc(d.ds)}">${esc(dsName(d.ds))} <b>${num(d.count)}</b>${d.local ? ` · 本地 ${num(d.local)}` : ''}${d.missing ? ` · <span style="color:var(--bad)">缺 ${num(d.missing)}</span>` : ''}</span>`).join('') +
    jumps.map(([k, lbl]) => `<span class="chip" data-jump="${k}">${lbl} <b>${num(fac.flags[k])}</b></span>`).join('');
  $(el.chips).innerHTML = chips;
  // 空结果要说清是哪些条件叠出来的,否则用户以为数据没了
  const conds = [cfg.ds && dsName(cfg.ds),
    p.flag && ((jumps.find((j) => j[0] === p.flag) || [p.flag, p.flag])[1]),
    p.status && '状态 ' + p.status, p.q && '关键词「' + p.q + '」'].filter(Boolean);
  const tbl = $(el.tbl);
  tbl.innerHTML = tableHead(kind) + '<tbody>' + r.rows.map((x, i) => rowHtml(x, i)).join('') +
    (r.rows.length ? '' : `<tr><td colspan="10" class="empty">没有命中条目${conds.length ? `（当前条件：${esc(conds.join(' + '))}；去掉一个再看）` : ''}</td></tr>`) + '</tbody>';
  bindToggle(tbl, r.rows);
  $(el.stat).innerHTML = `共 <b>${num(r.total)}</b> 条 · 显示 ${num(r.offset + 1)}–${num(r.offset + r.rows.length)}`;
  $(el.pages).textContent = `第 ${Math.floor(r.offset / cfg.limit) + 1} 页 / 每页 ${cfg.limit}`;
}

/* ---------------------------------------------------------------- 报告 */

async function loadReports(force) {
  if (st.reports.list && !force) return st.reports.list;
  const list = await get('/api/reports');
  st.reports.list = list;
  const groups = Array.from(new Set(list.map((d) => d.group)));
  $('#dgroup').innerHTML = '<option value="">全部组</option>' + groups.map((g) => `<option value="${esc(g)}">${esc(g)} (${list.filter((d) => d.group === g).length})</option>`).join('');
  renderDocList();
  const first = list.find((d) => d.group === '资讯专题' && d.name === 'README.md') || list[0];
  if (first) openDoc(first.path);
  return list;
}

function renderDocList() {
  const term = $('#dq').value.trim().toLowerCase();
  const g = $('#dgroup').value;
  const items = (st.reports.list || []).filter((d) => (!g || d.group === g) && (!term || d.path.toLowerCase().includes(term)));
  let last = '';
  $('#docList').innerHTML = items.map((d) => {
    const head = d.group !== last ? `<li class="g">${esc(d.group)}</li>` : '';
    last = d.group;
    return `${head}<li data-path="${esc(d.path)}" class="${d.path === st.reports.path ? 'on' : ''}">
      <div>${esc(d.name)}</div><span class="p">${esc(d.sub === d.group ? '' : d.sub)} ${esc(d.mtime)} · ${bytes(d.bytes)}</span>
      <span class="p">${esc(d.path)}</span></li>`;
  }).join('') + (items.length ? '' : '<li class="muted">没有匹配文件</li>');
  $('#docList').onclick = (e) => {
    const li = e.target.closest('li[data-path]');
    if (li) openDoc(li.dataset.path);
  };
}

async function openDoc(path) {
  st.reports.path = path;
  $$('#docList li').forEach((li) => li.classList.toggle('on', li.dataset.path === path));
  const d = await get('/api/doc?' + qs({ path }));
  $('#docHead').innerHTML = `<b>${esc(d.name)}</b> · <span class="mono">${esc(d.path)}</span> · 改于 ${esc(d.mtime)} · ${bytes(d.bytes)}`
    + ` · <a href="${esc('/api/doc?' + qs({ path }))}" target="_blank" rel="noreferrer">原文</a>`;
  $('#docBody').innerHTML = d.name.toLowerCase().endsWith('.txt')
    ? `<pre>${esc(d.content)}</pre>` : mdToHtml(d.content);
  $('.docpane').scrollTop = 0;
}

function mdToHtml(src) {
  const lines = String(src).replace(/\r\n/g, '\n').split('\n');
  const out = [];
  let i = 0, para = [], table = null, list = null, fence = null;
  const flushPara = () => { if (para.length) { out.push('<p>' + inline(para.join(' ')) + '</p>'); para = []; } };
  const flushList = () => { if (list) { out.push(`<${list.tag}>` + list.items.map((x) => `<li>${inline(x)}</li>`).join('') + `</${list.tag}>`); list = null; } };
  const flushTable = () => {
    if (!table) return;
    const head = table.rows[0];
    const body = table.rows.slice(table.sep ? 1 : 1);
    out.push('<table><thead><tr>' + head.map((c) => `<th>${inline(c)}</th>`).join('') + '</tr></thead><tbody>' +
      body.map((r) => '<tr>' + r.map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table>');
    table = null;
  };
  const splitRow = (ln) => ln.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());

  while (i < lines.length) {
    const ln = lines[i];
    if (/^```/.test(ln)) {
      if (fence === null) { flushPara(); flushList(); flushTable(); fence = []; }
      else { out.push('<pre><code>' + esc(fence.join('\n')) + '</code></pre>'); fence = null; }
      i++; continue;
    }
    if (fence !== null) { fence.push(ln); i++; continue; }
    if (/^\s*\|.*\|\s*$/.test(ln)) {
      flushPara(); flushList();
      const cells = splitRow(ln);
      if (!table) table = { rows: [cells], sep: false };
      else if (/^[\s|:-]+$/.test(ln)) { table.sep = true; }
      else table.rows.push(cells);
      i++; continue;
    }
    flushTable();
    if (/^#{1,6}\s/.test(ln)) {
      flushPara(); flushList();
      const lvl = Math.min(6, (ln.match(/^#+/) || ['#'])[0].length);
      out.push(`<h${lvl}>${inline(ln.replace(/^#+\s*/, ''))}</h${lvl}>`);
      i++; continue;
    }
    if (/^\s*(-\s*\*\*\*|\*\*\*|___)\s*$/.test(ln)) { flushPara(); flushList(); out.push('<hr>'); i++; continue; }
    if (/^\s*>\s?/.test(ln)) {
      flushPara(); flushList();
      const buf = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) { buf.push(lines[i].replace(/^\s*>\s?/, '')); i++; }
      out.push('<blockquote>' + inline(buf.join(' ')) + '</blockquote>');
      continue;
    }
    const lm = ln.match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/);
    if (lm) {
      flushPara();
      const tag = /\d/.test(lm[2]) ? 'ol' : 'ul';
      if (!list || list.tag !== tag) { flushList(); list = { tag, items: [] }; }
      list.items.push(lm[3]);
      i++; continue;
    }
    flushList();
    if (ln.trim() === '') { flushPara(); i++; continue; }
    para.push(ln.trim());
    i++;
  }
  if (fence !== null) out.push('<pre><code>' + esc(fence.join('\n')) + '</code></pre>');
  flushPara(); flushList(); flushTable();
  return out.join('\n');
}

function inline(s) {
  let t = esc(s);
  t = t.replace(/`([^`]+)`/g, (m, c) => '<code>' + c + '</code>');
  t = t.replace(/\*\*([^*]+)\*\*/g, (m, c) => '<b>' + c + '</b>');
  t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, (m, a, c) => a + '<i>' + c + '</i>');
  t = t.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, (m, txt, url) =>
    `<a href="${url}" target="_blank" rel="noreferrer">${txt}</a>`);
  t = t.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, (m, a, url) => `${a}<a href="${url}" target="_blank" rel="noreferrer">${url}</a>`);
  return t;
}

/* ---------------------------------------------------------------- 源 */

async function loadSources() {
  const p = { q: $('#sq').value.trim(), only: $('#sonly').value };
  const r = await get('/api/sources?' + qs(p));
  $('#sourcesTable').innerHTML = `<thead><tr><th>用</th><th>源</th><th>id</th><th>类型</th><th>台账</th><th>HOT</th>
    <th>最后发布</th><th>本轮 HTTP</th><th>解析</th><th>新入</th><th>备注</th></tr></thead><tbody>` +
    r.rows.map((s) => `<tr>
      <td>${s.enabled === '1' ? '<span class="tag ok">开</span>' : '<span class="tag off">关</span>'}</td>
      <td><a href="${esc(s.url)}" target="_blank" rel="noreferrer">${esc(s.name)}</a></td>
      <td class="mono muted nowrap">${esc(s.id)}</td>
      <td class="nowrap muted">${esc(s.kind || '—')}</td>
      <td class="num">${num(s.count)}</td>
      <td class="num">${num(s.hot)}</td>
      <td class="mono nowrap">${esc(s.last || '')}</td>
      <td class="num ${s.http && s.http !== '200' ? 'muted' : ''}">${esc(s.http || '')}</td>
      <td class="num">${esc(s.parsed || '')}</td>
      <td class="num">${esc(s.new || '')}</td>
      <td class="clamp" title="${esc(s.note)}">${esc(s.note)}</td>
    </tr>`).join('') + '</tbody>';
  $('#sstat').innerHTML = `共 <b>${num(r.total)}</b> 个源 · 本轮 ${esc(localTime(r.run_utc))} 新入 <b>${num(r.run_new)}</b> · 台账累计 <b>${num(r.ledger_total)}</b>`;
}

/* ---------------------------------------------------------------- 网盘(读 + 这一页的写) */

const nd = { last: null, cache: {}, gridDriver: '', edit: false, wired: false,
             timer: null, busy: false, shotUrl: '', ticks: 0, slot: '1' };

async function ndFields(driver) {
  if (nd.cache[driver]) return nd.cache[driver];
  const j = await get('/api/netdisk_fields?driver=' + encodeURIComponent(driver));
  if (j && j.ok) nd.cache[driver] = j;
  return j;
}

function ndMsg(text, ok) {
  const el = $('#ndMsg');
  el.className = 'stat' + (ok == null ? '' : (ok ? ' ok' : ' bad'));
  el.textContent = text || '';
}

async function ndPost(body, quiet) {
  if (!quiet) hint('提交中');
  let j;
  try {
    const r = await fetch('/api/netdisk/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    j = await r.json().catch(() => ({ ok: false, msg: 'HTTP ' + r.status + ',没回 JSON' }));
    j.status = r.status;
  } catch (e) {
    j = { ok: false, msg: '发不出去:' + e.message + '(看板还开着吗?)' };
  } finally {
    if (!quiet) hint('');
  }
  return j;
}

/* ---------------------------------------------------------------- 网盘:扫码登录这一条 */

function qrText(html, cls) {
  const el = $('#qrState');
  el.className = 'qrstate' + (cls ? ' ' + cls : '');
  el.innerHTML = html;
}

function ndSchema(driver) {
  const r = nd.last || {};
  if (nd.cache[driver]) return nd.cache[driver];
  if (r.schema && r.schema.driver === driver) return r.schema;
  return {};
}

function qrPaintSlots(driver, s) {
  // 一格登录位 = 一个独立 profile = 一个号的登录态;十格并排摆出来,谁占着哪格一目了然
  const sel = $('#qrSlot');
  const who = {};
  (((nd.last || {}).accounts) || []).filter((a) => a.driver === driver)
    .forEach((a) => { who[a.slot || 1] = a.alias; });
  const rows = s.qr_slots || [];
  sel.innerHTML = rows.length ? rows.map((r) => {
    const st = r.listening ? '窗口开着' : (who[r.slot] ? ('登着 ' + who[r.slot])
      : (r.profile_exists ? '有登录态残留' : '空'));
    return `<option value="${r.slot}">第 ${r.slot} 槽 · 端口 ${r.port} · ${st}</option>`;
  }).join('') : '<option value="1">第 1 槽 ·（账号台没带登录位表）</option>';
  if (!rows.length || !rows.some((r) => String(r.slot) === String(sel.value))) sel.value = '1';
  nd.slot = sel.value;

  const ex = $('#qrExe');
  const bs = (s.qr_browsers || {}).ok || [];
  ex.innerHTML = bs.length ? bs.map((b, i) =>
    `<option value="${esc(b.exe)}">${esc(b.file)} ${esc(b.version)}${i === 0 ? ' ·默认' : ''}</option>`).join('')
    : '<option value="">（本机没找到能开调试端口的浏览器）</option>';
  const bad = ((s.qr_browsers || {}).unusable || []).map((u) => u.file + '(' + u.why + ')').join(' ');
  ex.title = '这一格的窗口用哪个浏览器开。' + (bad ? ' 本机装了但用不了:' + bad : '');
}

function qrHead() {
  const driver = $('#ndDriver').value;
  const s = ndSchema(driver);
  const kind = s.login_kind || '';
  $('#qrStart').textContent = kind === 'qrcode' ? '▶ 打开扫码窗口' : '▶ 打开登录窗口';
  $('#qrShotHint').textContent = kind === 'qrcode'
    ? '窗口没开着。按上面『▶ 打开扫码窗口』,这里就实时显示那个二维码。'
    : '这个盘在 OpenList 里不吃 cookie,扫码/开窗口只当看内容;挂载要的东西在下面「手填凭据」里。';
  qrPaintSlots(driver, s);
  $('#qrHowto').innerHTML = esc(s.login_howto || '账号台没说这个盘怎么登录 —— 只能走下面「手填凭据」。')
    .replace(/\n/g, '<br>')
    + '<br><b>换第 2 个号怎么做:</b>把上面『登录位』调到第 2 槽再点打开 —— 每一格是一个独立 profile、'
    + '各装一个号的登录态,扫第二个号不会把第一个号顶掉;十个号就是十格。'
    + '(日常浏览器里已经登着的号捞不过来:Edge/Chrome 新版 cookie 是 App-Bound 加密,别的进程解不开,而且本机日常浏览器里也没登夸克 —— 详见 06-资讯监控\\网盘上传\\README.md 第 10 节。)';
  if (kind === 'password' || kind === 'oauth') $('#ndForm').open = true;
}

function qrStopPoll() {
  if (nd.timer) { clearInterval(nd.timer); nd.timer = null; }
}

function qrStartPoll() {
  qrStopPoll();
  nd.ticks = 0;
  qrTick();
  nd.timer = setInterval(qrTick, 2000);
}

function qrPaintInfo(q) {
  const rows = [
    ['登录位', `第 <b>${num(q.slot || 1)}</b> 槽 <span class="muted">${esc(q.profile || '')}${q.profile_exists ? '(profile 在)' : '(还没建)'} · 一共 ${num(q.max_slot || 10)} 格</span>`],
    ['窗口', q.listening ? `<span class="tag ok">在听</span> <span class="mono">127.0.0.1:${num(q.port)}</span>${q.exe ? ' <span class="muted">' + esc(q.exe) + '</span>' : ''}` : '<span class="tag off">没开着</span>'],
    ['开于', esc(q.started_at || '—')],
    ['页面到', `<span class="mono clamp" title="${esc(q.url || '')}">${esc(q.url || '—')}</span>`],
    ['抓到 cookie', `${num(q.cookie_count || 0)} 条 <span class="muted">${esc((q.cookie_names || q.names || []).slice(0, 12).join(' '))}${(q.cookie_names || q.names || []).length > 12 ? ' …' : ''}</span>`],
    ['登录标志', (q.markers || []).map((m) => {
      const has = (q.markers_have || []).indexOf(m) >= 0;
      return `<span class="tag ${has ? 'ok' : 'off'}">${esc(m)}</span>`;
    }).join(' ') || '<span class="muted">—</span>'],
    ['网盘认账', q.login_ok ? '<span class="tag ok">认了(是真账号)</span>'
      : '<span class="tag off">还没认(游客不算登录)</span>'],
    ['这一问的话', `<span class="muted" title="${esc(q.msg || '')}">${esc((q.msg || '').slice(0, 90)) || '—'}</span>`]
  ];
  $('#qrInfo').innerHTML = '<tbody>' + rows.map((r) => `<tr><td class="name nowrap">${r[0]}</td><td>${r[1]}</td></tr>`).join('') + '</tbody>';
}

async function qrShot() {
  const driver = $('#ndDriver').value;
  const img = $('#qrImg');
  try {
    const r = await fetch('/api/netdisk/shot?driver=' + encodeURIComponent(driver)
      + '&slot=' + encodeURIComponent(nd.slot) + '&t=' + Date.now());
    if (!r.ok) {
      img.hidden = true;
      $('#qrShotHint').hidden = false;
      $('#qrShotHint').textContent = '现在没画面(窗口没开着,或调试端口没回话)';
      return;
    }
    const url = URL.createObjectURL(await r.blob());
    if (nd.shotUrl) URL.revokeObjectURL(nd.shotUrl);
    nd.shotUrl = url;
    img.src = url;
    img.hidden = false;
    $('#qrShotHint').hidden = true;
  } catch (e) {
    img.hidden = true;
  }
}

async function qrTick() {
  if (nd.busy) return;                       // 一次问没回来就跳过这拍,别把请求堆起来
  nd.busy = true;
  const driver = $('#ndDriver').value;
  try {
    const j = await ndPost({ action: 'qr', phase: 'poll', driver, slot: nd.slot }, true);
    nd.ticks++;
    if (j.qr && j.qr.already) {                // 这一槽登着的就是库里那个号:别再转圈,也别再写库
      qrStopPoll();
      qrPaintInfo(j.qr);
      qrText('<span class="tag off">这一槽本来就登着</span> ' + esc(j.msg), 'off');
      return;                                  // 窗口和画面都留着,啥也不动
    }
    if (j.ok && j.account) {                 // 抓到了、也存进库了:收工
      qrStopPoll();
      $('#qrImg').hidden = true;
      $('#qrShotHint').hidden = false;
      $('#qrShotHint').textContent = '窗口已关,不用再扫了。';
      qrText('<span class="tag ok">登录成功</span> ' + esc(j.msg), 'ok');
      await loadNetdisk();
      return;
    }
    if (j.qr) qrPaintInfo(Object.assign({ phase: 'poll' }, j.qr));
    qrText((j.ok ? '<span class="tag off">等着扫码</span> ' : '<span class="tag bad">没成</span> ')
      + esc(j.msg || '网盘还没认这个会话')
      + ` <span class="muted">(第 ${num(nd.ticks)} 问)</span>`);
    if (j.qr && j.qr.listening) await qrShot();
  } finally {
    nd.busy = false;
  }
}

async function qrRefreshSlots() {
  const driver = $('#ndDriver').value;
  delete nd.cache[driver];                    // 窗口开没开是端口的事,登录位表不能拿缓存
  const s = await ndFields(driver);
  if (s && s.ok) qrPaintSlots(driver, s);
}

async function qrPhase(phase) {
  const driver = $('#ndDriver').value;
  const slot = nd.slot;
  const r = (nd.last || {}).account || {};
  if (!r.writable) return qrText('<span class="tag bad">写侧锁着</span> ' + esc(r.write_blocked || '看板绑了非回环地址'), 'bad');
  if (phase === 'purge' && !confirm('删掉第 ' + slot + ' 槽那套独立 profile(' + driver + ')?\n里面是浏览器自己存的登录态,删了这一格下次要重新扫;别的槽不受影响,账号库里的凭据也不受影响。')) return;
  qrStopPoll();
  qrText('<span class="tag off">处理中</span> ' + esc(phase === 'start' ? ('在第 ' + slot + ' 槽开浏览器窗口……') : '问账号台……'));
  const j = await ndPost({ action: 'qr', phase, driver, slot, exe: $('#qrExe').value });
  if (j.qr) qrPaintInfo(Object.assign({ phase }, j.qr));
  await qrRefreshSlots();
  if (phase === 'start' && j.ok) {
    qrText('<span class="tag ok">窗口开好了</span> ' + esc(j.msg) + ' <span class="muted">这里每 2 秒自动问一次,这一页关着也有看板服务端每 15 秒自己巡一遍,扫上就自己入库,不用回来填东西。</span>', 'ok');
    qrStartPoll();
  } else {
    $('#qrImg').hidden = true;
    $('#qrShotHint').hidden = false;
    qrText((j.ok ? '<span class="tag ok">好了</span> ' : '<span class="tag bad">没成</span> ') + esc(j.msg));
    if (phase !== 'start' && j.qr && j.qr.listening) qrStartPoll();
  }
  return j;
}

function ndWatch(w) {
  // 网页没开着也能收号,靠的是看板自己起的那根看守线程 —— 状态得让人看见,不然又是一次"没反应"。
  if (!w || !w.on) return '<span class="tag bad">服务端看守没起</span> 扫完号得把这一页开着才会入库(重启看板才有看守)';
  const bits = ['每 <b>' + num(w.every_sec) + '</b> 秒自己问一遍开着的窗口(这一页没开着也收)'];
  if (w.cycle) bits.push('已问 <b>' + num(w.cycle) + '</b> 轮' + (w.last_at ? '(最后 ' + esc(w.last_at) + ')' : ''));
  if ((w.held || []).length) bits.push('已处理过、不重复问:' + w.held.map(esc).join('、'));
  if (w.why) bits.push('<span class="tag bad">' + esc(w.why) + '</span>');
  if (w.last_err) bits.push('最近一次没成:' + esc(w.last_err));
  return '<span class="tag ok">服务端看守在跑</span> ' + bits.join(' · ');
}

function qrResume(r) {
  // 页面刷新/切回这一页时:窗口要是还开着,接着盯,别让按钮变成唯一线索
  if (nd.timer || !r.account || !r.account.writable) return;
  const driver = $('#ndDriver').value;
  const s = ndSchema(driver);
  if (!s.login_kind) return;
  // 开着的那个窗口可能在别的登录位(命令行开的、或上一轮留的),下拉却还停在第 1 格 —— 先跟过去,
  // 不然页面盯着一格空位问,真扫上号的那格没人管(11-05 就这么"没反应"过一次)。
  const rows = s.qr_slots || [];
  const cur = rows.filter((x) => String(x.slot) === String(nd.slot))[0];
  if (!cur || !cur.listening) {
    const other = rows.filter((x) => x.listening)[0];
    if (other && String(other.slot) !== String(nd.slot)) {
      nd.slot = String(other.slot);
      $('#qrSlot').value = nd.slot;
    }
  }
  ndPost({ action: 'qr', phase: 'poll', driver, slot: nd.slot }, true).then((j) => {
    if (j.qr && j.qr.already) { qrPaintInfo(j.qr); qrText('<span class="tag off">这一槽本来就登着</span> ' + esc(j.msg), 'off'); return; }
    if (j.qr && j.qr.listening) { qrPaintInfo(j.qr); qrStartPoll(); }
  });
}

/* 只把值交给 POST,交完立刻从 DOM 里抹掉 —— 看板这侧不留副本、不进 localStorage、不打日志 */
function ndCollect() {
  const fields = {};
  $$('#ndFields input').forEach((i) => { if (i.value !== '') fields[i.dataset.name] = i.value; });
  return {
    action: 'save', alias: $('#ndAlias').value.trim(), driver: $('#ndDriver').value,
    remark: $('#ndRemark').value.trim(), fields, edit: nd.edit
  };
}

function ndClearSecrets() {
  $$('#ndFields input.secret').forEach((i) => { i.value = ''; });
}

async function ndRun(body) {
  const r = nd.last || {};
  if (body.action !== 'start' && r.account && !r.account.writable) {
    ndMsg('写侧是锁着的:' + (r.account.write_blocked || '看板绑了非回环地址'), false);
    return;
  }
  if (body.action === 'del' && !confirm('删掉 ' + body.alias + '?\n先删 OpenList 的挂载点,删掉了才抹库里这条密文。')) return;
  const j = await ndPost(body);
  ndMsg(j.msg, j.ok);
  if (j.ok && body.action === 'save') ndClearSecrets();
  await loadNetdisk();
}

async function ndPaintFields(force) {
  const driver = $('#ndDriver').value;
  if (!driver) return;
  if (!force && nd.gridDriver === driver) return;
  const grid = $('#ndFields');
  grid.innerHTML = '<p class="muted note">正在向本机 OpenList 取 ' + esc(driver) + ' 的字段表……</p>';
  const s = await ndFields(driver);
  nd.gridDriver = driver;
  if (!s.ok) {
    grid.innerHTML = '<p class="muted note">字段表没拿到:' + esc(s.msg || '未知原因') +
      ' —— 这张表单出不了。格子是账号台向<b>在跑的</b> OpenList 现取的,它没起来就没有字段表(下面「拉起 OpenList」)。</p>';
    return;
  }
  grid.innerHTML = s.fields.map((f) => {
    const t = f.secret ? ' secret' : '';
    const ph = f.secret ? (nd.edit ? '留空 = 保持原值(已存 ' + '密文' + ')' : 'DPAPI 加密后入库,页面不回显')
      : (f.default ? '默认 ' + f.default : '');
    const type = f.secret ? 'password' : 'text';
    return `<label><span>${esc(f.name)}${f.required ? ' <b class="req">＊</b>' : ''}` +
      `${f.type ? ' <span class="ftype">' + esc(f.type) + '</span>' : ''}</span>` +
      `<input class="mono${t}" data-name="${esc(f.name)}" type="${type}" autocomplete="off" spellcheck="false" placeholder="${esc(ph)}">` +
      `</label>`;
  }).join('') + (s.no_upload ?
    '<p class="muted note">这个盘的驱动在 OpenList 里是<b>只读</b>(拿得到但传不上去)—— 挂它只能下载,别指望它当备份目的地。</p>' : '');
}

function ndPaintDrivers(r) {
  const sel = $('#ndDriver');
  const list = r.drivers || [];
  const sig = list.map((d) => d.driver).join(',');
  if (sel.dataset.sig === sig) return;
  sel.dataset.sig = sig;
  sel.innerHTML = list.map((d) => `<option value="${esc(d.driver)}">${esc(d.label)}</option>`).join('');
  nd.gridDriver = '';
}

async function ndLockPane(r) {
  const a = r.account || {};
  const box = $('#ndLock');
  const inputs = $$('#ndForm input, #ndForm button, #ndForm select, #ndDriver, #qrSlot, #qrExe, #qrStart, #qrClose, #qrPurge');
  if (a.writable) {
    box.innerHTML = '';
    inputs.forEach((i) => { i.disabled = false; });
    return;
  }
  box.innerHTML = `<p class="note"><span class="tag bad">写侧已锁</span> ${esc(
    a.write_blocked || a.load_error || '账号台模块读不进来,这张表单出不了')}</p>`;
  inputs.forEach((i) => { i.disabled = true; });
  qrStopPoll();
  $('#qrImg').hidden = true;
  $('#qrShotHint').hidden = false;
}

function ndWireOnce() {
  if (nd.wired) return;
  nd.wired = true;
  $('#ndDriver').onchange = () => { nd.edit = false; qrHead(); ndPaintFields(true); };
  $('#qrSlot').onchange = () => {
    nd.slot = $('#qrSlot').value || '1';
    qrStopPoll();
    $('#qrImg').hidden = true;
    $('#qrShotHint').hidden = false;
    qrText('<span class="tag off">换到第 ' + esc(nd.slot) + ' 槽</span> 这一格是另一个独立 profile;'
      + '按『▶ 打开扫码窗口』开这一格的窗口,扫进去的是新号,不会动别的槽那个号。');
  };
  $('#qrExe').onchange = () => {
    const t = ($('#qrExe').selectedOptions[0] || {}).textContent || '';
    qrText('<span class="tag off">窗口改用 ' + esc(t) + '</span> 只管下一格新开的窗口;'
      + '已经开着的那个不受影响 —— 要换浏览器就先按『关掉窗口』再重开。');
  };
  $('#qrStart').onclick = () => qrPhase('start');
  $('#qrClose').onclick = () => qrPhase('close');
  $('#qrPurge').onclick = () => qrPhase('purge');
  $('#ndSave').onclick = () => {
    const b = ndCollect();
    if (!b.alias) return ndMsg('先起个别名(小写字母/数字/-/_,2~24 位,例如 quark-03)', false);
    if (!Object.keys(b.fields).length) return ndMsg('一格都没填,没东西可存', false);
    ndRun(b);
  };
  $('#ndClear').onclick = () => {
    nd.edit = false;
    $('#ndAlias').value = ''; $('#ndRemark').value = '';
    $$('#ndFields input').forEach((i) => { i.value = ''; });
    ndMsg('清空了,下一条从头填');
  };
  $('#ndStart').onclick = () => ndRun({ action: 'start' });
  $('#ndAccountTable').onclick = (e) => {
    const b = e.target.closest('button');
    if (!b || !b.dataset.act) return;
    const alias = b.dataset.alias;
    if (b.dataset.act === 'edit') return ndStartEdit(b.dataset.driver, alias, b.dataset.remark);
    ndRun({ action: b.dataset.act, alias });
  };
}

async function ndStartEdit(driver, alias, remark) {
  $('#ndDriver').value = driver;
  nd.edit = true;
  $('#ndForm').open = true;
  qrHead();
  $('#ndAlias').value = alias;
  $('#ndRemark').value = remark || '';
  await ndPaintFields(true);
  $('#ndForm').scrollIntoView({ block: 'center' });
  ndMsg('在改 ' + alias + ':哪格要换就填哪格,留空的 secret 字段保持原值', null);
}

async function loadNetdisk() {
  const r = await get('/api/netdisk');
  nd.last = r;
  const state = (b) => b ? '<span class="tag ok">在跑</span>' : '<span class="tag bad">没在跑</span>';
  const yn = (b, a, c) => b ? `<span class="tag ok">${a}</span>` : `<span class="tag off">${c}</span>`;

  $('#ndCards').innerHTML = [
    { k: 'OpenList 服务', v: r.openlist.listening ? '在跑' : '没在跑', s: `127.0.0.1:${num(r.openlist.port)} ${state(r.openlist.listening)} · 程序 <b>${r.openlist.exists ? '在' : '缺失'}</b> ${bytes(r.openlist.bytes)}(${esc(r.openlist.mtime || '')})<br><span class="mono clamp">${esc(r.openlist.path)}</span>` },
    { k: '账号台(逻辑层)', v: r.account.writable ? '能写' : '只读', s: `模块 ${r.account.loadable ? '<span class="tag ok">读进来了</span>' : '<span class="tag bad">读不进来</span>'} · 接口齐 <b>${r.account.has_api ? '是' : '否'}</b> · 扫码模块 ${yn(r.account.qr_ready, '在', '没装好')} · 当前绑 <b class="mono">${esc(r.bind || '')}</b><br>管理员口令环境变量 ${yn(r.account.needs_admin_pw, '已设', '没设')}(只看有没有设,不取值)<br>${ndWatch(r.account.watch)}<br><span class="mono clamp">${esc(r.account.path)}</span>` },
    { k: '账号库', v: num(r.store.total) + ' 个号', s: `活跃 <b>${num(r.store.active)}</b> · 探测有效 <b>${num(r.store.ok)}</b> · 没探过 <b>${num(r.store.unprobed)}</b> · 库里实际 <b>${num(r.store.raw_total)}</b> 条<br>文件 ${r.store.exists ? (r.store.readable ? '在且能解析' : '在但解析不出 JSON') : '不存在'} ${bytes(r.store.bytes)}(${esc(r.store.mtime || '')})<br><span class="mono clamp">${esc(r.store.path)}</span>` },
    { k: '上传台账', v: num(r.ledger.total) + ' 条', s: Object.entries(r.ledger.by_status).map(([k, v]) => `${esc(k)} <b>${num(v)}</b>`).join(' · ') + ` · 记录体积 <b>${bytes(r.ledger.bytes)}</b><br>挂载点分布:${Object.entries(r.ledger.by_mount).map(([k, v]) => ` ${esc(k)} <b>${num(v)}</b>`).join(' · ') || ' —'}<br>最近一条 ${esc(r.ledger.last_at || '—')}` },
    { k: '上传档位', v: num(r.scopes.length) + ' 档', s: `enable=1 的 <b>${num(r.scopes.filter((s) => s.enable === '1').length)}</b> · 还指着 /本地暂存的 <b>${num(r.scopes.filter((s) => s.mount.indexOf('本地暂存') >= 0).length)}</b> · 目录缺失 <b>${num(r.scopes.filter((s) => !s.dir_exists).length)}</b>` },
  ].map((c) => `<div class="card"><div class="k">${c.k}</div><div class="v">${c.v}</div><div class="s">${c.s}</div></div>`).join('');

  ndPaintDrivers(r);
  if (r.schema && r.schema.ok) nd.cache[r.schema.driver] = r.schema;
  ndWireOnce();
  $('#ndOlLink').href = r.openlist.url || '#';
  await ndPaintFields(false);
  qrHead();
  await ndLockPane(r);   // 排在出格子之后:格子是新建的 DOM,锁得最后盖一遍
  if (r.account.writable) qrResume(r);
  if (!r.account.qr_ready) {
    qrStopPoll();
    qrText('<span class="tag bad">扫码这条走不了</span> ' + esc(r.account.qr_err || '账号台没带扫码模块')
      + ' —— 手填凭据那条还能用。', 'bad');
  }

  $('#ndDriverTable').innerHTML = '<thead><tr><th>网盘</th><th>账号</th><th>活跃</th><th>探测有效</th><th>失效</th><th>没探过</th></tr></thead><tbody>' +
    r.by_driver.map((d) => `<tr><td class="name">${esc(d.label)}</td><td class="num">${num(d.total)}</td>
      <td class="num">${d.active ? `<span class="tag ok">${num(d.active)}</span>` : '<span class="muted">—</span>'}</td>
      <td class="num">${d.ok ? `<span class="tag ok">${num(d.ok)}</span>` : '<span class="muted">—</span>'}</td>
      <td class="num">${d.bad ? `<span class="tag bad">${num(d.bad)}</span>` : '<span class="muted">—</span>'}</td>
      <td class="num">${num(d.total - d.ok - d.bad)}</td></tr>`).join('') + '</tbody>';

  $('#ndAccountTable').innerHTML = r.accounts.length ?
    '<thead><tr><th>盘</th><th>别名</th><th>ID</th><th>账号名</th><th>登录位</th><th>会员档</th><th>挂载点</th><th>活跃</th><th>最近探测</th><th>结论</th><th>文件数</th><th>备注</th><th>密文长</th><th>缺必填</th><th>操作</th></tr></thead><tbody>' +
    r.accounts.map((a) => `<tr>
      <td class="nowrap">${esc(a.driver_label || a.driver)}</td>
      <td class="mono nowrap">${esc(a.alias)}</td>
      <td class="mono nowrap" title="${esc(a.ident_msg || '')}">${a.uid ? esc(a.uid) : '<span class="muted">没认出</span>'}</td>
      <td class="nowrap">${a.nickname ? esc(a.nickname) : '<span class="muted">—</span>'}</td>
      <td class="num nowrap" title="一格登录位=一个独立 profile=一个号的登录态">第 ${num(a.slot || 1)} 槽</td>
      <td class="nowrap">${a.member ? `<span class="tag off">${esc(a.member)}</span>` : '<span class="muted">—</span>'}</td>
      <td class="mono nowrap">${esc(a.mount_path)}</td>
      <td>${a.active ? '<span class="tag ok">活跃</span>' : '<span class="tag off">备用</span>'}</td>
      <td class="mono nowrap">${esc(a.last_check || '没探过')}</td>
      <td class="status">${a.last_ok ? `<span class="tag ok">有效</span>` : (a.last_check ? `<span class="tag bad">失效</span>` : '<span class="tag off">—</span>')} <span class="muted" title="${esc(a.last_msg || '')}">${esc((a.last_msg || '').slice(0, 60))}</span></td>
      <td class="num">${a.items >= 0 ? num(a.items) : '<span class="muted">—</span>'}</td>
      <td class="clamp" title="${esc(a.remark || '')}">${esc(a.remark || '')}</td>
      <td class="num">${num(a.cipher_len)}</td>
      <td class="num">${a.missing_required ? `<span class="tag bad">${num(a.missing_required)}</span>` : '<span class="muted">—</span>'}</td>
      <td class="ops"><button class="ghost" data-act="check" data-alias="${esc(a.alias)}">探测</button>
        <button class="ghost" data-act="use" data-alias="${esc(a.alias)}">切</button>
        <button class="ghost" data-act="edit" data-alias="${esc(a.alias)}" data-driver="${esc(a.driver)}" data-remark="${esc(a.remark || '')}">改凭据</button>
        <button class="ghost" data-act="del" data-alias="${esc(a.alias)}">删</button></td>
    </tr>`).join('') + '</tbody>'
    : '<tbody><tr><td class="empty">账号库是空的 —— 一次都没登录过。按上面『▶ 打开扫码窗口』扫一下就行,不用手填。</td></tr></tbody>';

  $('#ndScopeTable').innerHTML = '<thead><tr><th>档位</th><th>本地目录</th><th>网盘前缀</th><th>挂到</th><th>enable</th><th>台账已记</th><th>体积</th><th>最近</th><th>说明</th></tr></thead><tbody>' +
    r.scopes.map((s) => `<tr>
      <td class="name">${esc(s.name)}</td>
      <td class="mono nowrap">${esc(s.dir)} ${s.dir_exists ? '<span class="tag ok">在</span>' : '<span class="tag bad">缺</span>'}</td>
      <td class="mono">${esc(s.remote_prefix)}</td>
      <td class="mono nowrap">${esc(s.mount)}${s.mount.indexOf('本地暂存') >= 0 ? ' <span class="tag needs">没出网盘</span>' : ''}</td>
      <td>${s.enable === '1' ? '<span class="tag ok">开</span>' : `<span class="tag off">关(${esc(s.enable || '空')})</span>`}</td>
      <td class="num">${num(s.uploaded)}</td>
      <td class="num">${s.uploaded_bytes ? bytes(s.uploaded_bytes) : '<span class="muted">—</span>'}</td>
      <td class="mono nowrap">${esc(s.last_at || '—')}</td>
      <td class="clamp" title="${esc(s.note)}">${esc(s.note)}</td>
    </tr>`).join('') + '</tbody>';

  const stat = Object.entries(r.ledger.by_status), mnt = Object.entries(r.ledger.by_mount);
  $('#ndLedgerTable').innerHTML = '<thead><tr><th>口径</th><th>值</th></tr></thead><tbody>' +
    `<tr><td class="name">总条数</td><td>${num(r.ledger.total)} 条 · 记录体积 ${bytes(r.ledger.bytes)} · 最近一条 ${esc(r.ledger.last_at || '—')}</td></tr>` +
    `<tr><td class="name">按状态</td><td>${stat.map(([k, v]) => `${esc(k)} <b>${num(v)}</b>`).join(' · ') || '—'}</td></tr>` +
    `<tr><td class="name">按挂载点</td><td>${mnt.map(([k, v]) => `${esc(k)} <b>${num(v)}</b>`).join(' · ') || '—'}</td></tr>` +
    `<tr><td class="name">事实源</td><td class="mono">${esc(r.ledger.file)} ${r.ledger.exists ? '' : '<span class="tag bad">文件缺失</span>'}</td></tr>` +
    '</tbody>';

  $('#ndWarn').innerHTML = (r.warnings || []).length ?
    r.warnings.map((w) => `<li><span class="tag bad">注意</span> ${esc(w)}</li>`).join('')
    : '<li><span class="tag ok">全绿</span> OpenList 与账号台都在跑、账号库有号、档位都开了。</li>';
  $('#ndNotes').innerHTML = esc((r.notes || []).join(' ')) + ` <span class="muted">(探测时间 ${esc(r.checked_at)})</span>`;
}

/* ---------------------------------------------------------------- 路由与事件 */

const LOADERS = {
  overview: () => loadOverview(),
  news: () => loadNews(),
  games: () => loadTable('games'),
  repos: () => loadTable('repos'),
  factory: () => loadTable('factory'),
  reports: () => loadReports(),
  sources: () => loadSources(),
  netdisk: () => loadNetdisk(),
};

function show(view) {
  if (view !== 'netdisk') qrStopPoll();      // 离开这页就别在后台每 2 秒问一次了
  st.view = view;
  LS.set('view', view);
  $$('#nav button').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  $$('.view').forEach((v) => v.classList.toggle('active', v.id === 'view-' + view));
  location.hash = view;
  LOADERS[view]();
}

function debounce(fn, ms) { let t; return () => { clearTimeout(t); t = setTimeout(fn, ms); }; }

function wire() {
  $('#nav').onclick = (e) => { const b = e.target.closest('button'); if (b) show(b.dataset.view); };

  $('#reload').onclick = async () => {
    st.loaded = {}; st.news.facets = null; st.news.loadedFacets = false; st.games.facets = null; st.repos.facets = null; st.factory.facets = null; st.reports.list = null;
    await newsFacets(true);
    await loadReports(true);
    await LOADERS[st.view]();
  };

  // 资讯
  const rl = () => { st.news.offset = 0; loadNews(); };
  $('#nq').addEventListener('keydown', (e) => { if (e.key === 'Enter') rl(); });
  $('#nq').addEventListener('input', debounce(rl, 400));
  ['#nflag', '#nkind', '#nsource', '#nsince', '#nuntil', '#norder'].forEach((s) => $(s).addEventListener('change', rl));
  $('#nreset').onclick = () => { ['#nq', '#nsince', '#nuntil'].forEach((s) => ($(s).value = '')); $('#nflag').value = ''; $('#nkind').value = ''; $('#nsource').value = ''; $('#norder').value = 'date'; rl(); };
  $('#nprev').onclick = () => { st.news.offset = Math.max(0, st.news.offset - st.news.limit); loadNews(); };
  $('#nnext').onclick = () => { if (st.news.offset + st.news.limit < st.news.total) { st.news.offset += st.news.limit; loadNews(); } };

  // 游戏 / 库 / 工厂
  Object.keys(KIND).forEach((kind) => {
    const el = KIND[kind];
    const rl = () => { st[kind].offset = 0; loadTable(kind); };
    $(el.q).addEventListener('keydown', (e) => { if (e.key === 'Enter') rl(); });
    $(el.q).addEventListener('input', debounce(rl, 400));
    $(el.flag).addEventListener('change', rl);
    $(el.sort).addEventListener('change', rl);
    if (el.status) $(el.status).addEventListener('change', (e) => { st[kind].status = e.target.value; rl(); });
    $(el.reset).onclick = () => {
      $(el.q).value = ''; $(el.flag).value = ''; $(el.sort).value = 'name';
      if (el.status) { $(el.status).value = ''; st[kind].status = ''; }
      st[kind].ds = ''; rl();
    };
    $(el.prev).onclick = () => { st[kind].offset = Math.max(0, st[kind].offset - st[kind].limit); loadTable(kind); };
    $(el.next).onclick = () => { if (st[kind].offset + st[kind].limit < st[kind].total) { st[kind].offset += st[kind].limit; loadTable(kind); } };
    $(el.chips).onclick = (e) => {
      const c = e.target.closest('.chip');
      if (!c) return;
      if (c.dataset.jump) { $(el.flag).value = c.dataset.jump; }
      else { st[kind].ds = c.dataset.ds || ''; }
      st[kind].offset = 0;
      loadTable(kind);
    };
  });

  // 报告
  $('#dq').addEventListener('input', renderDocList);
  $('#dgroup').addEventListener('change', renderDocList);

  // 源
  $('#sq').addEventListener('input', debounce(loadSources, 400));
  $('#sonly').addEventListener('change', loadSources);

  window.addEventListener('hashchange', () => {
    const v = (location.hash || '').replace('#', '');
    if (LOADERS[v] && v !== st.view) show(v);
  });

  const initial = (location.hash || '').replace('#', '');
  show(['overview', 'news', 'games', 'repos', 'factory', 'reports', 'sources', 'netdisk'].includes(initial) ? initial : st.view);
}

wire();
