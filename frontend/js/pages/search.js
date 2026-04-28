/**
 * 知识检索页面 — 增强版
 *
 * 功能:
 *  - 三种检索模式（向量/关键词/混合）+ Rerank 开关
 *  - 检索流水线可视化（召回 → RRF融合 → Rerank精排）
 *  - 搜索历史（localStorage 持久化）
 *  - 结果卡片展开详情、来源标签、分数可视化
 */

const SearchPage = {
  selectedKbId: null,
  knowledgeBases: [],
  searchResults: [],
  isSearching: false,
  lastSearchMeta: {},   // 上次搜索元信息
  searchHistory: [],    // 搜索历史

  // ============================================================
  // 渲染入口
  // ============================================================

  async render() {
    const container = document.getElementById('page-container');
    container.innerHTML = `
      <div class="page-header">
        <div>
          <h1 class="page-title">知识检索</h1>
          <p class="page-desc">混合向量检索 + 关键词检索，支持多路召回融合与智能重排</p>
        </div>
        <div style="display:flex; gap:8px;">
          <button class="btn btn-secondary" onclick="SearchPage.clearHistory()">
            🗑️ 清空历史
          </button>
          <button class="btn btn-primary" onclick="SearchPage.refreshKbs()">
            🔄 刷新知识库
          </button>
        </div>
      </div>

      <div class="search-page-layout">
        <!-- 左侧：搜索区域 + 结果 -->
        <div style="flex:1; display:flex; flex-direction:column; gap:16px;">
          <!-- 搜索输入卡片 -->
          <div class="search-input-card">
            <div class="search-bar">
              <div class="form-field" style="flex:1;">
                <label>搜索查询</label>
                <textarea id="search-query"
                  placeholder="输入您的问题，例如：&quot;什么是RAG系统？&quot;"
                  rows="3"></textarea>
              </div>
              <button class="btn btn-primary btn-lg" style="align-self:flex-end;" onclick="SearchPage.performSearch()" id="search-btn">
                🔍 搜索
              </button>
            </div>

            <!-- 搜索模式 & 设置 -->
            <div class="search-options-row">
              <!-- 检索模式 -->
              <div class="search-mode-group" role="radiogroup" aria-label="检索模式">
                <button class="mode-btn active" data-mode="vector" onclick="SearchPage.setMode('vector')">
                  <span class="mode-icon">🧠</span>
                  <span class="mode-label">向量</span>
                  <span class="mode-desc">语义匹配</span>
                </button>
                <button class="mode-btn" data-mode="keyword" onclick="SearchPage.setMode('keyword')">
                  <span class="mode-icon">🔤</span>
                  <span class="mode-label">关键词</span>
                  <span class="mode-desc">BM25</span>
                </button>
                <button class="mode-btn" data-mode="hybrid" onclick="SearchPage.setMode('hybrid')">
                  <span class="mode-icon">⚡</span>
                  <span class="mode-label">混合</span>
                  <span class="mode-desc">RRF+Rerank</span>
                </button>
              </div>

              <!-- 向量检索策略 -->
              <div class="search-vector-strategy">
                <span class="strategy-label">向量策略:</span>
                <select id="vector-strategy" style="width:auto;">
                  <option value="advanced" selected>摘要+子问题</option>
                  <option value="native">原文匹配</option>
                  <option value="hybrid">三路融合</option>
                </select>
              </div>

              <!-- 快捷设置 -->
              <div class="search-quick-settings">
                <label class="toggle-switch" title="启用后会对召回结果进行 LLM/CrossEncoder 重排序，精度更高但稍慢">
                  <input type="checkbox" id="toggle-rerank" checked />
                  <span class="toggle-slider"></span>
                  <span>Rerank 精排</span>
                </label>
                <select id="search-limit" style="width:auto; min-width:60px;">
                  <option value="5">Top 5</option>
                  <option value="10">Top 10</option>
                  <option value="20">Top 20</option>
                </select>
              </div>
            </div>

            <!-- 检索流水线提示 -->
            <div class="pipeline-hint" id="pipeline-hint">
              <span class="pipeline-step-badge vector">向量检索</span>
              <span class="pipeline-step-badge keyword" style="display:none;">关键词检索</span>
              <span class="pipeline-step-badge fusion" style="display:none;">RRF 融合</span>
              <span class="pipeline-step-badge rerank">LLM Rerank</span>
              <span class="pipeline-step-badge result">结果</span>
            </div>
          </div>



          <!-- 结果区 -->
          <div id="search-results" class="search-results">
            <div class="empty-state">
              <div class="empty-icon">🔍</div>
              <div class="empty-title">输入查询开始搜索</div>
              <div class="empty-desc">选择知识库 → 输入问题 → 选择检索模式 → 点击搜索</div>
            </div>
          </div>
        </div>

        <!-- 右侧：知识库选择 -->
        <div class="search-sidebar">
          <div class="card">
            <div class="card-header">
              <div class="card-title">📚 知识库</div>
            </div>
            <div class="card-body" id="kb-selector">
              <div style="padding:16px; text-align:center; color:var(--text3);">加载中...</div>
            </div>
          </div>

          <!-- 最近搜索 -->
          <div class="card" style="margin-top:16px;" id="search-history-card">
            <div class="card-header">
              <div class="card-title">🕐 最近搜索</div>
            </div>
            <div class="card-body" id="history-list"></div>
          </div>

          <!-- 搜索统计 -->
          <div class="card" style="margin-top:16px;" id="search-stats-card" style="display:none;">
            <div class="card-header"><div class="card-title">📊 本次检索</div></div>
            <div class="card-body" id="search-stats-body"></div>
          </div>
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

    // Ctrl+Enter / Cmd+Enter 触发搜索
    queryEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        this.performSearch();
      }
    });
  },

  setMode(mode) {
    document.querySelectorAll('.mode-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.mode === mode);
    });
    this.updatePipelineHint();
  },

  updatePipelineHint() {
    const modeBtn = document.querySelector('.mode-btn.active');
    const mode = modeBtn ? modeBtn.dataset.mode : 'vector';
    const rerankOn = document.getElementById('toggle-rerank').checked;

    const hint = document.getElementById('pipeline-hint');
    if (!hint) return;

    const vectorBadge = hint.querySelector('.vector');
    const keywordBadge = hint.querySelector('.keyword');
    const fusionBadge = hint.querySelector('.fusion');
    const rerankBadge = hint.querySelector('.rerank');
    const arrows = hint.querySelectorAll('.pipeline-arrow');

    // 隐藏所有箭头
    arrows.forEach(el => el.style.display = 'none');

    // 根据模式显示不同步骤
    if (mode === 'vector') {
      // 向量检索模式
      vectorBadge.style.display = '';
      keywordBadge.style.display = 'none';
      fusionBadge.style.display = 'none';
      
      // 显示第一个箭头（向量 → rerank）
      if (arrows[0]) arrows[0].style.display = '';
      
      // 隐藏第二个箭头
      if (arrows[1]) arrows[1].style.display = 'none';
    } else if (mode === 'keyword') {
      // 关键词检索模式
      vectorBadge.style.display = 'none';
      keywordBadge.style.display = '';
      fusionBadge.style.display = 'none';
      
      // 显示第一个箭头（关键词 → rerank）
      if (arrows[0]) arrows[0].style.display = '';
      
      // 隐藏第二个箭头
      if (arrows[1]) arrows[1].style.display = 'none';
    } else if (mode === 'hybrid') {
      // 混合检索模式
      vectorBadge.style.display = '';
      keywordBadge.style.display = '';
      fusionBadge.style.display = '';
      
      // 显示所有箭头
      arrows.forEach(el => el.style.display = '');
    }

    // Rerank 步骤
    if (rerankOn) {
      rerankBadge.style.display = '';
      rerankBadge.textContent = 'LLM Rerank';
      rerankBadge.className = 'pipeline-step-badge rerank';
    } else {
      rerankBadge.style.display = '';
      rerankBadge.textContent = '直接返回';
      rerankBadge.className = 'pipeline-step-badge skipped';
    }
  },

  // ============================================================
  // 知识库
  // ============================================================

  async loadKnowledgeBases() {
    const kbSelector = document.getElementById('kb-selector');
    try {
      const response = await window.KnowledgeBaseAPI.list();
      this.knowledgeBases = response.knowledge_bases || [];

      if (this.knowledgeBases.length === 0) {
        kbSelector.innerHTML = `
          <div class="empty-state" style="padding:24px 12px;">
            <div class="empty-icon" style="font-size:2rem;">🗂️</div>
            <div class="empty-title" style="font-size:.88rem;">暂无知识库</div>
            <div class="empty-desc" style="font-size:.78rem;">请先创建知识库并上传文档</div>
          </div>`;
        return;
      }

      kbSelector.innerHTML = this.knowledgeBases.map(kb => `
        <div class="kb-selector-item ${this.selectedKbId === kb.id ? 'active' : ''}"
             data-kb-id="${kb.id}" onclick="SearchPage.selectKnowledgeBase(${kb.id})">
          <span class="kb-sel-icon">📚</span>
          <div class="kb-sel-info">
            <span class="kb-sel-name">${this._escapeHtml(kb.kb_name)}</span>
            ${kb.description ? `<span class="kb-sel-desc">${this._escapeHtml(kb.description)}</span>` : ''}
          </div>
        </div>
      `).join('');

      if (this.knowledgeBases.length > 0 && !this.selectedKbId) {
        this.selectKnowledgeBase(this.knowledgeBases[0].id);
      }
    } catch (error) {
      kbSelector.innerHTML = `
        <div style="padding:16px; text-align:center; color:var(--red);">
          加载失败: ${this._escapeHtml(error.message)}
          <br><button class="btn btn-sm btn-secondary" style="margin-top:8px;" onclick="SearchPage.loadKnowledgeBables()">重试</button>
        </div>`;
    }
  },

  selectKnowledgeBase(kbId) {
    this.selectedKbId = kbId;
    document.querySelectorAll('.kb-selector-item').forEach(item => {
      item.classList.toggle('active', parseInt(item.dataset.kbId) === kbId);
    });
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
    const limit = parseInt(document.getElementById('search-limit').value) || 5;
    const useRerank = document.getElementById('toggle-rerank').checked;
    const retrievalMode = document.getElementById('vector-strategy').value;

    // 记录搜索开始时间
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

      // 记录到搜索历史
      this._addToHistory({ query, mode, count: this.searchResults.length, latency });

      this._updateResultsUI('results');
      this._renderStats();
    } catch (error) {
      this._updateResultsUI('error', error.message);
    } finally {
      this.isSearching = false;
    }
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
              <div class="empty-icon">🔍</div>
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
          // 绑定展开事件
          this._bindResultEvents();
        }
        break;

      case 'error':
        container.innerHTML = `
          <div class="empty-state">
            <div class="empty-icon">❌</div>
            <div class="empty-title">检索失败</div>
            <div class="empty-desc">${this._escapeHtml(errorMessage || '未知错误')}</div>
            <button class="btn btn-secondary" onclick="SearchPage.performSearch()">重试</button>
          </div>`;
        break;
    }
  },

  _renderResultCard(result, index) {
    const score = result.score ?? result.rerank_score ?? null;
    const content = result.content || '';
    const chunkText = result.chunk_text || '';
    const scoreDisplay = score != null ? this._formatScore(score) : '-';
    const scoreClass = score != null ? this._getScoreClass(score) : '';

    // 来源标签
    const sourceType = result.type || '';
    let sourceLabel = '知识库';
    let sourceTagClass = 'source-default';
    if (sourceType === 'summary') { sourceLabel = '摘要向量'; sourceTagClass = 'source-summary'; }
    else if (sourceType === 'subquestion') { sourceLabel = '子问题向量'; sourceTagClass = 'source-subq'; }
    else if (result.score && !result.rerank_score) { sourceLabel = 'ES关键词'; sourceTagClass = 'source-es'; }

    // RRF 分数 vs Rerank 分数
    const rrfScore = result.score != null ? parseFloat(result.score).toFixed(4) : null;
    const rerankScore = result.rerank_score != null ? result.rerank_score.toFixed(4) : null;

    const queryText = document.getElementById('search-query')?.value || '';

    return `
      <div class="result-card" data-index="${index}">
        <div class="result-card-header">
          <div class="result-left">
            <span class="result-rank">#${index + 1}</span>
            <span class="badge badge-sm ${sourceTagClass}">${sourceLabel}</span>
            <span class="result-score-bar ${scoreClass}">
              <span class="score-fill" style="width:${Math.min((score || 0) * 100, 100)}%"></span>
              <span class="score-text">${scoreDisplay}</span>
            </span>
          </div>
          <button class="result-expand-btn" data-index="${index}" title="展开详情">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </button>
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
              <span class="detail-tag">RRF分: ${rrfScore}</span>
              <span class="detail-tag">Rerank: ${rerankScore}</span>
              <span class="detail-tag">文档ID: ${result.document_id}</span>
              <span class="detail-tag">Chunk #${result.chunk_index}</span>
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
        
        // 收起所有其他
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

  _renderStats() {
    const card = document.getElementById('search-stats-card');
    const body = document.getElementById('search-stats-body');
    if (!card || !body) return;

    card.style.display = '';
    const m = this.lastSearchMeta;
    body.innerHTML = `
      <div class="stats-grid-mini">
        <div class="stats-mini-item">
          <span class="stats-mini-val">${m.totalResults || 0}</span>
          <span class="stats-mini-label">返回条数</span>
        </div>
        <div class="stats-mini-item">
          <span class="stats-mini-val">${m.latency || '-'}<small>ms</small></span>
          <span class="stats-mini-label">检索耗时</span>
        </div>
        <div class="stats-mini-item">
          <span class="stats-mini-val">${m.useRerank ? '✅' : '❌️'}</span>
          <span class="stats-mini-label">Rerank</span>
        </div>
        <div class="stats-mini-item">
          <span class="stats-mini-val mode-badge-${m.mode}">${this._getModeShort(m.mode)}</span>
          <span class="stats-mini-label">检索模式</span>
        </div>
      </div>
    `;
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
  _formatScore(score) {
    if (typeof score === 'number') {
      if (score <= 1) return (score * 100).toFixed(1) + '%';
      return score.toFixed(1);
    }
    return score;
  },
  _getScoreClass(score) {
    if (score == null) return '';
    if (score >= 0.8) return 'score-high';
    if (score >= 0.4) return 'score-mid';
    return 'score-low';
  },
  _getModeLabel() {
    const mode = document.querySelector('.mode-btn.active')?.dataset.mode || 'hybrid';
    const labels = { vector: '向量语义检索中…', keyword: '关键词检索中…', hybrid: '混合检索（向量+关键词）中…' };
    return labels[mode] || '检索中…';
  },
  _getModeShort(mode) {
    const map = { vector: '向量', keyword: 'ES', hybrid: '混合' };
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
  // 搜索历史
  // ============================================================

  _loadHistory() {
    try {
      this.searchHistory = JSON.parse(localStorage.getItem('rag_search_history') || '[]');
    } catch { this.searchHistory = []; }
    this._renderHistory();
  },

  _addToHistory(entry) {
    this.searchHistory.unshift({
      ...entry,
      ts: Date.now(),
    });
    // 保留最近 5 条
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
    const list = document.getElementById('history-list');
    if (!list) return;

    if (this.searchHistory.length === 0) {
      list.innerHTML = '<div style="padding:12px; text-align:center; color:var(--text3);">暂无搜索历史</div>';
      return;
    }

    list.innerHTML = this.searchHistory.slice(0, 5).map(item => `
      <div class="history-item" onclick="SearchPage.replayHistory('${this._escapeHtml(item.query).replace(/'/g, "\'")}', '${item.mode}')">
        <span class="history-q">${this._escapeHtml(this._truncate(item.query, 50))}</span>
        <span class="history-meta">
          <span class="badge badge-sm mode-badge-${item.mode}">${this._getModeShort(item.mode)}</span>
          <span>${item.count} 条</span>
          <span>${item.latency}ms</span>
        </span>
      </div>
    `).join('');
  },

  replayHistory(query, mode) {
    const qEl = document.getElementById('search-query');
    if (qEl) qEl.value = query;
    this.setMode(mode);
    this.performSearch();
  },
};

window.SearchPage = SearchPage;
