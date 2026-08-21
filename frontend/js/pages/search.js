/**
 * 知识检索页面 — 圈 3 按线框 04 重构
 * Hero 搜索 + seg 模式切换 + 最近搜索 chips + 横向召回漏斗（分层色）+ 结果卡双分数
 * 数据口径不变：三模式 / 策略 / Rerank / Top-K / 历史 localStorage
 */

const SearchPage = {
  selectedKbId: null,
  knowledgeBases: [],
  searchResults: [],
  isSearching: false,
  lastSearchMeta: {},   // 上次搜索元信息
  searchHistory: [],    // 搜索历史

  async render() {
    const container = document.getElementById('page-container');
    container.innerHTML = `
      <div class="search-hero glass-card">
        <div class="hero-search-row">
          <input class="input grow hero-query" id="search-query"
            placeholder="搜索知识库…  例如：RAG 系统包含哪些阶段" />
          <button class="btn btn-primary hero-search-btn" id="search-btn">搜索</button>
        </div>
        <div class="hero-controls-row">
          <div class="seg" role="radiogroup" aria-label="检索模式">
            <button class="mode-btn active" data-mode="vector">向量<span class="seg-sub"> 语义</span></button>
            <button class="mode-btn" data-mode="keyword">关键词<span class="seg-sub"> BM25</span></button>
            <button class="mode-btn" data-mode="hybrid">混合<span class="seg-sub"> RRF+Rerank</span></button>
          </div>
          <select id="vector-strategy" class="input" title="向量检索策略">
            <option value="advanced" selected>策略：摘要+子问题</option>
            <option value="native">策略：原文匹配</option>
            <option value="hybrid">策略：三路融合</option>
          </select>
          <label class="toggle-switch" title="启用后对召回结果进行精排，精度更高但稍慢">
            <input type="checkbox" id="toggle-rerank" checked />
            <span class="toggle-slider"></span>
            <span>Rerank</span>
          </label>
          <select id="search-limit" class="input" title="返回条数">
            <option value="0" selected>Top-K 默认</option>
            <option value="5">Top 5</option>
            <option value="10">Top 10</option>
            <option value="20">Top 20</option>
          </select>
          <select id="kb-select" class="input" title="知识库">
            <option value="">加载知识库…</option>
          </select>
        </div>
        <div class="hero-history-row" id="history-chips">
          <span class="t-dim">最近：</span>
        </div>
      </div>

      <!-- 横向召回漏斗 + 本次统计（一行收编；数据来自检索响应来源/计数） -->
      <div class="funnel-card glass-card" id="funnel-card" style="display:none;">
        <div class="funnel-h" id="funnel-h"></div>
        <div class="funnel-stats-row" id="funnel-stats"></div>
      </div>

      <!-- 结果区 -->
      <div id="search-results" class="search-results">
        <div class="empty-state">
          <div class="empty-icon">◎</div>
          <div class="empty-title">输入查询开始搜索</div>
          <div class="empty-desc">选择知识库 → 输入问题 → 选择检索模式 → 点击搜索</div>
        </div>
      </div>
    `;

    this.initEvents();
    this._loadHistory();
    await this.loadKnowledgeBases();
    this.updatePipelineHint();
  },

  // ============================================================
  // 事件绑定
  // ============================================================

  initEvents() {
    const queryEl = document.getElementById('search-query');
    queryEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); this.performSearch(); }
    });
    document.querySelectorAll('.mode-btn').forEach(btn => {
      btn.addEventListener('click', () => this.setMode(btn.dataset.mode));
    });
    document.getElementById('toggle-rerank').addEventListener('change', () => this.updatePipelineHint());
    document.getElementById('search-btn').addEventListener('click', () => this.performSearch());
  },

  setMode(mode) {
    document.querySelectorAll('.mode-btn').forEach(btn => {
      const on = btn.dataset.mode === mode;
      btn.classList.toggle('active', on);
      btn.classList.toggle('on', on);
      if (on && mode === 'hybrid') btn.classList.add('accent'); else btn.classList.remove('accent');
    });
    this.updatePipelineHint();
  },

  /** 模式语义提示（轻量保留，漏斗卡承载主要可视化） */
  updatePipelineHint() {
    const modeBtn = document.querySelector('.mode-btn.active');
    this._mode = modeBtn ? modeBtn.dataset.mode : 'vector';
  },

  // ============================================================
  // 知识库
  // ============================================================

  async loadKnowledgeBases() {
    const sel = document.getElementById('kb-select');
    if (!sel) return;
    try {
      const response = await window.KnowledgeBaseAPI.list();
      this.knowledgeBases = response.knowledge_bases || [];
      if (this.knowledgeBases.length === 0) {
        sel.innerHTML = '<option value="">暂无知识库</option>';
        return;
      }
      sel.innerHTML = this.knowledgeBases.map(kb =>
        `<option value="${kb.id}" ${this.selectedKbId === kb.id ? 'selected' : ''}>${this._escapeHtml(kb.kb_name)}</option>`
      ).join('');
      if (!this.selectedKbId) this.selectedKbId = this.knowledgeBases[0].id;
      sel.value = String(this.selectedKbId);
      sel.onchange = () => { this.selectedKbId = parseInt(sel.value); };
    } catch (error) {
      sel.innerHTML = `<option value="">加载失败</option>`;
      window.App.showToast('知识库加载失败: ' + error.message, 'error');
    }
  },

  async refreshKbs() {
    await this.loadKnowledgeBases();
    window.App.showToast('知识库列表已刷新', 'success');
  },

  // ============================================================
  // 执行搜索
  // ============================================================

  async performSearch() {
    const query = document.getElementById('search-query').value.trim();
    if (!query) {
      window.App.showToast('请输入搜索查询', 'error');
      document.getElementById('search-query').focus();
      return;
    }
    if (!this.selectedKbId) {
      window.App.showToast('请先选择一个知识库', 'error');
      return;
    }

    const mode = document.querySelector('.mode-btn.active')?.dataset.mode || 'hybrid';
    const limit = parseInt(document.getElementById('search-limit').value) || null;
    const useRerank = document.getElementById('toggle-rerank').checked;
    const retrievalMode = document.getElementById('vector-strategy').value;

    const startTime = performance.now();

    this.isSearching = true;
    this.lastSearchMeta = { query, mode, limit, useRerank, retrievalMode };
    this._updateResultsUI('loading');

    try {
      let results;
      switch (mode) {
        case 'vector':
          results = await window.SearchAPI.vectorSearch(query, limit, this.selectedKbId, { use_rerank: useRerank, retrieval_mode: retrievalMode });
          break;
        case 'keyword':
          results = await window.SearchAPI.keywordSearch(query, limit, this.selectedKbId, { use_rerank: useRerank });
          break;
        case 'hybrid':
          results = await window.SearchAPI.hybridSearch(query, limit, this.selectedKbId, { use_rerank: useRerank, retrieval_mode: retrievalMode });
          break;
      }

      const latency = Math.round(performance.now() - startTime);
      this.searchResults = results.results || [];
      this.lastSearchMeta.latency = latency;
      this.lastSearchMeta.totalResults = this.searchResults.length;

      this._addToHistory({ query, mode, count: this.searchResults.length, latency });

      this._renderFunnel();
      this._updateResultsUI('results');
    } catch (error) {
      this._updateResultsUI('error', error.message);
    } finally {
      this.isSearching = false;
    }
  },

  // ============================================================
  // 召回漏斗（基础版：来源分层计数 → 横向漏斗条，FAQ/实体/向量分层色）
  // ============================================================

  _layerOf(result) {
    const t = result.type;
    if (t === 'graph' || t === 'entity') return 'entity';
    if (t === 'summary' || t === 'subquestion') return 'vector';
    if (t === 'native' || t === 'chunk') return 'vector';
    if (result.rerank_score != null || t === 'custom') return 'vector'; // ES/融合路结果归向量层兜底
    return 'vector';
  },

  _renderFunnel() {
    const card = document.getElementById('funnel-card');
    const h = document.getElementById('funnel-h');
    const stats = document.getElementById('funnel-stats');
    if (!card || !h) return;
    const m = this.lastSearchMeta;

    // 分层计数（来自结果项 type/来源字段）
    const counts = { faq: 0, entity: 0, vector: 0 };
    this.searchResults.forEach(r => { counts[this._layerOf(r)]++; });
    const total = Math.max(this.searchResults.length, 1);
    const pct = n => (n / total) * 100;

    const layer = (cls, label, n, note, hit = true) => `
      <div class="funnel-layer ${hit ? 'hit' : ''} ${hit ? cls : ''}">
        <div class="row-between"><span class="badge ${hit && cls === 'l-faq' ? 'badge-accent' : hit && cls === 'l-entity' ? 'badge-violet' : hit && cls === 'l-vector' ? 'badge-info' : ''}">${label}</span><span class="fl-count num">${n}</span></div>
        <div class="fl-bar"><i style="width:${Math.max(pct(n), n ? 8 : 0)}%;${hit && cls === 'l-faq' ? 'background:var(--layer-faq)' : hit && cls === 'l-entity' ? 'background:var(--layer-entity)' : hit && cls === 'l-vector' ? 'background:var(--layer-vector)' : ''}"></i></div>
        <span class="fl-note t-dim">${note}</span>
      </div>`;

    h.innerHTML = [
      layer('l-faq', 'FAQ', counts.faq, counts.faq ? 'FAQ 命中' : '未命中', counts.faq > 0),
      `<div class="funnel-arrow">→</div>`,
      layer('l-entity', '实体图谱', counts.entity, counts.entity ? '实体扩展召回' : '未启用/未命中', counts.entity > 0),
      `<div class="funnel-arrow">→</div>`,
      layer('l-vector', m.mode === 'keyword' ? '关键词' : '向量分层', counts.vector, this._vectorLayerNote(), counts.vector > 0),
      `<div class="funnel-arrow">→</div>`,
      layer('l-result', '结果', this.searchResults.length, m.useRerank ? 'LLM Rerank 后' : (m.mode === 'hybrid' ? 'RRF 融合后' : '直接返回'), this.searchResults.length > 0),
    ].join('');

    card.style.display = '';
    stats.innerHTML = `
      <span>耗时 <b class="num">${m.latency || '-'}ms</b></span>
      <span>返回 <b class="num">${m.totalResults || 0}</b> 条</span>
      <span>Rerank <b style="color:${m.useRerank ? 'var(--green)' : 'var(--text3)'}">${m.useRerank ? '开' : '关'}</b></span>
      <span>模式 <b>${{ vector: '向量', keyword: '关键词', hybrid: '混合' }[m.mode] || m.mode}</b></span>
      ${m.retrievalMode && m.mode !== 'keyword' ? `<span>策略 <b>${{ advanced: '摘要+子问题', native: '原文匹配', hybrid: '三路融合' }[m.retrievalMode] || m.retrievalMode}</b></span>` : ''}
    `;
  },

  _vectorLayerNote() {
    const sub = this.searchResults.filter(r => r.type === 'subquestion').length;
    const sum = this.searchResults.filter(r => r.type === 'summary').length;
    const m = this.lastSearchMeta;
    if (m.mode === 'keyword') return 'BM25 关键词召回';
    if (sub || sum) return `摘要 ${sum} · 子问题 ${sub}`;
    return '向量召回';
  },

  // ============================================================
  // 结果 UI 渲染
  // ============================================================

  _updateResultsUI(state, errorMessage = '') {
    const container = document.getElementById('search-results');

    switch (state) {
      case 'loading':
        container.innerHTML = `
          <div class="search-loading">
            <div class="search-loading-spinner"></div>
            <p>正在检索<span class="loading-dots"></span></p>
            <p class="search-loading-sub">${this._getModeLabel()}</p>
          </div>`;
        break;

      case 'results':
        if (this.searchResults.length === 0) {
          container.innerHTML = `
            <div class="empty-state">
              <div class="empty-icon">◎</div>
              <div class="empty-title">未找到相关结果</div>
              <div class="empty-desc">尝试更换检索方式或调整查询词</div>
              <div style="margin-top:12px; display:flex; gap:8px;">
                <button class="btn btn-sm btn-secondary" onclick="SearchPage.switchToVector()">尝试向量检索</button>
                <button class="btn btn-sm btn-secondary" onclick="SearchPage.switchToHybrid()">尝试混合检索</button>
              </div>
            </div>`;
        } else {
          container.innerHTML = `
            <div class="results-header">
              <span class="results-count">
                共 <strong>${this.searchResults.length}</strong> 条结果
                ${this.lastSearchMeta.latency ? `<span class="results-latency">耗时 ${this.lastSearchMeta.latency}ms</span>` : ''}
              </span>
            </div>
            ${this.searchResults.map((result, i) => this._renderResultCard(result, i)).join('')}
          `;
          this._bindResultEvents();
        }
        break;

      case 'error':
        container.innerHTML = `
          <div class="empty-state">
            <div class="empty-icon">✕</div>
            <div class="empty-title">检索失败</div>
            <div class="empty-desc">${this._escapeHtml(errorMessage || '未知错误')}</div>
            <button class="btn btn-secondary" onclick="SearchPage.performSearch()">重试</button>
          </div>`;
        break;
    }
  },

  _renderResultCard(result, index) {
    // 主分：rerank 分数优先，其次 score
    const mainScore = result.rerank_score != null ? result.rerank_score : result.score;
    const score = mainScore != null ? Number(mainScore) : null;
    const content = result.content || '';
    const chunkText = result.chunk_text || '';
    const scoreDisplay = score != null ? (score <= 1 ? score.toFixed(3) : score.toFixed(1)) : '-';

    // RRF 分数小字
    const rrfScore = result.score != null && result.rerank_score != null ? Number(result.score).toFixed(4) : null;

    // 来源徽章（分层色：向量蓝 / 实体紫 / FAQ 金）
    const t = result.type;
    let sourceLabel = '混合', sourceCls = 'badge-info';
    if (t === 'summary') { sourceLabel = '摘要向量'; sourceCls = 'badge-info'; }
    else if (t === 'subquestion') { sourceLabel = '子问题向量'; sourceCls = 'badge-info'; }
    else if (t === 'native') { sourceLabel = '原文向量'; sourceCls = 'badge-info'; }
    else if (t === 'graph' || t === 'entity') { sourceLabel = '实体扩展'; sourceCls = 'badge-violet'; }
    else if (result.rerank_score != null) { sourceLabel = 'reranked'; sourceCls = 'badge-accent'; }
    else if (this.lastSearchMeta.mode === 'keyword') { sourceLabel = 'BM25'; sourceCls = ''; }

    const barPct = score != null ? Math.max(Math.min((score <= 1 ? score : score / 10) * 100, 100), 2) : 0;

    const queryText = document.getElementById('search-query')?.value || '';

    return `
      <div class="result-card glass-card" data-index="${index}">
        <div class="result-card-header">
          <div class="result-left">
            <span class="result-rank num">#${index + 1}</span>
            <span class="badge badge-sm ${sourceCls}">${sourceLabel}</span>
          </div>
          <div class="result-right">
            <span class="result-score-bar"><span class="score-fill" style="width:${barPct}%"></span></span>
            <b class="num">${scoreDisplay}</b>
            ${rrfScore ? `<span class="t-dim num" style="font-size:.7rem;">RRF ${rrfScore}</span>` : ''}
            <button class="result-expand-btn" data-index="${index}" title="展开详情">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <polyline points="6 9 12 15 18 9"/>
              </svg>
            </button>
          </div>
        </div>
        <div class="result-content-preview">
          ${this._highlightQuery(this._truncate(this._escapeHtml(chunkText), 280), queryText)}
        </div>
        <div class="result-detail" id="detail-${index}" style="display:none;">
          <div class="detail-inner">
            <div class="detail-section">
              <span class="detail-label">匹配内容</span>
              <pre class="detail-content-text">${this._escapeHtml(content)}</pre>
            </div>
            <div class="detail-meta-row">
              <span class="detail-tag">RRF分: ${result.score != null ? Number(result.score).toFixed(4) : '—'}</span>
              <span class="detail-tag">Rerank: ${result.rerank_score != null ? Number(result.rerank_score).toFixed(4) : '—'}</span>
              <span class="detail-tag">文档ID: ${result.document_id ?? '—'}</span>
              <span class="detail-tag">Chunk #${result.chunk_index ?? '—'}</span>
            </div>
          </div>
        </div>
      </div>
    `;
  },

  _bindResultEvents() {
    document.querySelectorAll('.result-expand-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.index);
        const detail = document.getElementById(`detail-${idx}`);
        const isExpanded = detail && detail.style.display !== 'none';

        document.querySelectorAll('.result-detail').forEach(d => d.style.display = 'none');
        document.querySelectorAll('.result-expand-btn svg').forEach(s =>
          s.innerHTML = '<polyline points="6 9 12 15 18 9"/>'
        );

        if (!isExpanded && detail) {
          detail.style.display = '';
          btn.querySelector('svg').innerHTML = '<polyline points="18 15 12 9 6 15"/>';
        }
      });
    });
  },

  // ============================================================
  // 辅助方法
  // ============================================================

  highlightQuery(text, query) {
    if (!query || !text) return text;
    try {
      const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(`(${escaped})`, 'gi');
      return text.replace(regex, '<mark>$1</mark>');
    } catch { return text; }
  },

  _highlightQuery(text, query) { return this.highlightQuery(text, query); },
  _escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  },
  _truncate(text, maxLen) {
    if (!text) return '';
    return text.length > maxLen ? text.slice(0, maxLen) + '…' : text;
  },
  _getModeLabel() {
    const mode = document.querySelector('.mode-btn.active')?.dataset.mode || 'hybrid';
    const labels = { vector: '向量语义检索中…', keyword: '关键词检索中…', hybrid: '混合检索（向量+关键词）中…' };
    return labels[mode] || '检索中…';
  },
  _getModeShort(mode) {
    const map = { vector: '向量', keyword: 'BM25', hybrid: '混合' };
    return map[mode] || mode;
  },
  switchToVector() {
    this.setMode('vector');
    this.performSearch();
  },
  switchToHybrid() {
    this.setMode('hybrid');
    this.performSearch();
  },

  // ============================================================
  // 搜索历史（chips：点击即重搜）
  // ============================================================

  _loadHistory() {
    try {
      this.searchHistory = JSON.parse(localStorage.getItem('rag_search_history') || '[]');
    } catch { this.searchHistory = []; }
    this._renderHistory();
  },

  _addToHistory(entry) {
    // 去重：相同 query 只保留最新
    this.searchHistory = this.searchHistory.filter(h => h.query !== entry.query);
    this.searchHistory.unshift({ ...entry, ts: Date.now() });
    if (this.searchHistory.length > 5) this.searchHistory.length = 5;
    try {
      localStorage.setItem('rag_search_history', JSON.stringify(this.searchHistory));
    } catch {}
    this._renderHistory();
  },

  clearHistory() {
    this.searchHistory = [];
    localStorage.removeItem('rag_search_history');
    this._renderHistory();
    window.App.showToast('搜索历史已清空', 'success');
  },

  _renderHistory() {
    const row = document.getElementById('history-chips');
    if (!row) return;
    const chips = this.searchHistory.slice(0, 5).map((item, idx) =>
      `<span class="src-chip" data-history-idx="${idx}" title="${this._escapeHtml(item.query)}">${this._escapeHtml(this._truncate(item.query, 24))}</span>`
    ).join('');
    row.innerHTML = `<span class="t-dim">最近：</span>${chips || '<span class="t-dim">暂无</span>'}
      ${this.searchHistory.length ? '<button class="btn-link" id="clear-history-btn" style="margin-left:auto;">清空</button>' : ''}`;
    row.querySelectorAll('.src-chip[data-history-idx]').forEach(el => {
      el.addEventListener('click', () => {
        const item = this.searchHistory[parseInt(el.dataset.historyIdx, 10)];
        if (item) this.replayHistory(item.query, item.mode);
      });
    });
    const clearBtn = document.getElementById('clear-history-btn');
    if (clearBtn) clearBtn.addEventListener('click', () => this.clearHistory());
  },

  replayHistory(query, mode) {
    const qEl = document.getElementById('search-query');
    if (qEl) qEl.value = query;
    this.setMode(mode);
    this.performSearch();
  },
};

window.SearchPage = SearchPage;
