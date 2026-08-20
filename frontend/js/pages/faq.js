/**
 * 知识记忆管理页（Stage 3 自进化 RAG，文档 06）
 *
 * 三个 Tab：
 * - 正式知识（active）：可降级/删除
 * - 候选记忆（candidate）：显示命中进度（hit_count/distill_threshold），可升格/删除
 * - PR 审核：我名下 KB 收到的协作 PR（合并/拒绝）
 *
 * 挂载 window.FAQPage；同时暴露 window.FaqAPI 薄封装供其他页面复用。
 */

/* global request, KnowledgeBaseAPI */

const FaqAPI = {
  listFaqs({ status, kbId = null, page = 1, pageSize = 20 }) {
    const q = new URLSearchParams({ page, page_size: pageSize });
    if (status) q.set('status', status);
    if (kbId) q.set('kb_id', kbId);
    return request(`/api/faq?${q.toString()}`);
  },
  promote(faqId) { return request(`/api/faq/${faqId}/promote`, { method: 'POST' }); },
  demote(faqId) { return request(`/api/faq/${faqId}/demote`, { method: 'POST' }); },
  remove(faqId) { return request(`/api/faq/${faqId}`, { method: 'DELETE' }); },
  supplement({ question, answer, kb_id = null }) {
    return request('/api/faq/supplement', {
      method: 'POST',
      body: JSON.stringify({ question, answer, kb_id }),
    });
  },
  listPrs({ kbId = null, page = 1, pageSize = 20 } = {}) {
    const q = new URLSearchParams({ page, page_size: pageSize });
    if (kbId) q.set('target_kb_id', kbId);
    return request(`/api/faq-pr?${q.toString()}`);
  },
  mergePr(prId, note = null) {
    return request(`/api/faq-pr/${prId}/merge`, { method: 'POST', body: JSON.stringify({ note }) });
  },
  rejectPr(prId, note = null) {
    return request(`/api/faq-pr/${prId}/reject`, { method: 'POST', body: JSON.stringify({ note }) });
  },
  shareKb({ kb_id, username, can_write_directly }) {
    return request('/api/kb/share', {
      method: 'POST',
      body: JSON.stringify({ kb_id, username, can_write_directly }),
    });
  },
  unshareKb({ kb_id, username }) {
    return request('/api/kb/unshare', {
      method: 'POST',
      body: JSON.stringify({ kb_id, username }),
    });
  },
  listShares(kbId) { return request(`/api/kb/${kbId}/shares`); },
  cloneKb(kbId, newName = null) {
    return request(`/api/kb/${kbId}/clone`, {
      method: 'POST',
      body: JSON.stringify(newName ? { new_name: newName } : {}),
    });
  },
};
window.FaqAPI = FaqAPI;

const FAQPage = {
  currentTab: 'active',
  currentKbId: null,
  page: 1,
  pageSize: 20,
  total: 0,
  knowledgeBases: [],

  async render() {
    this.currentTab = 'active';
    this.currentKbId = null;
    this.page = 1;

    const container = document.getElementById('page-container');
    container.innerHTML = `
      <div class="page-header">
        <div>
          <h1 class="page-title">知识记忆</h1>
          <p class="page-desc">自进化知识闭环：候选记忆随命中自动成长为正式知识，协作知识经审核后生效</p>
        </div>
        <button class="btn btn-primary" id="faq-refresh-btn"><span>🔄 刷新</span></button>
      </div>

      <div class="doc-toolbar" style="margin-bottom: 12px;">
        <div class="faq-tabs" id="faq-tabs">
          <button class="btn btn-sm btn-primary" data-tab="active">正式知识</button>
          <button class="btn btn-sm btn-secondary" data-tab="candidate">候选记忆</button>
          <button class="btn btn-sm btn-secondary" data-tab="pr">PR 审核</button>
        </div>
        <select id="faq-kb-filter">
          <option value="">全部知识库</option>
        </select>
      </div>

      <div class="doc-table-wrap">
        <table id="faq-table">
          <thead id="faq-table-head"></thead>
          <tbody id="faq-table-body">
            <tr><td colspan="6" style="text-align:center; padding: 40px;">
              <div class="loading-spinner"></div>
              <p style="margin-top: 12px; color: var(--text3);">加载中...</p>
            </td></tr>
          </tbody>
        </table>
      </div>
      <div class="faq-pager" id="faq-pager" style="margin-top: 12px; display: flex; gap: 8px; align-items: center; justify-content: flex-end;"></div>
    `;

    this.initEvents();
    await this.loadKnowledgeBases();
    await this.loadList();
  },

  initEvents() {
    document.getElementById('faq-refresh-btn').addEventListener('click', () => this.loadList());
    document.getElementById('faq-tabs').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-tab]');
      if (!btn) return;
      this.currentTab = btn.dataset.tab;
      this.page = 1;
      document.querySelectorAll('#faq-tabs button').forEach(b => {
        b.className = `btn btn-sm ${b.dataset.tab === this.currentTab ? 'btn-primary' : 'btn-secondary'}`;
      });
      this.loadList();
    });
    document.getElementById('faq-kb-filter').addEventListener('change', (e) => {
      this.currentKbId = e.target.value ? parseInt(e.target.value, 10) : null;
      this.page = 1;
      this.loadList();
    });
  },

  async loadKnowledgeBases() {
    try {
      const resp = await KnowledgeBaseAPI.list();
      this.knowledgeBases = resp.knowledge_bases || [];
      const sel = document.getElementById('faq-kb-filter');
      sel.innerHTML = '<option value="">全部知识库</option>' +
        this.knowledgeBases.map(kb =>
          `<option value="${kb.id}">${this._esc(kb.kb_name)}</option>`).join('');
    } catch (e) {
      console.error('加载知识库列表失败', e);
    }
  },

  async loadList() {
    const tbody = document.getElementById('faq-table-body');
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 40px;">
      <div class="loading-spinner"></div></td></tr>`;
    try {
      if (this.currentTab === 'pr') {
        await this.loadPrs();
      } else {
        const resp = await FaqAPI.listFaqs({
          status: this.currentTab,
          kbId: this.currentKbId,
          page: this.page,
          pageSize: this.pageSize,
        });
        this.total = resp.total || 0;
        this.renderFaqRows(resp.items || []);
      }
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="6">
        <div class="empty-state"><div class="empty-icon">❌</div>
        <p>加载失败: ${this._esc(e.message)}</p></div></td></tr>`;
    }
    this.renderPager();
  },

  async loadPrs() {
    const resp = await FaqAPI.listPrs({ kbId: this.currentKbId, page: this.page, pageSize: this.pageSize });
    this.total = resp.total || 0;
    this.renderPrRows(resp.items || []);
  },

  _kbName(kbId) {
    const kb = this.knowledgeBases.find(k => k.id === kbId);
    return kb ? kb.kb_name : `KB#${kbId}`;
  },

  renderFaqRows(items) {
    const isActive = this.currentTab === 'active';
    document.getElementById('faq-table-head').innerHTML = `
      <tr>
        <th>问题</th><th>答案</th><th>知识库</th><th>命中/热度</th><th>来源</th><th>操作</th>
      </tr>`;
    const tbody = document.getElementById('faq-table-body');
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="6">
        <div class="empty-state"><div class="empty-icon">🧠</div>
        <p>${isActive ? '暂无正式知识' : '暂无候选记忆'}</p></div></td></tr>`;
      return;
    }
    tbody.innerHTML = items.map(f => `
      <tr>
        <td title="${this._esc(f.question)}">${this._esc(this._cut(f.question, 40))}</td>
        <td title="${this._esc(f.answer)}">${this._esc(this._cut(f.answer, 60))}</td>
        <td>${this._esc(this._kbName(f.kb_id))}</td>
        <td>${f.hit_count}${isActive ? '' : ` / ${f.distill_threshold}`} 次<br>
            <span style="color: var(--text3); font-size: .75rem;">热度 ${(f.heat_score || 0).toFixed(2)}</span></td>
        <td>${this._esc(f.source || '-')}</td>
        <td>
          ${isActive
            ? `<button class="btn btn-sm btn-secondary" onclick="FAQPage.demote(${f.id})">降级</button>`
            : `<button class="btn btn-sm btn-primary" onclick="FAQPage.promote(${f.id})">升格</button>`}
          <button class="btn btn-sm btn-danger" onclick="FAQPage.removeFaq(${f.id})">删除</button>
        </td>
      </tr>`).join('');
  },

  renderPrRows(items) {
    document.getElementById('faq-table-head').innerHTML = `
      <tr><th>提交人</th><th>目标知识库</th><th>问题</th><th>答案</th><th>提交时间</th><th>操作</th></tr>`;
    const tbody = document.getElementById('faq-table-body');
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="6">
        <div class="empty-state"><div class="empty-icon">📬</div>
        <p>暂无待审核的协作提交</p></div></td></tr>`;
      return;
    }
    tbody.innerHTML = items.map(pr => `
      <tr>
        <td>${this._esc(pr.submitter_name || `用户#${pr.submitted_by}`)}</td>
        <td>${this._esc(pr.target_kb_name || `KB#${pr.target_kb_id}`)}</td>
        <td title="${this._esc(pr.question)}">${this._esc(this._cut(pr.question, 30))}</td>
        <td title="${this._esc(pr.answer)}">${this._esc(this._cut(pr.answer, 40))}</td>
        <td style="white-space: nowrap;">${this._fmtTime(pr.created_at)}</td>
        <td style="white-space: nowrap;">
          <button class="btn btn-sm btn-primary" onclick="FAQPage.reviewPr(${pr.id}, true)">合并</button>
          <button class="btn btn-sm btn-danger" onclick="FAQPage.reviewPr(${pr.id}, false)">拒绝</button>
        </td>
      </tr>`).join('');
  },

  renderPager() {
    const pager = document.getElementById('faq-pager');
    if (!pager) return;
    const pages = Math.max(1, Math.ceil(this.total / this.pageSize));
    if (this.total <= this.pageSize) { pager.innerHTML = ''; return; }
    pager.innerHTML = `
      <button class="btn btn-sm btn-secondary" ${this.page <= 1 ? 'disabled' : ''}
        onclick="FAQPage.goPage(${this.page - 1})">上一页</button>
      <span style="color: var(--text3); font-size: .8rem;">${this.page} / ${pages}</span>
      <button class="btn btn-sm btn-secondary" ${this.page >= pages ? 'disabled' : ''}
        onclick="FAQPage.goPage(${this.page + 1})">下一页</button>`;
  },

  goPage(p) {
    this.page = p;
    this.loadList();
  },

  async promote(id) {
    try {
      await FaqAPI.promote(id);
      window.App.showToast('已升格为正式知识', 'success');
      this.loadList();
    } catch (e) { window.App.showToast('升格失败: ' + e.message, 'error'); }
  },

  async demote(id) {
    try {
      await FaqAPI.demote(id);
      window.App.showToast('已降级为候选记忆', 'success');
      this.loadList();
    } catch (e) { window.App.showToast('降级失败: ' + e.message, 'error'); }
  },

  async removeFaq(id) {
    if (!confirm('确定删除这条知识记忆？删除后不可恢复。')) return;
    try {
      await FaqAPI.remove(id);
      window.App.showToast('已删除', 'success');
      this.loadList();
    } catch (e) { window.App.showToast('删除失败: ' + e.message, 'error'); }
  },

  async reviewPr(id, approve) {
    const note = approve ? null : prompt('拒绝原因（可选）：');
    if (!approve && note === null) return; // 用户点了取消
    try {
      if (approve) {
        await FaqAPI.mergePr(id, note);
        window.App.showToast('已合并，知识已生效', 'success');
      } else {
        await FaqAPI.rejectPr(id, note);
        window.App.showToast('已拒绝', 'success');
      }
      this.loadList();
    } catch (e) { window.App.showToast('操作失败: ' + e.message, 'error'); }
  },

  _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  },
  _cut(s, n) {
    s = String(s ?? '');
    return s.length > n ? s.slice(0, n) + '…' : s;
  },
  _fmtTime(t) {
    if (!t) return '-';
    try { return new Date(t).toLocaleString('zh-CN', { hour12: false }); } catch { return t; }
  },
};

window.FAQPage = FAQPage;
