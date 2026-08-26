/**
 * 审计中心页面（文档 07 §5 功能版）
 *
 * - 概览卡：24h 事件数 / 活跃用户 / 总事件数 / Top 事件类型（管理员）
 * - 事件时间线：过滤（动作 / 用户 / request_id / 资源类型）+ 分页 + 详情展开（detail JSONB 渲染）
 * - 导出按钮（管理员；CSV / JSON）
 * - 普通用户：后端自动过滤为「我的活动」（同一页面，权限内自动收敛）
 *
 * 注：功能版，完整美化归入 05b 最后整合阶段。
 */
const AuditPage = {
  _filters: { action: '', user_id: '', request_id: '', resource_type: '' },
  _page: 1,
  _pageSize: 50,
  _total: 0,
  _stats: null,
  _expanded: new Set(),

  async render() {
    const container = document.getElementById('page-container');
    const isAdmin = (window.UserManager && UserManager.get() && UserManager.get().role === 'admin');
    container.innerHTML = `
      <div class="row between mb4">
        <div>
          <h1 class="h-title">${isAdmin ? '审计中心' : '我的活动'}</h1>
          <p class="t2 mt2" style="font-size:var(--fs-sm)">全透明审计日志：谁、何时、做了什么、改了什么、从哪来（request_id/IP）</p>
        </div>
        ${isAdmin ? '<button class="btn btn-sm" id="audit-export-btn">⬇ 导出 CSV</button>' : ''}
      </div>
      <div class="grid stats mb4" id="audit-stats"></div>
      <div class="glass p5 mb4" id="audit-filters"></div>
      <div class="glass" id="audit-list">
        <div class="skeleton" style="height:80px"></div>
      </div>
      <div class="row between p4" id="audit-pagination"></div>
    `;
    if (isAdmin) {
      const btn = document.getElementById('audit-export-btn');
      if (btn) btn.addEventListener('click', () => this.exportCsv());
    }
    this.renderFilters();
    if (isAdmin) await this.loadStats();
    await this.load();
  },

  renderFilters() {
    const el = document.getElementById('audit-filters');
    el.classList.add('row');
    el.style.flexWrap = 'wrap';
    el.style.alignItems = 'flex-end';
    el.style.gap = 'var(--sp-3)';
    const f = this._filters;
    el.innerHTML = `
      <div class="field" style="flex:1 1 160px;min-width:160px"><label>动作</label><input class="input" type="text" id="af-action" placeholder="如 kb.create" value="${f.action}"></div>
      <div class="field" style="flex:1 1 140px;min-width:140px"><label>用户</label><input class="input" type="text" id="af-user" placeholder="用户名/ID" value="${f.user_id}"></div>
      <div class="field" style="flex:1 1 180px;min-width:180px"><label>请求 ID</label><input class="input" type="text" id="af-rid" placeholder="request_id" value="${f.request_id}"></div>
      <div class="field" style="flex:1 1 140px;min-width:140px"><label>资源类型</label>
        <select class="select" id="af-rtype">
          <option value="">全部</option>
          ${['kb', 'document', 'faq', 'user', 'search', 'agent', 'settings'].map(t =>
            `<option value="${t}" ${f.resource_type === t ? 'selected' : ''}>${t}</option>`).join('')}
        </select>
      </div>
      <button class="btn btn-primary" id="af-apply">查询</button>
      <button class="btn btn-ghost" id="af-reset">重置</button>
    `;
    document.getElementById('af-apply').addEventListener('click', async () => {
      this._filters = {
        action: document.getElementById('af-action').value.trim(),
        user_id: document.getElementById('af-user').value.trim(),
        request_id: document.getElementById('af-rid').value.trim(),
        resource_type: document.getElementById('af-rtype').value.trim(),
      };
      this._page = 1;
      await this.load();
    });
    document.getElementById('af-reset').addEventListener('click', async () => {
      this._filters = { action: '', user_id: '', request_id: '', resource_type: '' };
      this._page = 1;
      this.renderFilters();
      await this.load();
    });
  },

  async loadStats() {
    try {
      this._stats = await window.AuditAPI.stats();
      const s = this._stats;
      const top = (s.top_actions_7d || []).slice(0, 5)
        .map(a => `<span class="badge ${this._actionBadgeColor(a.action)}">${this._esc(a.action)} <span class="num">${a.cnt}</span></span>`).join('');
      const topAction = (s.top_actions_7d || [])[0];
      const failActions = (s.top_actions_7d || []).filter(a => a.action.includes('failed'));
      const failTotal = failActions.reduce((sum, a) => sum + a.cnt, 0);
      const failRate = s.total_events > 0 ? (failTotal / s.total_events * 100).toFixed(1) + '%' : '0%';
      document.getElementById('audit-stats').innerHTML = `
        <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:4px;min-width:0"><div class="label-caps">今日事件</div><b class="num" style="font-size:var(--fs-xl)">${s.today_events ?? 0}</b></div>
        <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:4px;min-width:0"><div class="label-caps">活跃用户</div><b class="num" style="font-size:var(--fs-xl)">${s.active_users_24h ?? 0}</b></div>
        <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:4px;min-width:0"><div class="label-caps">最高频动作</div><b class="num" style="font-size:var(--fs-xl)">${topAction ? topAction.cnt : 0}</b><div class="t3" style="font-size:var(--fs-xs)">${topAction ? this._esc(topAction.action) : '—'}</div></div>
        <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:4px;min-width:0"><div class="label-caps">失败率</div><b class="num" style="font-size:var(--fs-xl);color:${parseFloat(failRate) > 5 ? 'var(--danger)' : 'var(--ok)'}">${failRate}</b></div>
      `;
    } catch (err) {
      document.getElementById('audit-stats').innerHTML =
        `<div class="glass p4"><div class="label-caps">统计加载失败</div><p class="t2" style="font-size:var(--fs-sm)">${this._esc(err.message)}</p></div>`;
    }
  },

  async load() {
    const list = document.getElementById('audit-list');
    list.innerHTML = '<div class="skeleton" style="height:120px"></div>';
    try {
      const params = { page: this._page, page_size: this._pageSize, ...this._filters };
      const resp = await window.AuditAPI.query(params);
      this._total = resp.total || 0;
      this.renderList(resp.items || []);
      this.renderPagination();
    } catch (err) {
      list.innerHTML = `<div class="glass"><div class="state"><div class="glyph" style="color:var(--danger)">✕</div><div class="title">加载失败</div><p class="desc">${this._esc(err.message)}</p></div></div>`;
      document.getElementById('audit-pagination').innerHTML = '';
    }
  },

  renderList(items) {
    const list = document.getElementById('audit-list');
    if (!items.length) {
      list.innerHTML = '<div class="glass"><div class="state"><div class="glyph">≣</div><div class="title">无匹配的审计记录</div><p class="desc">调整筛选条件后重新查询</p></div></div>';
      return;
    }
    list.innerHTML = `
      <table class="table dense">
        <thead><tr>
          <th>时间</th><th>动作</th><th>用户</th><th>资源</th><th>KB</th><th>request_id</th><th>IP</th><th style="text-align:right">操作</th>
        </tr></thead>
        <tbody>
          ${items.map(it => this.renderRow(it)).join('')}
        </tbody>
      </table>
    `;
    items.forEach(it => {
      const btn = document.getElementById(`audit-exp-${it.id}`);
      if (btn) btn.addEventListener('click', () => {
        if (this._expanded.has(it.id)) this._expanded.delete(it.id);
        else this._expanded.add(it.id);
        this.renderList(items);
      });
    });
  },

  /** 动作 → 语义色徽章 class（wireframe.css 体系：.badge.danger/.warn/.accent/.violet/.ok/.info） */
  _actionBadgeColor(action) {
    const a = String(action || '');
    if (/(login_failed|failed|error|delete|remove)/.test(a)) return 'badge danger';
    if (/(share|pr|promote|demote)/.test(a)) return 'badge warn';
    if (/^(kb\.|user\.)/.test(a)) return 'badge accent';
    if (/^faq/.test(a)) return 'badge violet';
    if (/^(document|import|upload|split|generate)/.test(a)) return 'badge ok';
    if (/^search|^agent/.test(a)) return 'badge info';
    return 'badge';
  },

  /** 动作 → 徽章 HTML（线框 08：语义色 + num 等宽） */
  _actionBadge(action) {
    return `<span class="${this._actionBadgeColor(action)} num">${this._esc(String(action || ''))}</span>`;
  },

  renderRow(it) {
    const t = it.occurred_at ? String(it.occurred_at).replace('T', ' ').slice(0, 19) : '';
    const detail = it.detail ? JSON.stringify(it.detail, null, 2) : '';
    const expanded = this._expanded.has(it.id);
    return `
      <tr data-id="${it.id}">
        <td class="num">${t}</td>
        <td>${this._actionBadge(it.action)}</td>
        <td>${this._esc(it.user_name || String(it.user_id ?? '-'))}</td>
        <td class="mono">${this._esc(it.resource_type || '—')}${it.resource_id ? ':' + String(it.resource_id).slice(0, 12) : ''}</td>
        <td class="num">${it.kb_id ?? '—'}</td>
        <td class="mono t3" title="${this._esc(it.request_id || '')}">${it.request_id ? this._esc(String(it.request_id).slice(0, 8)) + '…' : '—'}</td>
        <td class="mono">${this._esc(it.client_ip || '—')}</td>
        <td style="text-align:right"><button class="btn btn-sm" id="audit-exp-${it.id}">${expanded ? '收起 ▴' : '详情 ▾'}</button></td>
      </tr>
      ${expanded ? `<tr><td colspan="8"><pre class="mono t3" style="padding:var(--sp-3);overflow:auto;max-height:240px">${this._esc(detail)}</pre></td></tr>` : ''}
    `;
  },

  renderPagination() {
    const el = document.getElementById('audit-pagination');
    const pages = Math.max(1, Math.ceil(this._total / this._pageSize));
    el.innerHTML = `
      <span class="t3">共 ${this._total} 条 · 每页 ${this._pageSize}</span>
      <span class="num t3">${this._page} / ${pages}</span>
      <button class="btn btn-sm" id="pg-prev" ${this._page <= 1 ? 'disabled' : ''}>← 上一页</button>
      <button class="btn btn-sm" id="pg-next" ${this._page >= pages ? 'disabled' : ''}>下一页 →</button>
    `;
    const prev = document.getElementById('pg-prev');
    const next = document.getElementById('pg-next');
    if (prev && !prev.disabled) prev.addEventListener('click', async () => { this._page--; await this.load(); });
    if (next && !next.disabled) next.addEventListener('click', async () => { this._page++; await this.load(); });
  },

  _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  },

  exportCsv() {
    const url = window.AuditAPI.exportUrl({ format: 'csv', ...this._filters });
    const token = window.TokenManager.get();
    // 导出接口需要鉴权头，用 fetch 下载
    fetch(url, { headers: { Authorization: 'Bearer ' + token } })
      .then(r => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.blob();
      })
      .then(blob => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'audit_export.csv';
        a.click();
        URL.revokeObjectURL(a.href);
      })
      .catch(err => window.UI.alert({
        title: '导出失败',
        message: err.message
      }));
  },
};

window.AuditPage = AuditPage;
