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
      <div class="audit-layout">
        <div class="audit-header">
          <h2>${isAdmin ? '审计中心' : '我的活动'}</h2>
          <p class="audit-desc">全透明审计日志：谁、何时、做了什么、改了什么（before→after）、从哪来（request_id/IP）</p>
          ${isAdmin ? '<button class="btn btn-secondary" id="audit-export-btn">导出 (CSV)</button>' : ''}
        </div>
        <div class="audit-stats" id="audit-stats"></div>
        <div class="audit-filters" id="audit-filters"></div>
        <div class="audit-list" id="audit-list">
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
      <input type="text" id="af-action" placeholder="动作 (如 kb.create)" value="${f.action}">
      <input type="text" id="af-user" placeholder="用户ID" value="${f.user_id}" style="max-width:100px">
      <input type="text" id="af-rid" placeholder="request_id" value="${f.request_id}">
      <input type="text" id="af-rtype" placeholder="资源类型 (kb/document/...)" value="${f.resource_type}">
      <button class="btn btn-primary" id="af-apply">查询</button>
      <button class="btn btn-secondary" id="af-reset">重置</button>
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
        .map(a => `<span class="audit-top-action">${a.action} <b>${a.cnt}</b></span>`).join('');
      document.getElementById('audit-stats').innerHTML = `
        <div class="audit-stat-card"><div class="audit-stat-num">${s.today_events ?? 0}</div><div>24h 事件数</div></div>
        <div class="audit-stat-card"><div class="audit-stat-num">${s.active_users_24h ?? 0}</div><div>24h 活跃用户</div></div>
        <div class="audit-stat-card"><div class="audit-stat-num">${s.total_events ?? 0}</div><div>总事件数</div></div>
        <div class="audit-stat-card audit-stat-wide"><div class="audit-top-list">${top || '近 7 天无事件'}</div><div>Top 事件类型（7d）</div></div>
      `;
    } catch (err) {
      document.getElementById('audit-stats').innerHTML =
        `<div class="audit-stat-card"><div>统计加载失败: ${err.message}</div></div>`;
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

  renderRow(it) {
    const t = it.occurred_at ? String(it.occurred_at).replace('T', ' ').slice(0, 19) : '';
    const detail = it.detail ? JSON.stringify(it.detail, null, 2) : '';
    const expanded = this._expanded.has(it.id);
    return `
      <tr class="audit-row" data-id="${it.id}">
        <td>${t}</td>
        <td>${it.user_id ?? '-'}</td>
        <td><span class="audit-action">${it.action || ''}</span></td>
        <td>${it.resource_type || ''}${it.resource_id ? ':' + String(it.resource_id).slice(0, 12) : ''}</td>
        <td>${it.kb_id ?? '-'}</td>
        <td class="audit-rid" title="${it.request_id || ''}">${it.request_id ? String(it.request_id).slice(0, 8) : '-'}</td>
        <td>${it.client_ip || '-'}</td>
        <td><button class="btn btn-sm" id="audit-exp-${it.id}">${expanded ? '收起' : '详情'}</button></td>
      </tr>
      ${expanded ? `<tr class="audit-detail-row"><td colspan="8"><pre class="audit-detail">${detail}</pre></td></tr>` : ''}
    `;
  },

  renderPagination() {
    const el = document.getElementById('audit-pagination');
    const pages = Math.max(1, Math.ceil(this._total / this._pageSize));
    el.innerHTML = `
      <span>共 ${this._total} 条 / ${pages} 页</span>
      <button class="btn btn-sm" id="pg-prev" ${this._page <= 1 ? 'disabled' : ''}>上一页</button>
      <span>第 ${this._page} 页</span>
      <button class="btn btn-sm" id="pg-next" ${this._page >= pages ? 'disabled' : ''}>下一页</button>
    `;
    const prev = document.getElementById('pg-prev');
    const next = document.getElementById('pg-next');
    if (prev && !prev.disabled) prev.addEventListener('click', async () => { this._page--; await this.load(); });
    if (next && !next.disabled) next.addEventListener('click', async () => { this._page++; await this.load(); });
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
