/**
 * 知识记忆管理页（Stage 3 自进化 RAG，文档 06；圈 4 对齐线框 06）
 *
 * 三个 Tab（带计数徽章）：
 * - 正式知识（active）：可降级/删除
 * - 候选记忆（candidate）：命中进度环（hit_count/distill_threshold），可升格/删除
 * - PR 审核：我名下 KB 收到的协作 PR（合并/拒绝 + 审核备注）
 *
 * 布局：卡片栅格（候选记忆）/ 表格（正式知识）+ KB 过滤；来源/状态徽章用 tokens 语义色。
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
  tabCounts: { active: null, candidate: null, pr: null },  // null = 未知（不显示）
  knowledgeBases: [],

  async render() {
    this.currentTab = 'active';
    this.currentKbId = null;
    this.page = 1;

    const container = document.getElementById('page-container');
    container.innerHTML = `
      <div class="row between mb6">
        <div>
          <h1 class="h-title">知识记忆</h1>
          <p class="t2 mt2" style="font-size:var(--fs-sm)">对话中沉淀的 FAQ：候选命中达阈值自动蒸馏升格，协作库走 PR 审核</p>
        </div>
        <div class="row" style="gap:var(--sp-2)">
          <button class="btn btn-sm" id="faq-refresh-btn">🔄 刷新</button>
          <button class="btn" id="faq-supplement-btn">＋ 手动补全</button>
        </div>
      </div>

      <div class="tabs faq-tabs mb4" id="faq-tabs">
        <button data-tab="active" class="on">正式知识<span class="count"></span></button>
        <button data-tab="candidate">候选记忆<span class="count"></span></button>
        <button data-tab="pr">PR 审核<span class="count pr-count"></span></button>
      </div>

      <div class="row mb4">
        <select id="faq-kb-filter" class="select" style="width:200px">
          <option value="">全部知识库</option>
        </select>
      </div>

      <div id="faq-body">
        <div class="skeleton" style="height:120px"></div>
      </div>
      <div class="row mt4" id="faq-pager" style="justify-content:center"></div>
    `;

    this.initEvents();
    await this.loadKnowledgeBases();
    await this.loadCounts();
    await this.loadList();
  },

  initEvents() {
    document.getElementById('faq-refresh-btn').addEventListener('click', () => { this.loadCounts(); this.loadList(); });
    document.getElementById('faq-supplement-btn').addEventListener('click', () => this.showSupplementModal());
    document.getElementById('faq-tabs').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-tab]');
      if (!btn) return;
      this.currentTab = btn.dataset.tab;
      this.page = 1;
      document.querySelectorAll('#faq-tabs button').forEach(b => {
        b.classList.toggle('on', b.dataset.tab === this.currentTab);
      });
      this.loadList();
    });
    document.getElementById('faq-kb-filter').addEventListener('change', (e) => {
      this.currentKbId = e.target.value ? parseInt(e.target.value, 10) : null;
      this.page = 1;
      this.loadCounts();
      this.loadList();
    });
    // 空态跳转按钮（如「去问一个问题」→ agent）
    document.getElementById('faq-body').addEventListener('click', (e) => {
      const btn = e.target.closest('[data-goto]');
      if (btn && window.App) window.App.navigate(btn.dataset.goto);
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

  /** 拉三个 Tab 的计数（失败静默，不阻塞主列表） */
  async loadCounts() {
    const jobs = [
      ['active', FaqAPI.listFaqs({ status: 'active', kbId: this.currentKbId, page: 1, pageSize: 1 })],
      ['candidate', FaqAPI.listFaqs({ status: 'candidate', kbId: this.currentKbId, page: 1, pageSize: 1 })],
      ['pr', FaqAPI.listPrs({ kbId: this.currentKbId, page: 1, pageSize: 1 })],
    ];
    await Promise.all(jobs.map(([k, p]) => p
      .then(r => { this.tabCounts[k] = r.total ?? 0; })
      .catch(() => { this.tabCounts[k] = null; })));
    this.renderTabs();
  },

  renderTabs() {
    document.querySelectorAll('#faq-tabs button').forEach(btn => {
      const k = btn.dataset.tab;
      const v = this.tabCounts[k];
      const cntEl = btn.querySelector('.count');
      if (!cntEl) return;
      cntEl.textContent = v === null ? '' : String(v);
      if (k === 'pr' && typeof v === 'number' && v > 0) cntEl.classList.add('has-warn');
      else cntEl.classList.remove('has-warn');
    });
  },

  async loadList() {
    const body = document.getElementById('faq-body');
    body.innerHTML = '<div class="skeleton" style="height:120px"></div>';
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
        if (this.currentTab === 'candidate') this.renderCandidateCards(resp.items || []);
        else this.renderFaqRows(resp.items || []);
      }
    } catch (e) {
      body.innerHTML = `<div class="glass"><div class="state"><div class="glyph" style="color:var(--danger)">✕</div><div class="title">加载失败</div><p class="desc">${this._esc(e.message)}</p></div></div>`;
    }
    this.renderPager();
  },

  async loadPrs() {
    const resp = await FaqAPI.listPrs({ kbId: this.currentKbId, page: this.page, pageSize: this.pageSize });
    this.total = resp.total || 0;
    this.renderPrCards(resp.items || []);
  },

  _kbName(kbId) {
    const kb = this.knowledgeBases.find(k => k.id === kbId);
    return kb ? kb.kb_name : `KB#${kbId}`;
  },

  /* ── 正式知识：表格（线框 06：正式知识 Tab） ─────────── */
  renderFaqRows(items) {
    const body = document.getElementById('faq-body');
    if (!items.length) {
      body.innerHTML = this._emptyState('❖', '还没有正式知识', '在 AI Agent 中提问，或从候选记忆升格。');
      return;
    }
    body.innerHTML = `
      <table class="table">
        <thead><tr>
          <th>问题</th><th>答案</th><th>知识库</th><th>命中</th><th>来源</th><th>热度</th><th style="text-align:right">操作</th>
        </tr></thead>
        <tbody>
          ${items.map(f => `
            <tr>
              <td title="${this._esc(f.question)}">${this._esc(this._cut(f.question, 40))}</td>
              <td title="${this._esc(f.answer)}">${this._esc(this._cut(f.answer, 60))}</td>
              <td><span class="badge">${this._esc(this._kbName(f.kb_id))}</span></td>
              <td class="num">${f.hit_count ?? 0}</td>
              <td><span class="badge ${f.source === 'manual' ? 'info' : 'accent'}">${f.source === 'manual' ? '手动补全' : '对话沉淀'}</span></td>
              <td class="num t3">${(f.heat_score || 0).toFixed(2)}</td>
              <td style="text-align:right;white-space:nowrap">
                <button class="btn btn-sm" data-demote="${f.id}">降级</button>
                <button class="icon-btn" data-remove="${f.id}" title="删除">🗑</button>
              </td>
            </tr>`).join('')}
        </tbody>
      </table>`;
    body.querySelectorAll('[data-demote]').forEach(b =>
      b.addEventListener('click', () => this.demote(parseInt(b.dataset.demote, 10))));
    body.querySelectorAll('[data-remove]').forEach(b =>
      b.addEventListener('click', () => this.removeFaq(parseInt(b.dataset.remove, 10))));
  },

  /* ── 候选记忆：双列卡片栅格 + 命中进度环（线框 06） ───── */
  renderCandidateCards(items) {
    const body = document.getElementById('faq-body');
    if (!items.length) {
      body.innerHTML = this._emptyState('❖', '还没有候选记忆',
        '在 AI Agent 中提问，未被覆盖的问题可一键沉淀为候选 FAQ。',
        { label: '去问一个问题', page: 'agent' });
      return;
    }
    body.innerHTML = `<div class="grid faq">${items.map(f => {
      const hits = f.hit_count ?? 0;
      const thr = Math.max(1, f.distill_threshold ?? 1);
      const reached = hits >= thr;
      const pct = Math.min(1, hits / thr);
      const R = 18, C = 2 * Math.PI * R;
      return `
        <div class="glass card card-hover col ${reached ? 'faq-ready' : ''}">
          <div class="row between">
            <span class="badge ${f.source === 'manual' ? 'info' : 'accent'}">${f.source === 'manual' ? '手动补全' : '对话沉淀'}</span>
            <svg class="ring" viewBox="0 0 44 44" title="命中 ${hits}/${thr}">
              <circle class="bg" cx="22" cy="22" r="${R}"/>
              <circle class="fg" cx="22" cy="22" r="${R}"
                stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${(C * (1 - pct)).toFixed(1)}"/>
            </svg>
          </div>
          <b style="font-size:var(--fs-lg)">${this._esc(f.question)}</b>
          <p class="t2" style="font-size:var(--fs-sm)">答：${this._esc(this._cut(f.answer, 90))}</p>
          <div class="row wrap" style="gap:6px">
            <span class="badge">${this._esc(this._kbName(f.kb_id))}</span>
            <span class="t3 num" style="font-size:var(--fs-xs)">${reached ? `已达阈值 ${hits}/${thr} · 待蒸馏` : `命中 ${hits}/${thr} · 再命中 ${thr - hits} 次自动升格`}</span>
          </div>
          <div class="row" style="border-top:1px solid var(--glass-border);padding-top:var(--sp-3)">
            <div class="spacer"></div>
            <button class="btn btn-sm btn-ghost" data-remove="${f.id}">删除</button>
            <button class="btn btn-sm btn-primary" data-promote="${f.id}">${reached ? '升格为正式' : '提前升格'}</button>
          </div>
        </div>`;
    }).join('')}</div>`;
    body.querySelectorAll('[data-promote]').forEach(b =>
      b.addEventListener('click', () => this.promote(parseInt(b.dataset.promote, 10))));
    body.querySelectorAll('[data-remove]').forEach(b =>
      b.addEventListener('click', () => this.removeFaq(parseInt(b.dataset.remove, 10))));
  },

  /* ── PR 审核：卡片 + 合并/拒绝 + 备注（线框 06：左缘警示条） ── */
  renderPrCards(items) {
    const body = document.getElementById('faq-body');
    if (!items.length) {
      body.innerHTML = this._emptyState('📬', '暂无待审核的协作提交',
        '其他用户向你的共享知识库提交的 FAQ 会出现在这里。');
      return;
    }
    body.innerHTML = `<div class="col">${items.map(pr => `
      <div class="glass card faq-pr-warn">
        <div class="row between">
          <b>${this._esc(pr.question)}</b>
          <span class="badge warn">来自 ${this._esc(pr.submitter_name || `用户#${pr.submitted_by}`)} → ${this._esc(pr.target_kb_name || `KB#${pr.target_kb_id}`)}</span>
        </div>
        <p class="t2 mt4" style="font-size:var(--fs-sm)">答：${this._esc(pr.answer)}</p>
        <div class="row mt4">
          <input type="text" class="input grow pr-note" data-pr="${pr.id}" placeholder="审核备注（可选）…" style="height:32px" />
          <button class="btn btn-sm btn-primary" data-merge="${pr.id}">合并</button>
          <button class="btn btn-sm btn-danger" data-reject="${pr.id}">拒绝</button>
        </div>
      </div>`).join('')}</div>`;
    body.querySelectorAll('[data-merge]').forEach(b =>
      b.addEventListener('click', () => this.reviewPr(parseInt(b.dataset.merge, 10), true)));
    body.querySelectorAll('[data-reject]').forEach(b =>
      b.addEventListener('click', () => this.reviewPr(parseInt(b.dataset.reject, 10), false)));
  },

  _emptyState(glyph, title, desc, action = null) {
    return `
      <div class="glass"><div class="state">
        <div class="glyph">${glyph}</div>
        <div class="title">${title}</div>
        <p class="desc">${desc}</p>
        ${action ? `<button class="btn btn-sm btn-primary" data-goto="${action.page}">${action.label}</button>` : ''}
      </div></div>`;
  },

  renderPager() {
    const pager = document.getElementById('faq-pager');
    if (!pager) return;
    const pages = Math.max(1, Math.ceil(this.total / this.pageSize));
    if (this.total <= this.pageSize) { pager.innerHTML = ''; return; }
    pager.innerHTML = `
      <button class="btn btn-sm" ${this.page <= 1 ? 'disabled' : ''} data-page="${this.page - 1}">← 上一页</button>
      <span class="num t3" style="font-size:var(--fs-sm)">${this.page} / ${pages} · 共 ${this.total} 条</span>
      <button class="btn btn-sm" ${this.page >= pages ? 'disabled' : ''} data-page="${this.page + 1}">下一页 →</button>`;
    pager.querySelectorAll('[data-page]').forEach(b =>
      b.addEventListener('click', () => this.goPage(parseInt(b.dataset.page, 10))));
  },

  goPage(p) {
    this.page = p;
    this.loadList();
  },

  async promote(id) {
    try {
      await FaqAPI.promote(id);
      window.App.showToast('已升格为正式知识', 'success');
      this.loadCounts();
      this.loadList();
    } catch (e) { window.App.showToast('升格失败: ' + e.message, 'error'); }
  },

  async demote(id) {
    try {
      await FaqAPI.demote(id);
      window.App.showToast('已降级为候选记忆', 'success');
      this.loadCounts();
      this.loadList();
    } catch (e) { window.App.showToast('降级失败: ' + e.message, 'error'); }
  },

  async removeFaq(id) {
    const ok = await window.UI.confirm({
      title: '删除知识记忆',
      message: '确定删除这条知识记忆？删除后不可恢复。',
      okText: '删除',
      danger: true
    });
    if (!ok) return;
    try {
      await FaqAPI.remove(id);
      window.App.showToast('已删除', 'success');
      this.loadCounts();
      this.loadList();
    } catch (e) { window.App.showToast('删除失败: ' + e.message, 'error'); }
  },

  async reviewPr(id, approve) {
    const noteEl = document.querySelector(`.pr-note[data-pr="${id}"]`);
    const note = noteEl ? noteEl.value.trim() || null : null;
    try {
      if (approve) {
        await FaqAPI.mergePr(id, note);
        window.App.showToast('已合并，知识已生效', 'success');
      } else {
        await FaqAPI.rejectPr(id, note);
        window.App.showToast('已拒绝', 'success');
      }
      this.loadCounts();
      this.loadList();
    } catch (e) { window.App.showToast('操作失败: ' + e.message, 'error'); }
  },

  /* 手动补全弹窗（线框 06 头部按钮：问题 + 答案 + 目标 KB） */
  showSupplementModal() {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal">
        <div class="modal-header">
          <h3 class="modal-title">手动补全知识</h3>
          <button type="button" class="modal-close" aria-label="关闭">×</button>
        </div>
        <div class="modal-body">
          <div class="form-field">
            <label>问题</label>
            <input type="text" id="supp-question" placeholder="用户会怎么问？（标准问法）" />
          </div>
          <div class="form-field">
            <label>答案</label>
            <textarea id="supp-answer" rows="4" placeholder="标准答案要点"></textarea>
          </div>
          <div class="form-field">
            <label>目标知识库</label>
            <select id="supp-kb">
              <option value="">默认私有库（我的知识库）</option>
              ${this.knowledgeBases.map(kb => `<option value="${kb.id}">${this._esc(kb.kb_name)}</option>`).join('')}
            </select>
            <div class="form-hint">私有库直接写入候选；他人共享库将提交 PR 由库主审核</div>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-ghost" data-act="cancel">取消</button>
          <button type="button" class="btn btn-primary" data-act="ok">提交补全</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    overlay.querySelector('.modal-close').addEventListener('click', close);
    overlay.querySelector('[data-act="cancel"]').addEventListener('click', close);
    overlay.querySelector('[data-act="ok"]').addEventListener('click', async () => {
      const question = overlay.querySelector('#supp-question').value.trim();
      const answer = overlay.querySelector('#supp-answer').value.trim();
      const kbId = overlay.querySelector('#supp-kb').value || null;
      if (!question || !answer) {
        window.App.showToast('问题和答案都不能为空', 'error');
        return;
      }
      try {
        await FaqAPI.supplement({ question, answer, kb_id: kbId ? parseInt(kbId, 10) : null });
        window.App.showToast('已提交补全（进入候选记忆）', 'success');
        close();
        this.loadCounts();
        this.loadList();
      } catch (e) {
        window.App.showToast('提交失败: ' + e.message, 'error');
      }
    });
    const onKey = (e) => { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', onKey); } };
    document.addEventListener('keydown', onKey);
  },

  _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  },
  _cut(s, n) {
    s = String(s ?? '');
    return s.length > n ? s.slice(0, n) + '…' : s;
  },
};

window.FAQPage = FAQPage;
