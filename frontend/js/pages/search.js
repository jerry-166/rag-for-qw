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
      <div class="glass" style="padding:var(--sp-5) var(--sp-6)">
        <div class="row">
          <input class="input grow" id="search-query" style="height:50px;font-size:var(--fs-lg);border-radius:var(--r-md);padding-left:var(--sp-5)"
            placeholder="搜索知识库…  例如：RAG 系统包含哪些阶段" />
          <button class="btn btn-primary" id="search-btn" style="height:50px;padding:0 var(--sp-6);border-radius:var(--r-md)">搜索</button>
        </div>
        <div class="row wrap mt4" style="gap:var(--sp-3)">
          <div class="seg" role="radiogroup" aria-label="检索模式">
            <button class="mode-btn on" data-mode="vector">向量<span class="t3" style="font-size:var(--fs-xs)"> 语义</span></button>
            <button class="mode-btn" data-mode="keyword">关键词<span class="t3" style="font-size:var(--fs-xs)"> BM25</span></button>
            <button class="mode-btn" data-mode="hybrid">混合<span style="font-size:var(--fs-xs)"> RRF+Rerank</span></button>
          </div>
          <select id="vector-strategy" class="select" style="width:170px;height:32px" title="向量检索策略">
            <option value="advanced" selected>策略：摘要+子问题</option>
            <option value="native">策略：原文匹配</option>
            <option value="hybrid">策略：三路融合</option>
          </select>
          <label class="row" style="gap:6px;font-size:var(--fs-sm);color:var(--text-2)" title="启用后对召回结果进行精排，精度更高但稍慢">
            <input type="checkbox" id="toggle-rerank" checked />
            <span>Rerank</span>
          </label>
          <select id="search-limit" class="select" style="width:120px;height:32px" title="返回条数">
            <option value="0" selected>Top-K 默认</option>
            <option value="5">Top 5</option>
            <option value="10">Top 10</option>
            <option value="20">Top 20</option>
          </select>
          <select id="kb-select" class="select" style="width:170px;height:32px" title="知识库">
            <option value="">加载知识库…</option>
          </select>
        </div>
        <div class="row wrap mt4" id="history-chips" style="gap:6px">
          <span class="t3" style="font-size:var(--fs-xs)">最近：</span>
        </div>
      </div>

      <div class="glass p4 mb4" id="funnel-card" style="display:none">
        <div class="funnel-h" id="funnel-h"></div>
        <div class="row mt4" id="funnel-stats" style="gap:var(--sp-5);padding:0 var(--sp-2)"></div>
      </div>

      <div id="search-results" class="col">
        <div class="glass"><div class="state">
          <div class="glyph">◎</div>
          <div class="title">输入查询开始搜索</div>
          <div class="desc">选择知识库 → 输入问题 → 选择检索模式 → 点击搜索</div>
        </div></div>
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
      btn.classList.toggle('on', on);
      btn.classList.toggle('accent', on && mode === 'hybrid');
    });
    this.updatePipelineHint();
  },

  /** 模式语义提示（轻量保留，漏斗卡承载主要可视化） */
  updatePipelineHint() {
    const modeBtn = document.querySelector('.mode-btn.on');
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

    const mode = document.querySelector('.mode-btn.on')?.dataset.mode || 'hybrid';
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

    const layer = (cls, label, n, note, hit = true) => {
      const badgeCls = cls === 'l-faq' ? 'accent' : cls === 'l-entity' ? 'violet' : cls === 'l-vector' ? 'info' : '';
      const barColor = cls === 'l-faq' ? 'var(--layer-faq)' : cls === 'l-entity' ? 'var(--layer-entity)' : cls === 'l-vector' ? 'var(--layer-vector)' : 'var(--glass-3-bg)';
      return `
      <div class="funnel-layer ${hit ? 'hit ' + cls : ''}">
        <div class="row between" style="width:100%"><span class="badge ${hit ? badgeCls : ''}">${label}</span><span class="fl-count num" style="font-size:var(--fs-xl);font-weight:640">${n}</span></div>
        <div class="fl-bar"><i style="width:${Math.max(pct(n), n ? 8 : 0)}%;background:${hit ? barColor : 'var(--glass-3-bg)'}"></i></div>
        <span class="t3" style="font-size:var(--fs-xs)">${note}</span>
      </div>`;
    };

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
      <span class="t3" style="font-size:var(--fs-xs)">耗时 <b class="num" style="color:var(--text-1)">${m.latency || '-'}ms</b></span>
      <span class="t3" style="font-size:var(--fs-xs)">返回 <b class="num" style="color:var(--text-1)">${m.totalResults || 0}</b> 条</span>
      <span class="t3" style="font-size:var(--fs-xs)">Rerank <b style="color:${m.useRerank ? 'var(--ok)' : 'var(--text3)'}">${m.useRerank ? '开' : '关'}</b></span>
      <span class="t3" style="font-size:var(--fs-xs)">模式 <b style="color:var(--text-1)">${{ vector: '向量', keyword: '关键词', hybrid: '混合' }[m.mode] || m.mode}</b></span>
      ${m.retrievalMode && m.mode !== 'keyword' ? `<span class="t3" style="font-size:var(--fs-xs)">策略 <b style="color:var(--text-1)">${{ advanced: '摘要+子问题', native: '原文匹配', hybrid: '三路融合' }[m.retrievalMode] || m.retrievalMode}</b></span>` : ''}
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
          <div class="glass"><div class="state">
            <div class="glyph float-anim">◎</div>
            <div class="title">正在检索</div>
            <p class="desc">${this._getModeLabel()}</p>
            <div class="progress indeterminate" style="width:120px;margin-top:8px"><i></i></div>
          </div></div>`;
        break;

      case 'results':
        if (this.searchResults.length === 0) {
          container.innerHTML = `
            <div class="glass"><div class="state">
              <div class="glyph">◎</div>
              <div class="title">未找到相关结果</div>
              <div class="desc">尝试更换检索方式或调整查询词</div>
              <div class="row" style="margin-top:12px;gap:8px">
                <button class="btn btn-sm" onclick="SearchPage.switchToVector()">尝试向量检索</button>
                <button class="btn btn-sm btn-primary" onclick="SearchPage.switchToHybrid()">尝试混合检索</button>
              </div>
            </div></div>`;
        } else {
          container.innerHTML = `
            <div class="row between mb4">
              <span class="t2" style="font-size:var(--fs-sm)">共 <b class="num">${this.searchResults.length}</b> 条结果${this.lastSearchMeta.latency ? `<span class="t3 num" style="font-size:var(--fs-xs)"> · 耗时 ${this.lastSearchMeta.latency}ms</span>` : ''}</span>
              <span class="t3" style="font-size:var(--fs-xs)">按 Rerank 分数排序</span>
            </div>
            ${this.searchResults.map((result, i) => this._renderResultCard(result, i)).join('')}
          `;
          this._bindResultEvents();
        }
        break;

      case 'error':
        container.innerHTML = `
          <div class="glass"><div class="state">
            <div class="glyph" style="color:var(--danger)">✕</div>
            <div class="title">检索失败</div>
            <div class="desc">${this._escapeHtml(errorMessage || '未知错误')}</div>
            <button class="btn btn-sm" onclick="SearchPage.performSearch()">重试</button>
          </div></div>`;
        break;
    }
  },

  _renderResultCard(result, index) {
    // 主分：rerank 分数优先，其次 score
    const mainScore = result.rerank_score != null ? result.rerank_score : result.score;
    const score = mainScore != null ? Number(mainScore) : null;
    // 字段语义（按 type 选择，非降级 fallback）：
    //   - summary/subquestion：chunk_text=原文，content=增强内容(摘要/子问题)
    //   - native：chunk_text=原文，content=原文（等价）
    //   - graph：仅 chunk_text=原文
    //   - 关键词/BM25、hybrid(PG 补全)：仅 content=原文（无 chunk_text）
    const rawText = result.chunk_text || result.content || '';   // 原文兜底（graph 仅 chunk_text，BM25 仅 content）
    const enhancedText = (result.type === 'summary' || result.type === 'subquestion')
        ? (result.content || '')
        : '';
    // 卡片正文：摘要/子问题优先展示增强内容，否则展示原文
    const chunkText = enhancedText || rawText;
    const scoreDisplay = score != null ? (score <= 1 ? score.toFixed(3) : score.toFixed(1)) : '-';

    // RRF 分数小字
    const rrfScore = result.score != null && result.rerank_score != null ? Number(result.score).toFixed(4) : null;

    // 来源徽章（分层色：向量蓝 / 实体紫 / FAQ 金）
    const t = result.type;
    let sourceLabel = '混合', sourceCls = 'badge-info';
    if (t === 'summary') { sourceLabel = '摘要'; sourceCls = 'badge-info'; }
    else if (t === 'subquestion') { sourceLabel = '子问题'; sourceCls = 'badge-info'; }
    else if (t === 'native') { sourceLabel = '原文'; sourceCls = 'badge-info'; }
    else if (t === 'graph' || t === 'entity') { sourceLabel = '实体扩展'; sourceCls = 'badge-violet'; }
    else if (this.lastSearchMeta.mode === 'keyword') { sourceLabel = 'BM25'; sourceCls = ''; }
    else if (result.rerank_score != null) { sourceLabel = 'reranked'; sourceCls = 'badge accent'; }

    const barPct = score != null ? Math.max(Math.min((score <= 1 ? score : score / 10) * 100, 100), 2) : 0;

    const queryText = document.getElementById('search-query')?.value || '';

    return `
      <div class="glass card card-hover result-card" data-index="${index}">
        <div class="row between">
          <div class="row" style="gap:6px">
            <b class="num" style="color:var(--accent);font-size:var(--fs-sm)">#${index + 1}</b>
            <span class="badge ${sourceCls}">${sourceLabel}</span>
          </div>
          <div class="row">
            <span class="score-bar" style="width:90px;height:5px;border-radius:3px;background:var(--glass-3-bg);overflow:hidden;display:inline-block"><span style="display:block;height:100%;width:${barPct}%;background:var(--accent);border-radius:3px"></span></span>
            <b class="num" style="font-size:var(--fs-sm)">${scoreDisplay}</b>
            ${rrfScore ? `<span class="t3 num" style="font-size:var(--fs-xs)">RRF ${rrfScore}</span>` : ''}
            <button class="icon-btn result-expand-btn" data-index="${index}" title="展开详情">▾</button>
          </div>
        </div>
        <p class="mt4" style="font-size:var(--fs-sm);color:var(--text-2)">${this._highlightQuery(this._truncate(this._escapeHtml(chunkText), 280), queryText)}</p>
        <div class="result-detail" id="detail-${index}" style="display:none">
          <div class="col mt4" style="gap:var(--sp-3)">
            ${enhancedText ? `<div>
              <div class="label-caps mb4">${sourceLabel}</div>
              <pre class="mono t2" style="font-size:var(--fs-xs);white-space:pre-wrap;padding:var(--sp-3);background:var(--glass-1-bg);border-radius:var(--r-sm);max-height:240px;overflow:auto">${this._escapeHtml(enhancedText)}</pre>
            </div>` : ''}
            ${rawText ? `<div>
              <div class="label-caps mb4">原文内容</div>
              <pre class="mono t2" style="font-size:var(--fs-xs);white-space:pre-wrap;padding:var(--sp-3);background:var(--glass-1-bg);border-radius:var(--r-sm);max-height:240px;overflow:auto">${this._escapeHtml(rawText)}</pre>
            </div>` : ''}
            <div class="row wrap" style="gap:6px">
              <span class="badge">RRF: ${result.score != null ? Number(result.score).toFixed(4) : '—'}</span>
              <span class="badge">Rerank: ${result.rerank_score != null ? Number(result.rerank_score).toFixed(4) : '—'}</span>
              <span class="badge">文档 ${result.document_id ?? '—'}</span>
              <span class="badge">Chunk #${result.chunk_index ?? '—'}</span>
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
        document.querySelectorAll('.result-expand-btn').forEach(b => b.textContent = '▾');

        if (!isExpanded && detail) {
          detail.style.display = '';
          btn.textContent = '▴';
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
    const mode = document.querySelector('.mode-btn.on')?.dataset.mode || 'hybrid';
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
    row.innerHTML = `<span class="t3" style="font-size:var(--fs-xs)">最近：</span>${chips || '<span class="t3" style="font-size:var(--fs-xs)">暂无</span>'}
      ${this.searchHistory.length ? '<button class="btn btn-sm btn-ghost" id="clear-history-btn" style="margin-left:auto;">清空</button>' : ''}`;
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
