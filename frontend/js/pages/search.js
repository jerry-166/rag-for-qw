/**
 * 知识检索页面
 */
const SearchPage = {
  selectedKbId: null,
  knowledgeBases: [],
  searchResults: [],
  isSearching: false,
  
  async render() {
    const container = document.getElementById('page-container');
    container.innerHTML = `
      <div class="page-header">
        <div>
          <h1 class="page-title">知识检索</h1>
          <p class="page-desc">通过向量搜索查询知识库中的内容</p>
        </div>
        <button class="btn btn-primary" onclick="SearchPage.refreshKbs()">
          <span>🔄 刷新知识库</span>
        </button>
      </div>
      
      <div class="search-page-layout">
        <!-- 左侧搜索区域 -->
        <div style="flex: 1;">
          <div class="search-input-card">
            <div class="search-bar">
              <div class="form-field" style="flex: 1;">
                <label>搜索查询</label>
                <textarea id="search-query" placeholder="输入您的查询..." rows="3"></textarea>
              </div>
              <button class="btn btn-primary" style="align-self: flex-end;" onclick="SearchPage.performSearch()">
                🔍 搜索
              </button>
            </div>
            
            <div class="search-options">
              <div class="search-option-item">
                <input type="radio" id="search-vector" name="search-type" value="vector" checked />
                <label for="search-vector">向量搜索</label>
              </div>
              <div class="search-option-item">
                <input type="radio" id="search-keyword" name="search-type" value="keyword" />
                <label for="search-keyword">关键词搜索</label>
              </div>
              <div class="search-option-item">
                <input type="radio" id="search-hybrid" name="search-type" value="hybrid" />
                <label for="search-hybrid">混合搜索</label>
              </div>
            </div>
          </div>
          
          <div id="search-results" class="search-results">
            <!-- 搜索结果将在这里渲染 -->
            <div class="empty-state">
              <div class="empty-icon">🔍</div>
              <div class="empty-title">输入查询开始搜索</div>
              <div class="empty-desc">在上方输入框中输入您的查询，选择搜索类型后点击搜索按钮</div>
            </div>
          </div>
        </div>
        
        <!-- 右侧知识库选择 -->
        <div class="search-sidebar">
          <div class="card">
            <div class="card-header">
              <div class="card-title">选择知识库</div>
            </div>
            <div class="card-body" id="kb-selector">
              <!-- 知识库列表将在这里渲染 -->
              <div style="padding: 16px; text-align: center; color: var(--text3);">加载中...</div>
            </div>
          </div>
          
          <div class="card" style="margin-top: 16px;">
            <div class="card-header">
              <div class="card-title">搜索设置</div>
            </div>
            <div class="card-body">
              <div class="form-field">
                <label>结果数量</label>
                <select id="search-limit">
                  <option value="5">5</option>
                  <option value="10">10</option>
                  <option value="20">20</option>
                </select>
              </div>
              <div class="form-field" style="margin-top: 12px;">
                <label>相似度阈值</label>
                <input type="range" id="similarity-threshold" min="0" max="1" step="0.1" value="0.5" />
                <div style="display: flex; justify-content: space-between; font-size: .75rem; color: var(--text3); margin-top: 4px;">
                  <span>0.0</span>
                  <span id="threshold-value">0.5</span>
                  <span>1.0</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
    
    // 初始化事件
    this.initEvents();
    
    // 加载知识库列表
    await this.loadKnowledgeBases();
  },

  initEvents() {
    // 搜索按钮
    document.getElementById('search-query').addEventListener('keypress', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        this.performSearch();
      }
    });
    
    // 相似度阈值滑块
    const thresholdSlider = document.getElementById('similarity-threshold');
    const thresholdValue = document.getElementById('threshold-value');
    thresholdSlider.addEventListener('input', () => {
      thresholdValue.textContent = thresholdSlider.value;
    });
  },

  async loadKnowledgeBases() {
    const kbSelector = document.getElementById('kb-selector');
    try {
      const response = await window.KnowledgeBaseAPI.list();
      this.knowledgeBases = response.knowledge_bases || [];
      
      if (this.knowledgeBases.length === 0) {
        kbSelector.innerHTML = `
          <div class="empty-state">
            <div class="empty-icon">🗂️</div>
            <div class="empty-title">暂无知识库</div>
            <div class="empty-desc">请先创建知识库并上传文档</div>
          </div>
        `;
        return;
      }
      
      kbSelector.innerHTML = this.knowledgeBases.map(kb => `
        <div class="kb-selector-item ${this.selectedKbId === kb.id ? 'active' : ''}" onclick="SearchPage.selectKnowledgeBase(${kb.id})">
          <span class="kb-sel-icon">📚</span>
          <span class="kb-sel-name">${kb.kb_name}</span>
          <span class="kb-sel-desc" style="font-size: .75rem; color: var(--text3);">${kb.description || '无描述'}</span>
        </div>
      `).join('');
      
      // 默认选择第一个知识库
      if (this.knowledgeBases.length > 0 && !this.selectedKbId) {
        this.selectedKbId = this.knowledgeBases[0].id;
        this.selectKnowledgeBase(this.selectedKbId);
      }
    } catch (error) {
      kbSelector.innerHTML = `
        <div style="padding: 16px; text-align: center; color: var(--red);">
          加载失败: ${error.message}
          <button class="btn btn-sm btn-secondary" style="margin-top: 8px;" onclick="SearchPage.loadKnowledgeBases()">
            重新加载
          </button>
        </div>
      `;
    }
  },

  selectKnowledgeBase(kbId) {
    this.selectedKbId = kbId;
    document.querySelectorAll('.kb-selector-item').forEach(item => {
      item.classList.remove('active');
    });
    document.querySelector(`.kb-selector-item[onclick="SearchPage.selectKnowledgeBase(${kbId})"]`).classList.add('active');
  },

  async performSearch() {
    const query = document.getElementById('search-query').value.trim();
    if (!query) {
      window.App.showToast('请输入搜索查询', 'error');
      return;
    }
    
    if (!this.selectedKbId) {
      window.App.showToast('请选择一个知识库', 'error');
      return;
    }
    
    const searchType = document.querySelector('input[name="search-type"]:checked').value;
    const limit = parseInt(document.getElementById('search-limit').value);
    
    this.isSearching = true;
    this.updateSearchResultsUI('loading');
    
    try {
      let results;
      switch (searchType) {
        case 'vector':
          results = await window.SearchAPI.vectorSearch(query, limit, this.selectedKbId);
          break;
        case 'keyword':
          results = await window.SearchAPI.keywordSearch(query, limit, this.selectedKbId);
          break;
        case 'hybrid':
          results = await window.SearchAPI.hybridSearch(query, limit, this.selectedKbId);
          break;
      }
      
      this.searchResults = results.results || [];
      this.updateSearchResultsUI('results');
    } catch (error) {
      this.updateSearchResultsUI('error', error.message);
    } finally {
      this.isSearching = false;
    }
  },

  updateSearchResultsUI(state, errorMessage = '') {
    const resultsContainer = document.getElementById('search-results');
    
    switch (state) {
      case 'loading':
        resultsContainer.innerHTML = `
          <div class="search-loading">
            <div class="search-loading-spinner"></div>
            <p>正在搜索...</p>
          </div>
        `;
        break;
      case 'results':
        if (this.searchResults.length === 0) {
          resultsContainer.innerHTML = `
            <div class="empty-state">
              <div class="empty-icon">🔍</div>
              <div class="empty-title">无搜索结果</div>
              <div class="empty-desc">没有找到与您的查询相关的内容</div>
            </div>
          `;
        } else {
          resultsContainer.innerHTML = this.searchResults.map((result, index) => `
            <div class="result-card">
              <div class="result-card-header">
                <span class="result-rank">${index + 1}</span>
                <span class="result-source">${result.source || '知识库'}</span>
                <span class="result-score">相似度: ${(result.score * 100).toFixed(1)}%</span>
              </div>
              <div class="result-content">
                ${this.highlightQuery(result.content, document.getElementById('search-query').value)}
              </div>
            </div>
          `).join('');
        }
        break;
      case 'error':
        resultsContainer.innerHTML = `
          <div class="empty-state">
            <div class="empty-icon">❌</div>
            <div class="empty-title">搜索失败</div>
            <div class="empty-desc">${errorMessage || '搜索过程中出现错误'}</div>
            <button class="btn btn-secondary" onclick="SearchPage.performSearch()">
              重试
            </button>
          </div>
        `;
        break;
    }
  },

  highlightQuery(text, query) {
    if (!query) return text;
    const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    return text.replace(regex, '<mark>$1</mark>');
  },

  async refreshKbs() {
    await this.loadKnowledgeBases();
    window.App.showToast('知识库列表已刷新', 'success');
  }
};

window.SearchPage = SearchPage;