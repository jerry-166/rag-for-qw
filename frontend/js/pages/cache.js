/**
 * 缓存中心页面（文档 08 §3.2，仅管理员）
 *
 * - 三总览卡片：L1(PG) / L2 内存 / L2 Redis（命中率、条目数、关键计数）
 * - 明细 tab：内存 / Redis / L1，行操作 [查看]（抽屉浮层展示 Top-K chunk + 命中时间线）
 * - 管理动作：按 KB 失效（bump version）、清空某层
 *
 * UI 铁律：浮层用 fixed 遮罩 + blur + Esc/点遮罩关闭；布局容器 inline style 显式声明；
 *         禁用原生 confirm/prompt/alert，统一 window.UI.*。
 */
const CachePage = {
  _pollTimer: null,
  _activeLayer: 'mem',

  async render() {
    const container = document.getElementById('page-container');
    container.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:var(--sp-3);margin-bottom:var(--sp-4)">
        <div>
          <h1 class="h-title">缓存中心</h1>
          <p class="t2 mt2" style="font-size:var(--fs-sm)">三层缓存状态：内存 LRU / Redis / PG（L1 向量缓存）。数据每 10s 自动刷新。</p>
        </div>
        <div style="display:flex;gap:var(--sp-2)">
          <button class="btn btn-sm" id="cache-invalidate-btn">按 KB 失效</button>
          <button class="btn btn-sm btn-ghost" id="cache-refresh-btn">↻ 刷新</button>
        </div>
      </div>
      <div id="cache-meta" style="display:flex;gap:var(--sp-2);flex-wrap:wrap;margin-bottom:var(--sp-4);font-size:var(--fs-xs)"></div>
      <div id="cache-cards" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:var(--sp-3);margin-bottom:var(--sp-4)">
        <div class="skeleton" style="height:120px"></div>
        <div class="skeleton" style="height:120px"></div>
        <div class="skeleton" style="height:120px"></div>
      </div>
      <div class="glass p4">
        <div style="display:flex;gap:var(--sp-2);margin-bottom:var(--sp-3);flex-wrap:wrap">
          <button class="btn btn-sm tab-btn ${this._activeLayer==='mem'?'btn-primary':'btn-ghost'}" data-layer="mem">内存 LRU</button>
          <button class="btn btn-sm tab-btn ${this._activeLayer==='redis'?'btn-primary':'btn-ghost'}" data-layer="redis">Redis</button>
          <button class="btn btn-sm tab-btn ${this._activeLayer==='l1'?'btn-primary':'btn-ghost'}" data-layer="l1">L1 向量(PG)</button>
          <span style="flex:1"></span>
          <button class="btn btn-sm btn-ghost" id="cache-clear-btn">清空当前层</button>
        </div>
        <div id="cache-entries"><div class="skeleton" style="height:80px"></div></div>
      </div>
    `;
    document.getElementById('cache-refresh-btn').addEventListener('click', () => this._refreshAll());
    document.getElementById('cache-invalidate-btn').addEventListener('click', () => this._invalidateKb());
    document.getElementById('cache-clear-btn').addEventListener('click', () => this._clearCurrent());
    document.querySelectorAll('.tab-btn').forEach(b =>
      b.addEventListener('click', () => { this._activeLayer = b.dataset.layer; this._rerenderTabs(); this._loadEntries(); }));
    await this._refreshAll();
    // 10s 轮询刷新 stats（不清空明细表，避免打断操作）
    this._pollTimer = setInterval(() => this._loadStats().catch(() => {}), 10000);
  },

  _cleanup() {
    if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = null; }
  },

  _rerenderTabs() {
    document.querySelectorAll('.tab-btn').forEach(b => {
      b.className = 'btn btn-sm tab-btn ' + (b.dataset.layer === this._activeLayer ? 'btn-primary' : 'btn-ghost');
    });
  },

  async _refreshAll() {
    await Promise.all([this._loadStats(), this._loadEntries()]);
  },

  async _loadStats() {
    try {
      const data = await window.CacheAPI.stats();
      const s = data.stats || {};
      const c = s.counters || {};
      const fmtRate = v => (v === null || v === undefined) ? '—' : (v * 100).toFixed(1) + '%';
      const fmtN = v => (v ?? 0).toLocaleString();
      const mb = (s.mem_bytes ? (s.mem_bytes / 1024 / 1024).toFixed(2) : '0') + ' MB';

      document.getElementById('cache-meta').innerHTML = `
        <span class="badge info num">backend: ${this._esc(s.backend || '—')}</span>
        <span class="badge ${s.redis_ok ? 'ok' : 'warn'} num">redis: ${s.redis_ok === null ? 'n/a' : (s.redis_ok ? 'OK' : '降级')}</span>
        ${s.redis_used_memory ? `<span class="badge num">redis内存: ${this._esc(s.redis_used_memory)}</span>` : ''}
        ${s.redis_keys !== undefined ? `<span class="badge num">redis keys: ${fmtN(s.redis_keys)}</span>` : ''}
      `;

      document.getElementById('cache-cards').innerHTML = `
        <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:6px;min-width:0">
          <div class="label-caps">L1 查询向量缓存 (PG)</div>
          <b class="num" style="font-size:var(--fs-xl)">${fmtRate(s.l1_hit_rate)}</b>
          <div class="t3" style="font-size:var(--fs-xs)">命中率</div>
          <div style="display:flex;gap:var(--sp-3);font-size:var(--fs-xs)" class="t3">
            <span>条目 <b class="num">${fmtN(s.l1_entries)}</b></span>
            <span>累计命中 <b class="num">${fmtN(s.l1_total_hits)}</b></span>
          </div>
        </div>
        <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:6px;min-width:0">
          <div class="label-caps">L2 检索结果 - 内存 LRU</div>
          <b class="num" style="font-size:var(--fs-xl)">${fmtRate(s.l2_hit_rate)}</b>
          <div class="t3" style="font-size:var(--fs-xs)">命中率（mem+redis 合计）</div>
          <div style="display:flex;gap:var(--sp-3);font-size:var(--fs-xs)" class="t3">
            <span>条目 <b class="num">${fmtN(s.mem_entries)}</b></span>
            <span>内存 <b class="num">${mb}</b></span>
            <span>逐出 <b class="num">${fmtN(c.evict)}</b></span>
          </div>
          <div style="display:flex;gap:var(--sp-3);font-size:var(--fs-xs)" class="t3">
            <span>mem命中 <b class="num">${fmtN(c.l2_mem_hit)}</b></span>
            <span>redis命中 <b class="num">${fmtN(c.l2_redis_hit)}</b></span>
            <span>miss <b class="num">${fmtN(c.l2_miss)}</b></span>
          </div>
        </div>
        <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:6px;min-width:0">
          <div class="label-caps">写路径失效统计</div>
          <b class="num" style="font-size:var(--fs-xl)">${fmtN(c.version_bump)}</b>
          <div class="t3" style="font-size:var(--fs-xs)">版本 bump 次数</div>
          <div style="display:flex;gap:var(--sp-3);font-size:var(--fs-xs)" class="t3">
            <span>set <b class="num">${fmtN(c.set)}</b></span>
            <span>L1命中 <b class="num">${fmtN(c.l1_hit)}</b></span>
            <span>L1miss <b class="num">${fmtN(c.l1_miss)}</b></span>
          </div>
        </div>
      `;
    } catch (err) {
      document.getElementById('cache-cards').innerHTML =
        `<div class="glass"><div class="state"><div class="glyph" style="color:var(--danger)">✕</div><div class="title">统计加载失败</div><p class="desc">${this._esc(err.message)}</p></div></div>`;
    }
  },

  async _loadEntries() {
    const el = document.getElementById('cache-entries');
    el.innerHTML = '<div class="skeleton" style="height:60px"></div>';
    try {
      const data = await window.CacheAPI.entries(this._activeLayer, 50);
      const items = data.items || [];
      if (!items.length) {
        el.innerHTML = '<div class="state"><div class="glyph">≣</div><div class="title">无缓存条目</div><p class="desc">该层当前为空（或 Redis 未运行）</p></div>';
        return;
      }
      if (this._activeLayer === 'l1') {
        el.innerHTML = `
          <table class="table dense">
            <thead><tr><th>查询文本</th><th>模型</th><th style="text-align:right">命中</th><th>最近命中</th></tr></thead>
            <tbody>${items.map(it => this._renderL1Row(it)).join('')}</tbody>
          </table>`;
      } else {
        el.innerHTML = `
          <table class="table dense">
            <thead><tr><th>缓存 key</th><th>KB/模式</th><th style="text-align:right">命中</th><th>大小</th><th>TTL</th><th style="text-align:right">操作</th></tr></thead>
            <tbody>${items.map(it => this._renderL2Row(it)).join('')}</tbody>
          </table>`;
        items.forEach(it => {
          const btn = document.getElementById(`cache-view-${this._keyId(it.key)}`);
          if (btn) btn.addEventListener('click', () => this._showDetail(it.key));
        });
      }
    } catch (err) {
      el.innerHTML = `<div class="state"><div class="glyph" style="color:var(--danger)">✕</div><div class="title">加载失败</div><p class="desc">${this._esc(err.message)}</p></div>`;
    }
  },

  _keyId(key) { return String(key).slice(-12).replace(/[^a-z0-9]/gi, ''); },

  _renderL2Row(it) {
    const meta = it.meta || {};
    const kb = meta.kb_id ?? '—';
    const mode = meta.mode || '';
    return `
      <tr>
        <td class="mono t3" title="${this._esc(it.key)}">${this._esc(String(it.key).slice(0, 24))}…</td>
        <td class="num">${kb} <span class="t3">${this._esc(mode)}</span></td>
        <td class="num" style="text-align:right">${it.hits ?? 0}</td>
        <td class="num">${it.bytes ? (it.bytes/1024).toFixed(1)+'KB' : (it.bytes === 0 ? '0' : '—')}</td>
        <td class="num">${it.ttl_left != null ? it.ttl_left+'s' : '—'}</td>
        <td style="text-align:right"><button class="btn btn-sm" id="cache-view-${this._keyId(it.key)}">查看</button></td>
      </tr>`;
  },

  _renderL1Row(it) {
    const t = it.last_hit_at ? String(it.last_hit_at).replace('T',' ').slice(0,19) : '—';
    return `
      <tr>
        <td title="${this._esc(it.query)}">${this._esc(it.query || '')}${(it.query||'').length >= 60 ? '…' : ''}</td>
        <td class="mono t3">${this._esc(it.model || '—')}</td>
        <td class="num" style="text-align:right">${it.hits ?? 0}</td>
        <td class="num">${t}</td>
      </tr>`;
  },

  /** 详情抽屉（浮层铁律：fixed 全屏遮罩 + blur + Esc/点遮罩关闭） */
  async _showDetail(keyHash) {
    let overlay = document.getElementById('cache-detail-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'cache-detail-overlay';
      overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.45);backdrop-filter:blur(6px);z-index:70;display:flex;align-items:center;justify-content:center;padding:var(--sp-4)';
      document.body.appendChild(overlay);
      overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
      document.addEventListener('keydown', e => { if (e.key === 'Escape') { const o = document.getElementById('cache-detail-overlay'); if (o) o.remove(); } });
    }
    overlay.innerHTML = `<div class="glass" style="width:min(720px,92vw);max-height:80vh;overflow:auto;padding:var(--sp-5)"><div class="skeleton" style="height:120px"></div></div>`;
    try {
      const d = await window.CacheAPI.entryDetail(keyHash);
      const val = Array.isArray(d.value) ? d.value : [];
      const meta = d.meta || {};
      const timeline = (d.hit_timeline || []).map(ts => {
        const t = new Date(ts * 1000);
        return t.toLocaleTimeString();
      });
      const chunks = val.map((r, i) => {
        const content = (r.content || r.chunk_text || '').slice(0, 300);
        const score = r.rerank_score ?? r.score ?? r._similarity;
        return `
          <div class="glass" style="padding:10px 12px;margin-bottom:var(--sp-2)">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
              <span class="num t3">#${i+1}</span>
              ${score != null ? `<span class="badge info num">score ${typeof score === 'number' ? score.toFixed(4) : this._esc(score)}</span>` : ''}
            </div>
            <div class="t3" style="font-size:var(--fs-xs);line-height:1.5">${this._esc(content)}${(r.content||'').length > 300 ? '…' : ''}</div>
          </div>`;
      }).join('');
      overlay.innerHTML = `
        <div class="glass" style="width:min(720px,92vw);max-height:80vh;overflow:auto;padding:var(--sp-5)">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--sp-3)">
            <h2 class="h-title" style="font-size:var(--fs-lg)">缓存条目详情</h2>
            <button class="btn btn-sm btn-ghost" id="cache-detail-close">✕ 关闭</button>
          </div>
          <div class="mono t3" style="word-break:break-all;margin-bottom:var(--sp-3);font-size:var(--fs-xs);padding:8px;background:var(--surface-2);border-radius:6px">${this._esc(d.key)}</div>
          <div style="display:flex;gap:var(--sp-3);flex-wrap:wrap;margin-bottom:var(--sp-4);font-size:var(--fs-xs)" class="t3">
            <span>KB <b class="num">${meta.kb_id ?? '—'}</b></span>
            <span>模式 <b class="num">${this._esc(meta.mode || '—')}</b></span>
            <span>limit <b class="num">${meta.limit ?? '—'}</b></span>
            <span>rerank <b class="num">${meta.rerank ?? '—'}</b></span>
            <span>大小 <b class="num">${d.bytes ? (d.bytes/1024).toFixed(1)+'KB' : '—'}</b></span>
            <span>命中 <b class="num">${(d.hit_timeline||[]).length}</b></span>
          </div>
          <div class="label-caps" style="margin-bottom:var(--sp-2)">缓存内容（Top-${val.length}）</div>
          ${chunks || '<div class="state"><div class="title">空结果缓存</div></div>'}
          ${timeline.length ? `<div class="label-caps" style="margin-top:var(--sp-4);margin-bottom:var(--sp-2)">命中时间线（最近 ${timeline.length}）</div><div class="t3" style="font-size:var(--fs-xs)">${timeline.map(t => `<span class="badge num">${this._esc(t)}</span>`).join(' ')}</div>` : ''}
        </div>`;
      document.getElementById('cache-detail-close').addEventListener('click', () => overlay.remove());
    } catch (err) {
      overlay.innerHTML = `<div class="glass" style="width:min(480px,92vw);padding:var(--sp-5)"><div class="state"><div class="glyph" style="color:var(--danger)">✕</div><div class="title">加载失败</div><p class="desc">${this._esc(err.message)}</p></div></div>`;
    }
  },

  async _invalidateKb() {
    let kbId;
    try {
      kbId = await window.UI.prompt({ title: '按知识库失效缓存', message: '输入要失效的知识库 ID（bump cache_version，等于内容变更的手动版）：' });
    } catch (e) { return; } // 用户取消
    if (!kbId || isNaN(kbId)) { window.App.showToast('请输入有效的数字 KB ID', 'error'); return; }
    try {
      const r = await window.CacheAPI.invalidate(kbId);
      window.App.showToast(`已失效 KB ${kbId}（新版本 ${r.new_version}）`, 'success');
      await this._loadStats();
    } catch (err) {
      window.UI.alert({ title: '失效失败', message: err.message });
    }
  },

  async _clearCurrent() {
    const layerNames = { mem: '内存 LRU', redis: 'Redis', l1: 'L1 向量缓存 (PG)' };
    const name = layerNames[this._activeLayer] || this._activeLayer;
    try {
      await window.UI.confirm({ title: `清空 ${name}`, message: `确认清空 ${name} 的全部缓存条目？此操作不可撤销。` });
    } catch (e) { return; }
    try {
      await window.CacheAPI.clear(this._activeLayer);
      window.App.showToast(`${name} 已清空`, 'success');
      await this._refreshAll();
    } catch (err) {
      window.UI.alert({ title: '清空失败', message: err.message });
    }
  },

  _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  },
};

window.CachePage = CachePage;
