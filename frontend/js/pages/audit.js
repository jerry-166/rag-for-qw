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
      <div class="audit-layout audit-v2">
        <div class="audit-header row-between">
          <div>
            <h2 class="page-title">${isAdmin ? '审计中心' : '我的活动'}</h2>
            <p class="audit-desc">全透明审计日志：谁、何时、做了什么、改了什么、从哪来（request_id/IP）</p>
          </div>
          ${isAdmin ? '<button class="btn btn-sm" id="audit-export-btn">⬇ 导出 CSV</button>' : ''}
        </div>
        <div class="audit-stats" id="audit-stats"></div>
        <div class="audit-filters glass-card" id="audit-filters"></div>
        <div class="audit-list glass-card" id="audit-list">
          <div class="settings-loading"><div class="loading-spinner"></div><span>加载审计日志中...</span></div>
        </div>
        <div class="audit-pagination" id="audit-pagination"></div>
      </div>
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
    const f = this._filters;
    el.innerHTML = `
      <div class="audit-filter-field"><label>动作</label><input type="text" id="af-action" placeholder="如 kb.create" value="${f.action}"></div>
      <div class="audit-filter-field"><label>用户 ID</label><input type="text" id="af-user" placeholder="user_id" value="${f.user_id}"></div>
      <div class="audit-filter-field"><label>请求 ID</label><input type="text" id="af-rid" placeholder="request_id" value="${f.request_id}"></div>
      <div class="audit-filter-field"><label>资源类型</label>
        <select id="af-rtype">
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
        .map(a => `<span class="badge badge-gray num">${this._esc(a.action)} <b>${a.cnt}</b></span>`).join('');
      document.getElementById('audit-stats').innerHTML = `
        <div class="audit-stat-card glass-card"><div class="label-caps">24h 事件数</div><b class="num audit-stat-num">${s.today_events ?? 0}</b></div>
        <div class="audit-stat-card glass-card"><div class="label-caps">24h 活跃用户</div><b class="num audit-stat-num">${s.active_users_24h ?? 0}</b></div>
        <div class="audit-stat-card glass-card"><div class="label-caps">总事件数</div><b class="num audit-stat-num">${s.total_events ?? 0}</b></div>
        <div class="audit-stat-card glass-card audit-stat-wide"><div class="label-caps">Top 事件类型（7d）</div><div class="audit-top-list">${top || '近 7 天无事件'}</div></div>
      `;
    } catch (err) {
      document.getElementById('audit-stats').innerHTML =
        `<div class="audit-stat-card glass-card"><div>统计加载失败: ${this._esc(err.message)}</div></div>`;
    }
  },

  async load() {
    const list = document.getElementById('audit-list');
    list.innerHTML = '<div class="settings-loading"><div class="loading-spinner"></div><span>加载审计日志中...</span></div>';
    try {
      const params = { page: this._page, page_size: this._pageSize, ...this._filters };
      const resp = await window.AuditAPI.query(params);
      this._total = resp.total || 0;
      this.renderList(resp.items || []);
      this.renderPagination();
    } catch (err) {
      list.innerHTML = `<span class="text-red">加载审计日志失败: ${err.message}</span>`;
    }
  },

  renderList(items) {
    const list = document.getElementById('audit-list');
    if (!items.length) {
      list.innerHTML = '<div class="audit-empty">无匹配的审计记录</div>';
      return;
    }
    list.innerHTML = `
      <table class="audit-table">
        <thead><tr>
          <th>时间</th><th>用户</th><th>动作</th><th>资源</th><th>KB</th><th>request_id</th><th>IP</th><th></th>
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

  /** 动作 → 语义色徽章（圈 4：tokens 语义色对齐线框 08） */
  _actionBadge(action) {
    const a = String(action || '');
    let cls = 'badge-gray';
    if (/(login_failed|failed|error|delete|remove)/.test(a)) cls = 'badge-red';
    else if (/(share|pr|promote|demote)/.test(a)) cls = 'badge-yellow';
    else if (/^(kb\.|user\.)/.test(a)) cls = 'badge-accent';
    else if (/^faq/.test(a)) cls = 'badge-violet';
    else if (/^(document|import|upload|split|generate)/.test(a)) cls = 'badge-green';
    else if (/^search|^agent/.test(a)) cls = 'badge-info';
    return `<span class="badge ${cls} num">${this._esc(a)}</span>`;
  },

  renderRow(it) {
    const t = it.occurred_at ? String(it.occurred_at).replace('T', ' ').slice(0, 19) : '';
    const detail = it.detail ? JSON.stringify(it.detail, null, 2) : '';
    const expanded = this._expanded.has(it.id);
    return `
      <tr class="audit-row" data-id="${it.id}">
        <td class="num">${t}</td>
        <td>${this._esc(it.user_name || String(it.user_id ?? '-'))}</td>
        <td>${this._actionBadge(it.action)}</td>
        <td class="mono">${this._esc(it.resource_type || '—')}${it.resource_id ? ':' + String(it.resource_id).slice(0, 12) : ''}</td>
        <td class="num">${it.kb_id ?? '—'}</td>
        <td class="audit-rid" title="${this._esc(it.request_id || '')}">${it.request_id ? this._esc(String(it.request_id).slice(0, 8)) + '…' : '—'}</td>
        <td class="mono">${this._esc(it.client_ip || '—')}</td>
        <td><button class="btn btn-sm" id="audit-exp-${it.id}">${expanded ? '收起 ▴' : '详情 ▾'}</button></td>
      </tr>
      ${expanded ? `<tr class="audit-detail-row"><td colspan="8"><pre class="audit-detail">${this._esc(detail)}</pre></td></tr>` : ''}
    `;
  },

  renderPagination() {
    const el = document.getElementById('audit-pagination');
    const pages = Math.max(1, Math.ceil(this._total / this._pageSize));
    el.innerHTML = `
      <span class="t-dim">共 ${this._total} 条 · 每页 ${this._pageSize}</span>
      <span class="num t-dim">${this._page} / ${pages}</span>
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
      .catch(err => alert('导出失败: ' + err.message));
  },
};

window.AuditPage = AuditPage;
