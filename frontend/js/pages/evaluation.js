/**
 * 测试集管理页面（评估质量基础设施）
 *
 * - 测试集列表 + 样本表格（status 徽章）+ 浮层审核（改 answer/contexts/ground_truth + 一键生成GT）
 * - 多格式导入 + 跑评估（approved<30 禁用门控）
 *
 * UI 铁律：浮层用 fixed 遮罩 + blur + Esc/点遮罩关闭；布局容器 inline style 显式声明；
 *         禁用原生 confirm/prompt/alert，统一 window.UI.*；长操作用 App.showLoading/hideLoading。
 */
const EvaluationPage = {
  _datasets: [],
  _current: null,         // 当前选中测试集 name
  _samples: [],
  _stats: null,           // 当前测试集 stats（含 total/pending/approved/rejected/with_gt/by_source）
  _page: 1,
  _pageSize: 20,
  _total: 0,
  _filters: { status: 'all', source: 'all' },

  async render() {
    const container = document.getElementById('page-container');
    container.innerHTML = `
      <div class="eval-layout">
      <div style="display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:var(--sp-3);margin-bottom:var(--sp-4)">
        <div>
          <h1 class="h-title">测试集管理</h1>
          <p class="t2 mt2" style="font-size:var(--fs-sm)">从 session 提取 → 待审状态 → 人工审核（含 LLM 辅助补 ground_truth）→ approved 入评估</p>
        </div>
        <div style="display:flex;gap:var(--sp-2);flex-wrap:wrap">
          <button class="btn btn-sm" id="eval-from-session-btn">从 Session 提取</button>
          <button class="btn btn-sm" id="eval-import-btn">导入</button>
          <button class="btn btn-sm" id="eval-run-btn" disabled>跑评估</button>
          <input type="file" id="eval-import-input" accept=".json,.jsonl" style="display:none" />
        </div>
      </div>
      <div id="eval-stats" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:var(--sp-3);margin-bottom:var(--sp-4)">
        <div class="skeleton" style="height:80px"></div>
        <div class="skeleton" style="height:80px"></div>
        <div class="skeleton" style="height:80px"></div>
        <div class="skeleton" style="height:80px"></div>
        <div class="skeleton" style="height:80px"></div>
      </div>
      <div style="display:flex;gap:var(--sp-4);flex-wrap:wrap;align-items:flex-start">
        <div style="flex:0 0 240px;max-width:240px">
          <div class="label-caps" style="margin-bottom:var(--sp-2)">测试集</div>
          <div id="eval-dataset-list" class="glass" style="padding:var(--sp-2);max-height:600px;overflow:auto">
            <div class="skeleton" style="height:60px"></div>
          </div>
        </div>
        <div style="flex:1;min-width:0">
          <div id="eval-sample-panel" class="glass" style="padding:var(--sp-3);min-height:280px;max-height:calc(100vh - 300px);display:flex;flex-direction:column">
            <div class="state"><div class="glyph">≣</div><div class="title">未选择测试集</div><p class="desc">从左侧选择一个测试集查看样本</p></div>
          </div>
        </div>
      </div>
      </div>
    `;

    // 按钮事件
    document.getElementById('eval-from-session-btn').addEventListener('click', () => this._fromSession());
    document.getElementById('eval-import-btn').addEventListener('click', () => document.getElementById('eval-import-input').click());
    document.getElementById('eval-import-input').addEventListener('change', (e) => this._importFile(e));
    document.getElementById('eval-run-btn').addEventListener('click', () => this._runEval());

    await this._listDatasets();
  },

  // ===== 统计卡（当前测试集概览） =====
  _renderStats() {
    const el = document.getElementById('eval-stats');
    if (!el) return;
    // 从当前选中测试集的 stats 渲染，无选中则显示数据集数
    if (!this._current || !this._stats) {
      const dsCount = this._datasets.length;
      el.innerHTML = `
        <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:4px;min-width:0"><div class="label-caps">测试集数</div><b class="num" style="font-size:var(--fs-xl)">${dsCount}</b></div>
        <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:4px;min-width:0"><div class="label-caps">总样本</div><b class="num" style="font-size:var(--fs-xl)">${this._datasets.reduce((s, d) => s + (d.count ?? 0), 0)}</b></div>
        <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:4px;min-width:0"><div class="label-caps">待审</div><b class="num" style="font-size:var(--fs-xl);color:var(--t3)">—</b></div>
        <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:4px;min-width:0"><div class="label-caps">已通过</div><b class="num" style="font-size:var(--fs-xl);color:var(--t3)">—</b></div>
        <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:4px;min-width:0"><div class="label-caps">含 GT</div><b class="num" style="font-size:var(--fs-xl);color:var(--t3)">—</b></div>
      `;
      this._updateRunBtn(0);
      return;
    }
    const s = this._stats;
    const total = s.total ?? 0;
    const pending = (s.status && s.status.pending) ?? 0;
    const approved = (s.status && s.status.approved) ?? 0;
    const withGt = s.with_ground_truth ?? 0;
    const sourceCount = s.sources ? Object.keys(s.sources).length : 0;
    el.innerHTML = `
      <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:4px;min-width:0"><div class="label-caps">总样本</div><b class="num" style="font-size:var(--fs-xl)">${total}</b></div>
      <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:4px;min-width:0"><div class="label-caps">待审</div><b class="num" style="font-size:var(--fs-xl);color:var(--warn)">${pending}</b></div>
      <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:4px;min-width:0"><div class="label-caps">已通过</div><b class="num" style="font-size:var(--fs-xl);color:var(--ok)">${approved}</b></div>
      <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:4px;min-width:0"><div class="label-caps">含 GT</div><b class="num" style="font-size:var(--fs-xl)">${withGt}</b></div>
      <div class="glass" style="padding:14px 18px;display:flex;flex-direction:column;gap:4px;min-width:0"><div class="label-caps">来源数</div><b class="num" style="font-size:var(--fs-xl)">${sourceCount}</b></div>
    `;
    this._updateRunBtn(approved);
  },

  _updateRunBtn(approvedCount) {
    const btn = document.getElementById('eval-run-btn');
    if (!btn) return;
    if (approvedCount >= 30) {
      btn.disabled = false;
      btn.title = '';
      btn.classList.remove('btn-ghost');
      btn.classList.add('btn-primary');
    } else {
      btn.disabled = true;
      btn.title = `审核通过样本仅 ${approvedCount} 条，不足 30 条，无法保证评估统计显著性`;
      btn.classList.add('btn-ghost');
      btn.classList.remove('btn-primary');
    }
  },

  // ===== 测试集列表 =====
  async _listDatasets() {
    const el = document.getElementById('eval-dataset-list');
    el.innerHTML = '<div class="skeleton" style="height:60px"></div>';
    try {
      const resp = await window.EvaluationAPI.listDatasets();
      this._datasets = resp.datasets || resp || [];
      if (!this._datasets.length) {
        el.innerHTML = '<div class="state" style="padding:var(--sp-3)"><div class="glyph">≣</div><div class="title">无测试集</div><p class="desc" style="font-size:var(--fs-xs)">从 session 提取或导入文件</p></div>';
      } else {
        el.innerHTML = this._datasets.map(ds => {
          const name = ds.name || ds.dataset_name || '—';
          const count = ds.count ?? 0;
          const isActive = name === this._current;
          return `
            <div style="padding:8px 10px;border-radius:6px;cursor:pointer;margin-bottom:4px;${isActive ? 'background:var(--accent-soft);border-left:3px solid var(--accent)' : ''}" class="eval-ds-item" data-name="${this._esc(name)}">
              <div style="font-weight:600;font-size:var(--fs-sm);word-break:break-all">${this._esc(name)}</div>
              <div style="font-size:var(--fs-xs);margin-top:2px" class="t3">${count} 条</div>
            </div>`;
        }).join('');
        // 绑定点击
        el.querySelectorAll('.eval-ds-item').forEach(item => {
          item.addEventListener('click', () => {
            this._current = item.dataset.name;
            this._page = 1;
            this._filters = { status: 'all', source: 'all' };
            this.render();
          });
        });
      }
      this._renderStats();
      // 如果有选中的测试集，加载样本
      if (this._current && this._datasets.some(d => (d.name || d.dataset_name) === this._current)) {
        await this._loadSamples();
      }
    } catch (err) {
      el.innerHTML = `<div class="state" style="padding:var(--sp-3)"><div class="glyph" style="color:var(--danger)">✕</div><div class="title">加载失败</div><p class="desc" style="font-size:var(--fs-xs)">${this._esc(err.message)}</p></div>`;
    }
  },

  // ===== 样本表格 =====
  // 策略：始终用 status='all' 取全量（page_size=100），前端本地过滤+分页，
  // 保证 idx = 全局索引，与 sample/{idx} 端点对齐。
  async _loadSamples() {
    const panel = document.getElementById('eval-sample-panel');
    if (!this._current) {
      panel.innerHTML = '<div class="state"><div class="glyph">≣</div><div class="title">未选择测试集</div><p class="desc">从左侧选择一个测试集查看样本</p></div>';
      return;
    }
    panel.innerHTML = `
      <div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;align-items:center;margin-bottom:var(--sp-3)">
        <select class="select" id="eval-filter-status" style="min-width:120px;accent-color:var(--accent);outline:1px solid var(--border-light)">
          <option value="all" ${this._filters.status === 'all' ? 'selected' : ''}>全部状态</option>
          <option value="pending" ${this._filters.status === 'pending' ? 'selected' : ''}>待审</option>
          <option value="approved" ${this._filters.status === 'approved' ? 'selected' : ''}>已通过</option>
          <option value="rejected" ${this._filters.status === 'rejected' ? 'selected' : ''}>已驳回</option>
        </select>
        <span style="flex:1"></span>
        <button class="btn btn-sm btn-ghost" id="eval-export-btn">导出</button>
        <button class="btn btn-sm btn-ghost" id="eval-delete-btn">删除</button>
      </div>
      <div id="eval-sample-table" style="flex:1 1 auto;overflow:auto;min-height:0"><div class="skeleton" style="height:80px"></div></div>
      <div id="eval-pagination" style="display:flex;justify-content:space-between;align-items:center;margin-top:var(--sp-3)"></div>
    `;

    document.getElementById('eval-filter-status').addEventListener('change', (e) => {
      this._filters.status = e.target.value;
      this._page = 1;
      this._renderFilteredSamples();
    });
    document.getElementById('eval-export-btn').addEventListener('click', () => this._exportDataset());
    document.getElementById('eval-delete-btn').addEventListener('click', () => this._deleteDataset());

    const tblEl = document.getElementById('eval-sample-table');
    tblEl.innerHTML = '<div class="skeleton" style="height:80px"></div>';
    try {
      // 始终取全量（status='all', page_size=100），保证 idx = 全局索引
      const resp = await window.EvaluationAPI.samples(this._current, {
        status: 'all',
        page: 1,
        page_size: 100,
        source: 'all',
      });
      this._allSamples = (resp.samples || resp.items || []).map((s, i) => ({ ...s, _idx: i }));
      this._stats = resp.stats || null;
      this._renderStats();
      this._renderFilteredSamples();
    } catch (err) {
      tblEl.innerHTML = `<div class="state"><div class="glyph" style="color:var(--danger)">✕</div><div class="title">加载失败</div><p class="desc">${this._esc(err.message)}</p></div>`;
      document.getElementById('eval-pagination').innerHTML = '';
    }
  },

  /** 本地过滤 + 分页渲染 */
  _renderFilteredSamples() {
    let filtered = this._allSamples || [];
    if (this._filters.status !== 'all') {
      filtered = filtered.filter(s => (s.status || 'pending') === this._filters.status);
    }
    this._total = filtered.length;
    const start = (this._page - 1) * this._pageSize;
    const end = start + this._pageSize;
    this._samples = filtered.slice(start, end);
    this._renderSampleTable();
    this._renderPagination();
  },

  _renderSampleTable() {
    const el = document.getElementById('eval-sample-table');
    if (!this._samples.length) {
      el.innerHTML = '<div class="state"><div class="glyph">≣</div><div class="title">无样本</div><p class="desc">该测试集为空或无匹配样本</p></div>';
      return;
    }
    el.innerHTML = `
      <table class="table dense">
        <thead><tr>
          <th>#</th><th>问题</th><th>来源</th><th>状态</th><th>GT</th><th style="text-align:right">操作</th>
        </tr></thead>
        <tbody>
          ${this._samples.map((s, i) => this._renderSampleRow(s, i)).join('')}
        </tbody>
      </table>
    `;
    // 绑定操作按钮
    this._samples.forEach((s) => {
      const idx = s._idx;
      const reviewBtn = document.getElementById(`eval-review-${idx}`);
      if (reviewBtn) reviewBtn.addEventListener('click', () => this._showSampleDetail(idx));
    });
  },

  _renderSampleRow(s) {
    const idx = s._idx;
    const question = String(s.question || '').slice(0, 80);
    const source = s.metadata?.source || s.source || '—';
    const status = s.status || 'pending';
    const hasGt = !!(s.ground_truth && s.ground_truth.trim());
    const statusBadge = this._statusBadge(status);
    const gtMark = hasGt ? '<span style="color:var(--ok)">✓</span>' : '<span style="color:var(--t3)">✗</span>';
    return `
      <tr>
        <td class="num">${idx}</td>
        <td title="${this._esc(s.question || '')}">${this._esc(question)}${(s.question || '').length > 80 ? '…' : ''}</td>
        <td class="t3">${this._esc(source)}</td>
        <td>${statusBadge}</td>
        <td style="text-align:center">${gtMark}</td>
        <td style="text-align:right;white-space:nowrap">
          <button class="btn btn-sm" id="eval-review-${idx}">审核</button>
        </td>
      </tr>`;
  },

  _statusBadge(status) {
    const cls = status === 'approved' ? 'badge ok' : status === 'rejected' ? 'badge danger' : 'badge warn';
    const label = status === 'approved' ? '通过' : status === 'rejected' ? '驳回' : '待审';
    return `<span class="${cls} num">${this._esc(label)}</span>`;
  },

  _renderPagination() {
    const el = document.getElementById('eval-pagination');
    const pages = Math.max(1, Math.ceil(this._total / this._pageSize));
    el.innerHTML = `
      <span class="t3">共 ${this._total} 条 · 每页 ${this._pageSize}</span>
      <span class="num t3">${this._page} / ${pages}</span>
      <div style="display:flex;gap:var(--sp-2)">
        <button class="btn btn-sm" id="eval-pg-prev" ${this._page <= 1 ? 'disabled' : ''}>← 上一页</button>
        <button class="btn btn-sm" id="eval-pg-next" ${this._page >= pages ? 'disabled' : ''}>下一页 →</button>
      </div>
    `;
    const prev = document.getElementById('eval-pg-prev');
    const next = document.getElementById('eval-pg-next');
    if (prev && !prev.disabled) prev.addEventListener('click', () => { this._page--; this._renderFilteredSamples(); });
    if (next && !next.disabled) next.addEventListener('click', () => { this._page++; this._renderFilteredSamples(); });
  },

  // ===== 浮层审核 =====
  async _showSampleDetail(idx) {
    let overlay = document.getElementById('eval-detail-overlay');
    if (overlay) overlay.remove();
    overlay = document.createElement('div');
    overlay.id = 'eval-detail-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.55);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);z-index:70;display:flex;align-items:center;justify-content:center;padding:var(--sp-4)';
    document.body.appendChild(overlay);
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
    const escHandler = (e) => { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', escHandler); } };
    document.addEventListener('keydown', escHandler);

    overlay.innerHTML = `<div class="glass" style="width:min(760px,92vw);max-height:88vh;overflow:auto;padding:var(--sp-5)"><div class="skeleton" style="height:200px"></div></div>`;

    try {
      const resp = await window.EvaluationAPI.sampleDetail(this._current, idx);
      const s = resp.sample || resp;
      const contexts = Array.isArray(s.contexts) ? s.contexts.join('\n---\n') : (s.contexts || '');
      const answerNote = s.metadata?.source === 'session' ? '<span class="badge warn num">Agent 生成，需审核</span>' : '';
      overlay.innerHTML = `
        <div class="glass" style="width:min(760px,92vw);max-height:88vh;overflow:auto;padding:var(--sp-5)">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--sp-3)">
            <h2 class="h-title" style="font-size:var(--fs-lg)">样本 #${idx} 审核</h2>
            <button class="btn btn-sm btn-ghost" id="eval-detail-close">✕ 关闭</button>
          </div>
          <div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;margin-bottom:var(--sp-4);font-size:var(--fs-xs)" class="t3">
            <span>状态 ${this._statusBadge(s.status || 'pending')}</span>
            <span>来源 <b class="num">${this._esc(s.metadata?.source || '—')}</b></span>
            ${answerNote}
          </div>
          <div style="margin-bottom:var(--sp-3)">
            <label class="label-caps" style="margin-bottom:4px;display:block">问题（只读）</label>
            <textarea class="input" readonly style="width:100%;min-height:60px;resize:vertical;accent-color:var(--accent);outline:1px solid var(--border-light);opacity:0.85">${this._esc(s.question || '')}</textarea>
          </div>
          <div style="margin-bottom:var(--sp-3)">
            <label class="label-caps" style="margin-bottom:4px;display:block">Answer</label>
            <textarea class="input" id="eval-edit-answer" style="width:100%;min-height:80px;resize:vertical;accent-color:var(--accent);outline:1px solid var(--border-light)">${this._esc(s.answer || '')}</textarea>
          </div>
          <div style="margin-bottom:var(--sp-3)">
            <label class="label-caps" style="margin-bottom:4px;display:block">Contexts（每段用 --- 分隔）</label>
            <textarea class="input" id="eval-edit-contexts" style="width:100%;min-height:120px;resize:vertical;accent-color:var(--accent);outline:1px solid var(--border-light)">${this._esc(contexts)}</textarea>
          </div>
          <div style="margin-bottom:var(--sp-4)">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
              <label class="label-caps">Ground Truth</label>
              <button class="btn btn-sm btn-ghost" id="eval-gen-gt-btn">✨ 一键生成 GT</button>
            </div>
            <textarea class="input" id="eval-edit-gt" style="width:100%;min-height:80px;resize:vertical;accent-color:var(--accent);outline:1px solid var(--border-light)">${this._esc(s.ground_truth || '')}</textarea>
          </div>
          <div style="display:flex;justify-content:flex-end;gap:var(--sp-2)">
            <button class="btn btn-sm" id="eval-approve-inline">✓ 通过</button>
            <button class="btn btn-sm" id="eval-reject-inline">✕ 驳回</button>
            <button class="btn btn-sm btn-ghost" id="eval-detail-close2">取消</button>
            <button class="btn btn-sm btn-primary" id="eval-save-btn">保存</button>
          </div>
        </div>
      `;
      document.getElementById('eval-detail-close').addEventListener('click', () => overlay.remove());
      document.getElementById('eval-detail-close2').addEventListener('click', () => overlay.remove());
      document.getElementById('eval-save-btn').addEventListener('click', () => this._saveEdit(idx));
      document.getElementById('eval-gen-gt-btn').addEventListener('click', () => this._generateGt(idx));
      document.getElementById('eval-approve-inline').addEventListener('click', () => { this._approve(idx); overlay.remove(); });
      document.getElementById('eval-reject-inline').addEventListener('click', () => { this._reject(idx); overlay.remove(); });
    } catch (err) {
      overlay.innerHTML = `<div class="glass" style="width:min(480px,92vw);padding:var(--sp-5)"><div class="state"><div class="glyph" style="color:var(--danger)">✕</div><div class="title">加载失败</div><p class="desc">${this._esc(err.message)}</p></div></div>`;
    }
  },

  async _generateGt(idx) {
    const btn = document.getElementById('eval-gen-gt-btn');
    const done = window.btnLoading(btn, '生成中…');
    window.App.showLoading('正在调用 LLM 生成 Ground Truth…');
    try {
      const resp = await window.EvaluationAPI.generateGt(this._current, idx);
      const gt = resp.ground_truth || '';
      const ta = document.getElementById('eval-edit-gt');
      if (ta) ta.value = gt;
      window.App.showToast('GT 草稿已生成，请审核后保存', 'success');
    } catch (err) {
      if (!err._autoToasted) window.App.showToast(err.message, 'error');
    } finally {
      done();
      window.App.hideLoading();
    }
  },

  async _saveEdit(idx) {
    const answer = document.getElementById('eval-edit-answer')?.value ?? '';
    const contextsRaw = document.getElementById('eval-edit-contexts')?.value ?? '';
    const gt = document.getElementById('eval-edit-gt')?.value ?? '';
    const contexts = contextsRaw.split(/\n---\n/).map(s => s.trim()).filter(Boolean);
    const btn = document.getElementById('eval-save-btn');
    const done = window.btnLoading(btn, '保存中…');
    try {
      await window.EvaluationAPI.updateSample(this._current, idx, {
        answer: answer || undefined,
        contexts: contexts.length ? contexts : undefined,
        ground_truth: gt || undefined,
      });
      window.App.showToast('保存成功', 'success');
      document.getElementById('eval-detail-overlay')?.remove();
      await this._loadSamples();
      await this._listDatasets();
    } catch (err) {
      if (!err._autoToasted) window.App.showToast(err.message, 'error');
    } finally {
      done();
    }
  },

  async _approve(idx) {
    try {
      await window.EvaluationAPI.approve(this._current, idx);
      window.App.showToast('已通过', 'success');
      await this._loadSamples();
      await this._listDatasets();
    } catch (err) {
      if (!err._autoToasted) window.App.showToast(err.message, 'error');
    }
  },

  async _reject(idx) {
    try {
      await window.EvaluationAPI.reject(this._current, idx);
      window.App.showToast('已驳回', 'success');
      await this._loadSamples();
      await this._listDatasets();
    } catch (err) {
      if (!err._autoToasted) window.App.showToast(err.message, 'error');
    }
  },

  // ===== 从 Session 提取 =====
  async _fromSession() {
    let name;
    try {
      name = await window.UI.prompt({
        title: '从 Session 提取测试集',
        message: '输入测试集名称（留空自动生成）：',
        placeholder: '如 eval-dataset-001',
      });
    } catch (e) { return; } // 用户取消
    if (name === null) return;
    window.App.showLoading('正在从 session 历史提取样本…');
    try {
      const resp = await window.EvaluationAPI.fromSessions({
        name: name || null,
        min_sources_count: 1,
        max_samples: 50,
      });
      window.App.showToast(`提取成功：${resp.name || name || ''}（${resp.count || 0} 条样本）`, 'success');
      this._current = resp.name || name || null;
      this._page = 1;
      await this._listDatasets();
    } catch (err) {
      if (!err._autoToasted) window.App.showToast(err.message, 'error');
    } finally {
      window.App.hideLoading();
    }
  },

  // ===== 导入 =====
  async _importFile(e) {
    const file = e.target.files[0];
    if (!file) return;
    // 前端校验：文件大小 < 10MB
    if (file.size > 10 * 1024 * 1024) {
      window.App.showToast('文件超过 10MB 限制', 'error');
      e.target.value = '';
      return;
    }
    let format = 'auto';
    // 如果文件名含 ragas/crudrag/nfcorpus，自动选择格式
    const fn = (file.name || '').toLowerCase();
    if (fn.includes('ragas')) format = 'ragas';
    else if (fn.includes('crud')) format = 'crudrag';
    else if (fn.includes('nfc')) format = 'nfcorpus';

    window.App.showLoading('正在导入文件…');
    try {
      const resp = await window.EvaluationAPI.importFile(file, format);
      window.App.showToast(`导入成功：${resp.name || ''}（${resp.count || 0} 条样本）`, 'success');
      this._current = resp.name || null;
      await this._listDatasets();
    } catch (err) {
      if (!err._autoToasted) window.App.showToast(err.message, 'error');
    } finally {
      window.App.hideLoading();
      e.target.value = '';
    }
  },

  // ===== 导出 =====
  async _exportDataset() {
    let format;
    try {
      // 简单选择：用 prompt 让用户选 ours 或 ragas
      format = await window.UI.prompt({
        title: '导出测试集',
        message: '输入导出格式（ours 或 ragas）：',
        defaultValue: 'ours',
        placeholder: 'ours',
      });
    } catch (e) { return; }
    if (!format) return;
    format = format.trim().toLowerCase();
    if (format !== 'ours' && format !== 'ragas') {
      window.App.showToast('格式仅支持 ours 或 ragas', 'error');
      return;
    }
    window.App.showLoading('正在导出…');
    try {
      const url = window.EvaluationAPI.exportUrl(this._current, format);
      const token = window.TokenManager.get();
      const r = await fetch(url, { headers: { Authorization: 'Bearer ' + token } });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const blob = await r.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${this._current}_${format}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
      window.App.showToast('导出成功，已开始下载', 'success');
    } catch (err) {
      window.App.showToast(err.message, 'error');
    } finally {
      window.App.hideLoading();
    }
  },

  // ===== 删除测试集 =====
  async _deleteDataset() {
    try {
      await window.UI.confirm({
        title: '删除测试集',
        message: `确认删除测试集「${this._current}」？此操作不可撤销。`,
        danger: true,
        okText: '删除',
      });
    } catch (e) { return; }
    try {
      await window.EvaluationAPI.deleteDataset(this._current);
      window.App.showToast('已删除', 'success');
      this._current = null;
      this._page = 1;
      await this._listDatasets();
      const panel = document.getElementById('eval-sample-panel');
      if (panel) panel.innerHTML = '<div class="state"><div class="glyph">≣</div><div class="title">未选择测试集</div><p class="desc">从左侧选择一个测试集查看样本</p></div>';
    } catch (err) {
      if (!err._autoToasted) window.App.showToast(err.message, 'error');
    }
  },

  // ===== 跑评估 =====
  async _runEval() {
    let agentType;
    try {
      agentType = await window.UI.prompt({
        title: '跑评估',
        message: '选择 Agent 类型（claw / advanced / simple）：',
        defaultValue: 'claw',
        placeholder: 'claw',
      });
    } catch (e) { return; }
    if (!agentType) return;
    agentType = agentType.trim() || 'claw';

    window.App.showLoading('正在启动评估任务…');
    try {
      const resp = await window.EvaluationAPI.runEval({
        dataset_name: this._current,
        agent_type: agentType,
        auto_fill: true,
      });
      window.App.showToast(`评估已启动，报告：${resp.report_file || resp.report || '生成中'}`, 'success');
    } catch (err) {
      if (!err._autoToasted) window.App.showToast(err.message, 'error');
    } finally {
      window.App.hideLoading();
    }
  },

  _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  },
};

window.EvaluationPage = EvaluationPage;
