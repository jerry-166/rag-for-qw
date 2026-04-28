/**
 * AI Agent 页面
 *
 * 功能：
 * - 多会话管理（新建 / 切换 / 删除会话）
 * - 知识库选择器（可选绑定知识库，不选则自由问答）
 * - 单 Agent 对话（支持 Simple / Advanced / Claw 三种 Agent）
 * - SSE 流式响应 + typing 动画
 * - 引用文档卡片展示
 * - 多 Agent 对比模式（平行卡片）
 */

console.log('[AgentPage] agent.js 开始加载');
window.AgentPage = window.AgentPage || {

  // ── 状态 ────────────────────────────────────────────────────
  selectedAgent: 'claw',
  agents: [],

  // 多会话
  sessions: [],            // [{ id, name, messages, createdAt }]
  activeSessionId: null,

  // 知识库
  knowledgeBases: [],
  selectedKbId: null,      // null = 不使用知识库

  // 检索模式
  selectedRetrievalMode: 'advanced',  // native | advanced | hybrid

  // 流式状态
  isStreaming: false,
  abortController: null,

  // 对比模式
  compareMode: false,
  compareResults: null,
  compareLoading: false,

  // ── 计算属性 ──────────────────────────────────────────────
  get activeSession() {
    return this.sessions.find(s => s.id === this.activeSessionId) || null;
  },
  get currentMessages() {
    return this.activeSession ? this.activeSession.messages : [];
  },

  // ── 入口 ────────────────────────────────────────────────────

  async render() {
    try {
      // 初始化一个默认会话（仅当没有本地会话时）
      if (this.sessions.length === 0) {
        this._createSession('新对话');
      }

      // 并行加载：Agent 列表 + 知识库列表 + 历史会话
      await Promise.all([
        this._loadAgents(),
        this._loadKnowledgeBases(),
        this._loadHistorySessions(),
      ]);

      console.log('[AgentPage] 开始渲染布局');
      this._renderLayout();
      this._bindEvents();
      this._renderMessages();

      setTimeout(() => {
        const input = document.getElementById('agent-input');
        if (input) input.focus();
      }, 100);
    } catch (err) {
      console.error('[AgentPage] render() 失败:', err);
      const container = document.getElementById('page-container');
      if (container) {
        container.innerHTML = `
          <div style="padding: 40px; text-align: center; color: var(--text3);">
            <div style="font-size: 3rem; margin-bottom: 16px;">⚠️</div>
            <h3 style="color: var(--red); margin-bottom: 12px;">页面加载失败</h3>
            <p style="font-size: 0.9rem; margin-bottom: 16px;">${this._escapeHTML(err.message || '未知错误')}</p>
            <button onclick="window.AgentPage.render()" class="btn btn-primary" style="margin-top: 12px;">重试</button>
          </div>
        `;
      }
    }
  },

  async _loadAgents() {
    try {
      const data = await AgentAPI.list();
      this.agents = data.agents || [];
      const defaultAgent = data.default || 'claw';
      if (defaultAgent && this.agents.find(a => a.type === defaultAgent)) {
        this.selectedAgent = defaultAgent;
      } else if (this.agents.length > 0) {
        this.selectedAgent = this.agents[0].type;
      }
    } catch (e) {
      console.warn('[AgentPage] 获取 Agent 列表失败，使用默认值:', e);
      this.agents = [
        { type: 'simple',   name: 'SimpleRAGAgent',   capabilities: ['retrieval', 'basic-chat'] },
        { type: 'advanced', name: 'AdvancedRAGAgent',  capabilities: ['intent-classification', 'task-planning'] },
        { type: 'claw',     name: 'ClawRAGAgent',      capabilities: ['rag-workflow', 'hybrid-retrieval', 'rerank'], is_default: true },
      ];
      this.selectedAgent = 'claw';
    }
  },

  async _loadKnowledgeBases() {
    try {
      const data = await KnowledgeBaseAPI.list();
      this.knowledgeBases = data.knowledge_bases || [];
    } catch (e) {
      console.warn('[AgentPage] 获取知识库列表失败:', e);
      this.knowledgeBases = [];
    }
  },

  async _loadHistorySessions() {
    /**
     * 从后端加载历史会话列表（sessions/ 目录下的 .json 文件）。
     * 将历史会话合并到 this.sessions，避免重复。
     */
    try {
      const data = await AgentAPI.listSessions(50);
      const historySessions = (data.sessions || []).map(s => ({
        id: s.session_id,
        name: s.title || s.session_id,
        messageCount: s.message_count || 0,
        createdAt: s.created_at,
        updatedAt: s.updated_at,
        isHistory: true,  // 标记为来自服务器的历史会话
        messages: [],       // 历史消息按需加载
      }));

      // 合并：已有本地 session 不覆盖，新增历史 session
      const existingIds = new Set(this.sessions.map(s => s.id));
      for (const hs of historySessions) {
        if (!existingIds.has(hs.id)) {
          this.sessions.unshift(hs);  // 历史会话放在前面
          existingIds.add(hs.id);
        }
      }

      // 按更新时间排序（最新的在前）
      this.sessions.sort((a, b) => new Date(b.updatedAt || b.createdAt) - new Date(a.updatedAt || a.createdAt));

      console.log(`[AgentPage] 加载了 ${historySessions.length} 个历史会话，总计 ${this.sessions.length} 个`);
    } catch (e) {
      // 静默失败，不影响核心功能
      console.warn('[AgentPage] 加载历史会话失败:', e);
    }
  },

  // ── 会话管理 ────────────────────────────────────────────────

  _createSession(name) {
    const id = `session_${Date.now()}`;
    const session = {
      id,
      name: name || `对话 ${this.sessions.length + 1}`,
      messages: [],
      createdAt: Date.now(),
    };
    this.sessions.push(session);
    this.activeSessionId = id;
    return session;
  },

  async _switchSession(id) {
    if (this.isStreaming) return; // 流式中不允许切换
    const session = this.sessions.find(s => s.id === id);

    // 历史会话：从后端加载消息
    if (session && session.isHistory && (!session.messages || session.messages.length === 0)) {
      try {
        const data = await AgentAPI.getHistory(id, 50);
        if (data.messages && data.messages.length > 0) {
          session.messages = data.messages.map(m => ({
            role: m.role,
            content: m.content || '',
            agent_type: m.metadata?.agent_type,
            kb_name: null,
            sources: (m.metadata?.sources || []).map(s => ({
              content: s.content || '',
              chunk_text: s.chunk_text || '',
              score: s.score || 0,
              source: s.source || 'unknown',
              type: s.type || '',
              metadata: s.metadata || {},
            })),
            rawSources: [],
            citations: [],
          }));
        }
      } catch (e) {
        console.warn('[AgentPage] 加载历史消息失败:', e);
      }
    }

    this.activeSessionId = id;
    this._renderSessionList();
    this._renderMessages();
  },

  async _deleteSession(id) {
    if (this.sessions.length <= 1) {
      // 最后一个会话：清空内容而不删除
      const s = this.sessions.find(s => s.id === id);
      if (s) s.messages = [];
      try { await AgentAPI.clearSession(id); } catch (e) { /* ignore */ }
      this._renderMessages();
      return;
    }

    // 确认删除
    const session = this.sessions.find(s => s.id === id);
    const name = session ? session.name : '此会话';

    if (!confirm(`确定删除「${name}」？历史记录将被彻底删除。`)) return;

    // 如果是历史会话（存在后端文件），调用真正的删除接口
    if (session && session.isHistory) {
      try { await AgentAPI.deleteSession(id); } catch (e) { console.warn('删除失败:', e); }
    } else {
      try { await AgentAPI.clearSession(id); } catch (e) { /* ignore */ }
    }

    const idx = this.sessions.findIndex(s => s.id === id);
    this.sessions.splice(idx, 1);

    // 如果删的是当前会话，切换到最近的
    if (this.activeSessionId === id) {
      this.activeSessionId = this.sessions[Math.max(0, idx - 1)].id;
    }
    this._renderSessionList();
    this._renderMessages();
  },

  _newSession() {
    const name = `对话 ${this.sessions.length + 1}`;
    this._createSession(name);
    this._renderSessionList();
    this._renderMessages();
    setTimeout(() => {
      const input = document.getElementById('agent-input');
      if (input) input.focus();
    }, 50);
  },

  // ── 渲染 ────────────────────────────────────────────────────

  _renderLayout() {
    const container = document.getElementById('page-container');
    if (!container) return;

    container.innerHTML = `
      <div class="agent-page agent-page-v2">

        <!-- ── 左侧：会话列表 ── -->
        <aside class="agent-sidebar" id="agent-sidebar">
          <div class="sidebar-header">
            <span class="sidebar-title">会话列表</span>
            <button class="btn btn-ghost btn-icon sidebar-new-btn" id="agent-new-session" title="新建对话">＋</button>
          </div>
          <div class="sidebar-sessions" id="sidebar-sessions">
            ${this._buildSessionList()}
          </div>
        </aside>

        <!-- ── 右侧：主区域 ── -->
        <div class="agent-main" id="agent-main">

          <!-- 顶部工具栏 -->
          <div class="agent-toolbar">
            <div class="agent-toolbar-left">
              <h1 class="page-title" style="margin:0">AI Agent</h1>
              <div class="agent-mode-toggle">
                <button class="mode-btn ${!this.compareMode ? 'active' : ''}" id="mode-single" title="单 Agent 对话">💬 对话</button>
                <button class="mode-btn ${this.compareMode ? 'active' : ''}" id="mode-compare" title="多 Agent 对比">⚖️ 对比</button>
              </div>
            </div>
            <div class="agent-toolbar-right">
              <button class="btn btn-ghost btn-sm" id="agent-clear-btn" title="清空当前会话">🗑️ 清空</button>
            </div>
          </div>

          <!-- Agent 选择标签 -->
          ${this._buildAgentTabs()}
          ${this._buildCapabilitiesHint()}

          <!-- 主内容区 -->
          <div class="agent-content" id="agent-content">
            ${this.compareMode ? this._renderCompareView() : this._renderChatView()}
          </div>
        </div>
      </div>
    `;
  },

  _buildSessionList() {
    // sessions 已在 _loadHistorySessions 中按 updatedAt 降序排列（最新的在前）
    // 直接渲染，不再 reverse
    if (this.sessions.length === 0) return '<p class="sidebar-empty">暂无会话</p>';
    return this.sessions.map(s => {
      const msgCount = s.messages ? s.messages.length : (s.messageCount || 0);
      const metaParts = [];
      if (msgCount > 0) metaParts.push(`${msgCount} 条消息`);
      const timeStr = s.updatedAt || s.createdAt;
      if (timeStr) {
        try {
          const d = new Date(timeStr);
          const now = new Date();
          const diffMs = now - d;
          const diffMin = Math.floor(diffMs / 60000);
          if (diffMin < 1) metaParts.push('刚刚');
          else if (diffMin < 60) metaParts.push(`${diffMin} 分钟前`);
          else if (diffMin < 1440) metaParts.push(`${Math.floor(diffMin / 60)} 小时前`);
          else metaParts.push(d.toLocaleDateString());
        } catch { /* ignore */ }
      }
      return `
        <div class="sidebar-session-item ${s.id === this.activeSessionId ? 'active' : ''}" data-session-id="${s.id}">
          <span class="session-icon">${s.isHistory ? '📁' : '💬'}</span>
          <div class="session-info">
            <span class="session-name" title="${this._escapeAttr(s.name)}">${this._escapeHTML(s.name)}</span>
            ${metaParts.length > 0 ? `<span class="session-meta">${metaParts.join(' · ')}</span>` : ''}
          </div>
          <button class="session-delete-btn" data-delete-id="${s.id}" title="删除此会话">×</button>
        </div>
      `;
    }).join('');
  },

  _renderSessionList() {
    const el = document.getElementById('sidebar-sessions');
    if (el) el.innerHTML = this._buildSessionList();
    // 重新绑定侧边栏事件
    this._bindSidebarEvents();
  },

  _renderChatView() {
    const selectedKb = this.knowledgeBases.find(kb => kb.id === this.selectedKbId);
    return `
      <div class="agent-chat-layout">
        <!-- 消息列表 -->
        <div class="agent-messages" id="agent-messages">
          ${this._renderMessagesHTML()}
        </div>

        <!-- 知识库选择器 -->
        <div class="agent-kb-bar" id="agent-kb-bar">
          <div class="kb-bar-inner">
            <span class="kb-bar-label">📚 知识库：</span>
            <div class="kb-selector-chips" id="kb-selector-chips">
              ${this._buildKbChips()}
            </div>
          </div>
          <!-- 检索模式选择器 -->
          <div class="retrieval-mode-selector">
            <span class="mode-label">🔮 检索模式：</span>
            <select id="retrieval-mode-select" class="mode-select">
              <option value="advanced" ${this.selectedRetrievalMode === 'advanced' ? 'selected' : ''}>摘要+子问题</option>
              <option value="native" ${this.selectedRetrievalMode === 'native' ? 'selected' : ''}>原文匹配</option>
              <option value="hybrid" ${this.selectedRetrievalMode === 'hybrid' ? 'selected' : ''}>三路融合</option>
            </select>
          </div>
          ${selectedKb ? `
            <div class="kb-active-hint">
              <span class="kb-active-badge">✅ 已选：${this._escapeHTML(selectedKb.kb_name)}</span>
              <span class="kb-active-desc">Agent 将优先在此知识库中检索</span>
            </div>
          ` : `
            <div class="kb-active-hint">
              <span class="kb-active-badge kb-none">🔓 全局模式</span>
              <span class="kb-active-desc">未绑定知识库，Agent 将在全量数据中自由检索</span>
            </div>
          `}
        </div>

        <!-- 输入区 -->
        <div class="agent-input-area">
          <div class="input-wrapper">
            <textarea
              id="agent-input"
              class="agent-textarea"
              placeholder="输入您的问题，按 Enter 发送，Shift+Enter 换行..."
              rows="1"
            ></textarea>
            <button class="btn btn-primary agent-send-btn" id="agent-send-btn" title="发送">
              <span class="send-icon">➤</span>
            </button>
          </div>
          <div class="input-hint">Enter 发送 · Shift+Enter 换行</div>
        </div>
      </div>
    `;
  },

  _buildKbChips() {
    const options = [
      `<option value="" ${!this.selectedKbId ? 'selected' : ''}>🔓 不限知识库（全局检索）</option>`,
      ...this.knowledgeBases.map(kb =>
        `<option value="${kb.id}" ${this.selectedKbId === kb.id ? 'selected' : ''}>📂 ${this._escapeHTML(kb.kb_name)}</option>`
      ),
    ];
    return `
      <select class="kb-select" id="kb-select">
        ${options.join('')}
      </select>
      ${this.knowledgeBases.length === 0 ? '<span class="kb-hint-text">（暂无知识库，可前往「知识库」页面创建）</span>' : ''}
    `;
  },

  _renderCompareView() {
    return `
      <div class="agent-compare-layout">
        <div class="compare-header">
          <p class="compare-hint">同时运行所有 Agent，对比回答质量、处理速度和引用来源</p>
        </div>
        <div class="compare-results" id="compare-results">
          ${this.compareResults ? this._renderCompareResults() : `
            <div class="compare-placeholder">
              <div class="placeholder-icon">⚖️</div>
              <p>输入问题后点击「开始对比」，将并行运行所有 Agent</p>
            </div>
          `}
        </div>
        <div class="agent-input-area" id="compare-input-area">
          <div class="input-wrapper">
            <textarea id="compare-input" class="agent-textarea" placeholder="输入要对比的问题..." rows="1"></textarea>
            <button class="btn btn-accent agent-send-btn" id="compare-send-btn" title="开始对比">
              <span class="send-icon">⚡</span>
            </button>
          </div>
        </div>
      </div>
    `;
  },

  _renderMessagesHTML() {
    if (this.currentMessages.length === 0) {
      const kbHint = this.selectedKbId
        ? `已绑定知识库：<strong>${this._escapeHTML((this.knowledgeBases.find(k => k.id === this.selectedKbId) || {}).kb_name || '')}</strong>`
        : '全局模式（未绑定知识库）';
      return `
        <div class="agent-empty-state">
          <div class="empty-icon">🤖</div>
          <h3>开始对话</h3>
          <p>当前模式：${kbHint}</p>
          <div class="empty-examples">
            <p class="examples-label">试试这些问题：</p>
            <div class="example-chips">
              ${['RAG 和 Fine-tuning 的区别是什么？', '什么是向量检索？', '如何提升 RAG 的召回率？'].map(q =>
                `<button class="example-chip" data-query="${this._escapeAttr(q)}">${q}</button>`
              ).join('')}
            </div>
          </div>
        </div>
      `;
    }
    return this.currentMessages.map((msg, idx) => this._renderMessage(msg, idx)).join('');
  },

  _renderMessage(msg, idx) {
    if (msg.role === 'user') {
      return `
        <div class="message message-user" data-idx="${idx}">
          <div class="message-avatar user-avatar-icon">👤</div>
          <div class="message-bubble">
            <div class="message-content">${this._escapeHTML(msg.content)}</div>
          </div>
        </div>
      `;
    }

    const isStreaming = msg._streaming || false;
    const citations = msg.citations || [];
    const sources = msg.sources || [];   // 精排后来源
    // 反馈状态：null | 'up' | 'down'
    const feedback = msg.feedback || null;

    return `
      <div class="message message-agent" data-idx="${idx}">
        <div class="message-avatar agent-avatar-icon">🤖</div>
        <div class="message-bubble">
          <div class="message-meta">
            <span class="agent-tag ${msg.agent_type || this.selectedAgent}">${this._agentLabel(msg.agent_type || this.selectedAgent)}</span>
            ${msg.kb_name ? `<span class="kb-ref-badge">📂 ${this._escapeHTML(msg.kb_name)}</span>` : ''}
            ${msg.processing_time ? `<span class="processing-time">⏱ ${msg.processing_time}ms</span>` : ''}
            ${sources.length > 0 ? `<span class="sources-count">📚 ${sources.length} 条引用</span>` : ''}
          </div>
          <div class="message-content ${isStreaming ? 'streaming-text' : ''}" id="msg-content-${idx}">
            ${this._renderMarkdown(msg.content)}
          </div>
          ${sources.length > 0 ? this._renderSourcesPanel(sources, '精排来源') : ''}
          ${citations.length > 0 ? `
            <div class="citations-panel">
              <div class="citations-header">📎 引用文档</div>
              <div class="citations-list">
                ${citations.map((c, ci) => `
                  <div class="citation-card" data-idx="${ci}">
                    <div class="citation-score">${((c.score || 0) * 100).toFixed(0)}%</div>
                    <div class="citation-body">
                      <div class="citation-source">${this._escapeHTML(c.source || c.metadata?.source || '未知来源')}</div>
                      <div class="citation-snippet">${this._escapeHTML((c.content || '').slice(0, 200))}${c.content && c.content.length > 200 ? '…' : ''}</div>
                    </div>
                  </div>
                `).join('')}
              </div>
            </div>
          ` : ''}
          ${!isStreaming ? this._renderFeedbackBar(idx, feedback) : ''}
        </div>
      </div>
    `;
  },

  _renderFeedbackBar(msgIdx, feedback, comment = '') {
    const upActive   = feedback === 'up'   ? 'active' : '';
    const downActive = feedback === 'down' ? 'active' : '';
    // 点踩且尚未最终提交时显示评论框；若已有 comment 说明已提交
    const showCommentBox = feedback === 'down' && !comment;
    const showThanks     = (feedback === 'up') || (feedback === 'down' && comment !== undefined && comment !== null && comment !== '__skip__');
    const showSkipThanks = feedback === 'down' && comment === '__skip__';

    return `
      <div class="feedback-bar" data-msg-idx="${msgIdx}">
        <div class="feedback-row">
          <span class="feedback-label">对此回答：</span>
          <button class="feedback-btn feedback-up ${upActive}"
                  title="这个回答很有帮助"
                  data-feedback-idx="${msgIdx}" data-feedback-value="1">
            👍
          </button>
          <button class="feedback-btn feedback-down ${downActive}"
                  title="这个回答需要改进"
                  data-feedback-idx="${msgIdx}" data-feedback-value="0">
            👎
          </button>
          ${(showThanks || showSkipThanks) ? '<span class="feedback-thanks">已反馈，感谢！</span>' : ''}
        </div>
        ${showCommentBox ? `
          <div class="feedback-comment-box" data-comment-idx="${msgIdx}">
            <textarea class="feedback-comment-input"
                      placeholder="（可选）请简述问题所在，帮助我们改进……"
                      maxlength="300"
                      rows="2"></textarea>
            <div class="feedback-comment-actions">
              <button class="feedback-comment-submit" data-comment-idx="${msgIdx}">提交</button>
              <button class="feedback-comment-skip"   data-comment-idx="${msgIdx}">跳过</button>
            </div>
          </div>
        ` : ''}
      </div>
    `;
  },

  _renderSourcesPanel(sources, title, collapsed = true) {
    if (!sources || sources.length === 0) return '';
    const panelId = `src-panel-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const typeIcon = { vector: '🔮', keyword: '🔍', reranked: '⭐', unknown: '📄' };
    return `
      <div class="sources-panel ${collapsed ? 'sources-collapsed' : ''}" id="${panelId}">
        <div class="sources-header" onclick="document.getElementById('${panelId}').classList.toggle('sources-collapsed')">
          <span class="sources-title">🔍 ${this._escapeHTML(title)} (${sources.length})</span>
          <span class="sources-toggle">▼</span>
        </div>
        <div class="sources-list">
          ${sources.map((s, si) => `
            <div class="source-card" data-source-idx="${si}">
              <div class="source-card-header">
                <span class="source-type-badge ${s.source || 'unknown'}">${typeIcon[s.source] || '📄'} ${this._escapeHTML(s.source || 'unknown')}</span>
                <span class="source-score-bar">
                  <span class="source-score-fill" style="width: ${Math.min(100, Math.max(0, (parseFloat(s.score) || 0) * 100))}%"></span>
                  <span class="source-score-text">${typeof s.score === 'number' ? (s.score * 100).toFixed(1) + '%' : s.score}</span>
                </span>
              </div>
              ${(s.source === 'keyword' || s.type === 'native') ? `
                ${s.chunk_text ? `
                  <div class="source-section">
                    <div class="source-section-label">📄 原文内容</div>
                    <div class="source-chunk">${this._escapeHTML(s.chunk_text.slice(0, 400))}${s.chunk_text.length > 400 ? '…' : ''}</div>
                  </div>
                ` : ''}
              ` : `
                ${s.content ? `
                  <div class="source-section">
                    <div class="source-section-label">📝 ${s.type === 'subquestion' ? '匹配子问题' : (s.type === 'native' ? '原文匹配' : '匹配摘要')}</div>
                    <div class="source-snippet">${this._escapeHTML(s.content.slice(0, 300))}${s.content.length > 300 ? '…' : ''}</div>
                  </div>
                ` : ''}
                ${s.chunk_text ? `
                  <div class="source-section">
                    <div class="source-section-label">📄 原文内容</div>
                    <div class="source-chunk">${this._escapeHTML(s.chunk_text.slice(0, 400))}${s.chunk_text.length > 400 ? '…' : ''}</div>
                  </div>
                ` : ''}
              `}
              ${s.metadata?.filename ? `<div class="source-filename">📄 ${this._escapeHTML(s.metadata.filename)}</div>` : ''}
              ${s.metadata?.document_id ? `<div class="source-doc-id">ID: ${this._escapeHTML(String(s.metadata.document_id).slice(0, 12))}</div>` : ''}
            </div>
          `).join('')}
        </div>
      </div>
    `;
  },

  _renderSourcePanelOnly(msgIdx) {
    /**
     * 只更新指定消息的来源面板（不重渲染整个消息列表）。
     * 用于 SSE 流式期间收到 retrieved/reranked 事件时即时展示，
     * 以及流结束后兜底渲染。
     */
    const session = this.activeSession;
    if (!session || !session.messages[msgIdx]) {
      console.warn(`[AgentPage] _renderSourcePanelOnly: 消息 ${msgIdx} 不存在`);
      return;
    }
    const msg = session.messages[msgIdx];
    const sources = msg.sources || [];

    // 找到该消息气泡内的 source-panel 区域
    const msgEl = document.querySelector(`.message-agent[data-idx="${msgIdx}"]`);
    if (!msgEl) {
      console.warn(`[AgentPage] _renderSourcePanelOnly: DOM元素 [data-idx="${msgIdx}"] 不存在`);
      return;
    }

    // 移除旧的来源面板（防止重复追加）
    const oldPanels = msgEl.querySelectorAll('.sources-panel');
    oldPanels.forEach(el => el.remove());

    // 在消息内容后面插入新的来源面板
    const contentEl = msgEl.querySelector('.message-content');
    if (contentEl) {
      let html = '';
      if (sources.length > 0) html += this._renderSourcesPanel(sources, '精排来源');
      if (html) {
        contentEl.insertAdjacentHTML('afterend', html);
        // 绑定折叠事件
        const headers = contentEl.parentElement.querySelectorAll('.sources-header');
        headers.forEach(h => {
          h.onclick = () => {
            h.closest('.sources-panel')?.classList.toggle('sources-collapsed');
          };
        });
      }
      console.log(`[AgentPage] 来源面板已渲染: 精排${sources.length}条`);
    }

    this._scrollToBottom();
  },

  _renderCompareResults() {
    const results = this.compareResults;
    const agentOrder = Object.keys(results);
    if (agentOrder.length === 0) return '<p>暂无对比结果</p>';

    return `
      <div class="compare-cards">
        ${agentOrder.map(type => {
          const r = results[type];
          if (r.error) {
            return `
              <div class="compare-card error" data-agent="${type}">
                <div class="compare-card-header">
                  <span class="compare-agent-badge ${type}">${this._agentLabel(type)}</span>
                  <span class="compare-status error">❌ 错误</span>
                </div>
                <div class="compare-error">${this._escapeHTML(r.error)}</div>
              </div>
            `;
          }
          return `
            <div class="compare-card" data-agent="${type}">
              <div class="compare-card-header">
                <span class="compare-agent-badge ${type}">${this._agentLabel(type)}</span>
                <div class="compare-metrics">
                  <span class="metric-time" title="处理耗时">⏱ ${r.processing_time ? r.processing_time.toFixed(0) + 'ms' : '—'}</span>
                  <span class="metric-sources" title="引用文档数">📚 ${r.sources_count ?? 0}</span>
                </div>
              </div>
              <div class="compare-card-body">${this._renderMarkdown(r.content || '')}</div>
            </div>
          `;
        }).join('')}
      </div>
    `;
  },

  _buildAgentTabs() {
    if (this.compareMode) return '';
    const options = this.agents.map(agent => {
      const icon = this._agentIcon(agent.type);
      const label = `${icon} ${this._agentLabel(agent.type)}`;
      return `<option value="${agent.type}" ${agent.type === this.selectedAgent ? 'selected' : ''}>${label}</option>`;
    }).join('');
    return `
      <div class="agent-select-wrapper">
        <label class="agent-select-label">🤖 选择 Agent</label>
        <select class="agent-select" id="agent-type-select">
          ${options}
        </select>
      </div>
    `;
  },

  _buildCapabilitiesHint() {
    if (this.compareMode) return '';
    const agent = this.agents.find(a => a.type === this.selectedAgent);
    if (!agent || !agent.capabilities) return '';
    return `
      <div class="capabilities-hint">
        <span class="capabilities-label">能力：</span>
        ${agent.capabilities.map(c => `<span class="capability-chip">${c}</span>`).join('')}
      </div>
    `;
  },

  _renderMarkdown(text) {
    if (!text) return '';
    if (typeof marked !== 'undefined') {
      try { return marked.parse(text); } catch (e) { return this._escapeHTML(text); }
    }
    return this._escapeHTML(text).replace(/\n/g, '<br>');
  },

  _renderMessages() {
    const el = document.getElementById('agent-messages');
    if (el) {
      el.innerHTML = this._renderMessagesHTML();
      this._scrollToBottom();
    }
  },

  // ── 事件绑定 ────────────────────────────────────────────────

  _bindEvents() {
    // 侧边栏事件
    this._bindSidebarEvents();

    // 新建会话
    document.getElementById('agent-new-session')?.addEventListener('click', () => {
      this._newSession();
    });

    // 清空当前会话
    document.getElementById('agent-clear-btn')?.addEventListener('click', async () => {
      if (this.currentMessages.length === 0) return;
      if (!confirm('确定清空当前会话消息？')) return;
      if (this.activeSession) {
        try { await AgentAPI.clearSession(this.activeSessionId); } catch (e) { /* ignore */ }
        this.activeSession.messages = [];
      }
      this._renderMessages();
    });

    // 模式切换
    document.getElementById('mode-single')?.addEventListener('click', () => {
      if (this.compareMode) {
        this.compareMode = false;
        this._renderLayout();
        this._bindEvents();
        this._renderMessages();
      }
    });

    document.getElementById('mode-compare')?.addEventListener('click', () => {
      if (!this.compareMode) {
        this.compareMode = true;
        this._renderLayout();
        this._bindEvents();
      }
    });

    // Agent 选择器（下拉框）
    const agentSelect = document.getElementById('agent-type-select');
    if (agentSelect) {
      agentSelect.addEventListener('change', () => {
        const type = agentSelect.value;
        if (type === this.selectedAgent) return;
        this.selectedAgent = type;
        this._renderLayout();  // 重新渲染以更新能力提示
        this._bindEvents();
        this._renderMessages();
      });
    }

    // 知识库选择器（下拉框）
    const kbSelect = document.getElementById('kb-select');
    if (kbSelect) {
      kbSelect.addEventListener('change', () => {
        const rawVal = kbSelect.value;
        this.selectedKbId = (rawVal === '' || rawVal === null || rawVal === undefined) ? null : parseInt(rawVal, 10);
        this._refreshKbBar();
      });
    }

    // 检索模式选择器
    const retrievalModeSelect = document.getElementById('retrieval-mode-select');
    if (retrievalModeSelect) {
      retrievalModeSelect.addEventListener('change', () => {
        this.selectedRetrievalMode = retrievalModeSelect.value;
      });
    }

    // 对话输入
    const inputEl = document.getElementById('agent-input');
    const sendBtn = document.getElementById('agent-send-btn');
    if (inputEl && sendBtn) {
      inputEl.addEventListener('input', () => {
        inputEl.style.height = 'auto';
        inputEl.style.height = Math.min(inputEl.scrollHeight, 200) + 'px';
      });
      inputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this._handleSend(); }
      });
      sendBtn.addEventListener('click', () => this._handleSend());
    }

    // 示例问题
    document.querySelectorAll('.example-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const query = chip.dataset.query;
        const input = document.getElementById('agent-input');
        if (input) { input.value = query; this._handleSend(); }
      });
    });

    // 对比模式输入
    const compareInput = document.getElementById('compare-input');
    const compareBtn = document.getElementById('compare-send-btn');
    if (compareInput && compareBtn) {
      compareInput.addEventListener('input', () => {
        compareInput.style.height = 'auto';
        compareInput.style.height = Math.min(compareInput.scrollHeight, 200) + 'px';
      });
      compareInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this._handleCompare(); }
      });
      compareBtn.addEventListener('click', () => this._handleCompare());
    }

    // 引用卡片展开
    document.querySelectorAll('.citation-card').forEach(card => {
      card.addEventListener('click', () => card.classList.toggle('expanded'));
    });

    // 反馈按钮（事件委托，挂在消息容器上）
    const messagesEl = document.getElementById('agent-messages');
    if (messagesEl) {
      messagesEl.addEventListener('click', (e) => {
        // 点赞 / 点踩按钮
        const btn = e.target.closest('.feedback-btn');
        if (btn) {
          const idx = parseInt(btn.dataset.feedbackIdx, 10);
          const value = parseInt(btn.dataset.feedbackValue, 10);
          if (!isNaN(idx) && !isNaN(value)) {
            this._handleFeedback(idx, value);
          }
          return;
        }

        // 点踩评论框 — 提交
        const submitBtn = e.target.closest('.feedback-comment-submit');
        if (submitBtn) {
          const idx = parseInt(submitBtn.dataset.commentIdx, 10);
          if (!isNaN(idx)) this._submitFeedbackComment(idx, false);
          return;
        }

        // 点踩评论框 — 跳过
        const skipBtn = e.target.closest('.feedback-comment-skip');
        if (skipBtn) {
          const idx = parseInt(skipBtn.dataset.commentIdx, 10);
          if (!isNaN(idx)) this._submitFeedbackComment(idx, true);
          return;
        }
      });
    }
  },

  _bindSidebarEvents() {
    // 会话切换
    document.querySelectorAll('.sidebar-session-item').forEach(item => {
      item.addEventListener('click', (e) => {
        // 不触发删除按钮本身的点击
        if (e.target.classList.contains('session-delete-btn')) return;
        const id = item.dataset.sessionId;
        if (id && id !== this.activeSessionId) {
          this._switchSession(id);
        }
      });
    });

    // 会话删除
    document.querySelectorAll('.session-delete-btn').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const id = btn.dataset.deleteId;
        if (!id) return;
        const session = this.sessions.find(s => s.id === id);
        const name = session ? session.name : '此会话';
        if (!confirm(`确定删除「${name}」？`)) return;
        await this._deleteSession(id);
      });
    });
  },

  _bindKbChips() {
    document.querySelectorAll('.kb-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const rawId = chip.dataset.kbId;
        this.selectedKbId = (rawId === 'null' || rawId === null) ? null : parseInt(rawId, 10);
        // 更新 chip 高亮
        document.querySelectorAll('.kb-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        // 刷新知识库状态栏
        this._refreshKbBar();
      });
    });
  },

  _refreshKbBar() {
    const bar = document.getElementById('agent-kb-bar');
    if (!bar) return;
    const selectedKb = this.knowledgeBases.find(kb => kb.id === this.selectedKbId);
    // 只更新 hint 部分，不重建整个 bar
    const hintEl = bar.querySelector('.kb-active-hint');
    if (hintEl) {
      hintEl.innerHTML = selectedKb ? `
        <span class="kb-active-badge">✅ 已选：${this._escapeHTML(selectedKb.kb_name)}</span>
        <span class="kb-active-desc">Agent 将优先在此知识库中检索</span>
      ` : `
        <span class="kb-active-badge kb-none">🔓 全局模式</span>
        <span class="kb-active-desc">未绑定知识库，Agent 将在全量数据中自由检索</span>
      `;
    }
    // 重新渲染空状态提示（kb提示可能包含知识库名）
    const msgsEl = document.getElementById('agent-messages');
    if (msgsEl && this.currentMessages.length === 0) {
      msgsEl.innerHTML = this._renderMessagesHTML();
    }
  },

  // ── 发送消息 ────────────────────────────────────────────────

  async _handleSend() {
    if (this.isStreaming) return;
    const inputEl = document.getElementById('agent-input');
    const query = inputEl.value.trim();
    if (!query) return;

    // 保证有活跃会话
    if (!this.activeSession) {
      this._createSession('新对话');
      this._renderSessionList();
    }

    // 追加用户消息
    const session = this.activeSession;
    session.messages.push({ role: 'user', content: query });
    inputEl.value = '';
    inputEl.style.height = 'auto';

    // 自动重命名会话（取第一条问题的前 12 字）
    if (session.messages.filter(m => m.role === 'user').length === 1) {
      session.name = query.slice(0, 12) + (query.length > 12 ? '…' : '');
      this._renderSessionList();
    }

    // AI 占位消息
    const aiMsgIdx = session.messages.length;
    const selectedKb = this.knowledgeBases.find(kb => kb.id === this.selectedKbId);
    session.messages.push({
      role: 'assistant',
      content: '',
      agent_type: this.selectedAgent,
      kb_name: selectedKb ? selectedKb.kb_name : null,
      _streaming: true,
      citations: [],
      // 检索来源（SSE 流中 retrieved/reranked 事件填充）
      sources: [],   // 精排后的最终来源
      rawSources: [], // 原始检索候选
    });

    this._renderMessages();
    this.isStreaming = true;
    const sendBtn = document.getElementById('agent-send-btn');
    if (sendBtn) sendBtn.disabled = true;

    try {
      const stream = await AgentAPI.chatStream({
        query,
        agent_type: this.selectedAgent,
        session_id: this.activeSessionId,
        chat_history: this._formatHistory(session.messages.slice(0, aiMsgIdx)),
        knowledge_base_id: this.selectedKbId,
        retrieval_mode: this.selectedRetrievalMode,
      });

      await this._processStream(stream, aiMsgIdx);
    } catch (err) {
      console.error('流式请求失败:', err);
      if (session.messages[aiMsgIdx]) {
        session.messages[aiMsgIdx].content = `❌ 请求失败: ${err.message}`;
        session.messages[aiMsgIdx]._streaming = false;
      }
      this._renderMessages();
    } finally {
      this.isStreaming = false;
      if (sendBtn) sendBtn.disabled = false;
    }
  },

  async _processStream(stream, msgIdx) {
    const session = this.activeSession;
    if (!session) return;

    const reader = stream.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let fullContent = '';
    const msgContentEl = document.getElementById(`msg-content-${msgIdx}`);

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          let data;
          try { data = JSON.parse(raw); } catch { continue; }

          switch (data.type) {
            case 'connected':
              // 保存 Langfuse trace_id（由后端 @observe() 上下文生成）
              if (data.trace_id) {
                session.messages[msgIdx].trace_id = data.trace_id;
              }
              console.log('[Agent SSE] 已连接:', data);
              break;

            case 'chunk':
              if (data.chunk) {
                fullContent += data.chunk;
                session.messages[msgIdx].content = fullContent;
                if (msgContentEl) {
                  msgContentEl.innerHTML = this._renderMarkdown(fullContent);
                  this._scrollToBottom();
                }
              }
              break;

            case 'done':
              // 流结束 — 标记状态 + 兜底渲染来源面板
              session.messages[msgIdx]._streaming = false;
              session.messages[msgIdx].content = fullContent || '（无回复内容）';
              // done 事件中的 trace_id 比 connected 更可靠（CallbackHandler 执行后 trace 才确定）
              if (data.trace_id) {
                session.messages[msgIdx].trace_id = data.trace_id;
              }
              if (msgContentEl) {
                msgContentEl.innerHTML = this._renderMarkdown(fullContent || '（无回复内容）');
                msgContentEl.classList.remove('streaming-text');
              }
              // 【关键兜底】流结束后强制渲染来源面板
              // 防止 retrieved/reranked 事件丢失或时序问题时用户看不到来源
              const srcCount = (session.messages[msgIdx].sources?.length || 0)
                            + (session.messages[msgIdx].rawSources?.length || 0);
              console.log(`[Agent SSE] done事件, sources=${session.messages[msgIdx].sources?.length||0}, rawSources=${session.messages[msgIdx].rawSources?.length||0}`);
              if (srcCount > 0) {
                this._renderSourcePanelOnly(msgIdx);
              }
              break;

            case 'error':
              session.messages[msgIdx]._streaming = false;
              session.messages[msgIdx].content = `❌ 错误: ${data.error}`;
              break;

            case 'thinking':
              break;

            case 'retrieved':
              // 收集原始检索候选结果并立即渲染
              // 注意：后端 StreamChunk.to_sse() 将 metadata 直接展开到顶层
              const retrievedResults = data.results || (data.metadata && data.metadata.results);
              if (retrievedResults && retrievedResults.length > 0) {
                session.messages[msgIdx].rawSources = retrievedResults.map(r => ({
                  content: r.content || '',
                  chunk_text: r.chunk_text || '',
                  score: r.score || 0,
                  source: r.source || 'unknown',
                  type: r.type || '',
                  metadata: r.metadata || {},
                }));
                console.log('[Agent SSE] 收到 retrieved 事件:', session.messages[msgIdx].rawSources.length, '条候选');
                // 立即更新来源面板（不等流结束）
                this._renderSourcePanelOnly(msgIdx);
              }
              break;

            case 'reranked':
              // 收集精排后的最终来源并立即渲染
              // 注意：后端 StreamChunk.to_sse() 将 metadata 直接展开到顶层
              const rerankedResults = data.results || (data.metadata && data.metadata.results);
              if (rerankedResults && rerankedResults.length > 0) {
                session.messages[msgIdx].sources = rerankedResults.map(r => ({
                  content: r.content || '',
                  chunk_text: r.chunk_text || '',
                  score: r.score || 0,
                  source: r.source || 'unknown',
                  type: r.type || '',
                  metadata: r.metadata || {},
                }));
                console.log('[Agent SSE] 收到 reranked 事件:', session.messages[msgIdx].sources.length, '条精排结果');
                // 立即更新来源面板
                this._renderSourcePanelOnly(msgIdx);
              }
              break;

            case 'sources_final':
              // 【兜底事件】流结束后后端再次推送完整来源数据
              // 注意：后端 StreamChunk.to_sse() 将 metadata 直接展开到顶层
              const sourcesFinalResults = data.results || (data.metadata && data.metadata.results);
              if (sourcesFinalResults && sourcesFinalResults.length > 0) {
                session.messages[msgIdx].sources = sourcesFinalResults.map(r => ({
                  content: r.content || '',
                  chunk_text: r.chunk_text || '',
                  score: r.score || 0,
                  source: r.source || 'unknown',
                  type: r.type || '',
                  metadata: r.metadata || {},
                }));
                const srcCount = data.sources_count !== undefined ? data.sources_count :
                                (data.metadata && data.metadata.sources_count);
                if (srcCount !== undefined) {
                  session.messages[msgIdx].sources_count = srcCount;
                }
                console.log('[Agent SSE] 收到 sources_final 事件（兜底）:', session.messages[msgIdx].sources.length, '条来源');
                this._renderSourcePanelOnly(msgIdx);
              }
              break;

            default:
              if (data.metadata) {
                const meta = data.metadata;
                if (meta.sources_count !== undefined) {
                  session.messages[msgIdx].sources_count = meta.sources_count;
                }
              }
              break;
          }
        }
      }
    } finally {
      reader.releaseLock();
      session.messages[msgIdx]._streaming = false;
      // 全量重渲染（已包含来源面板）
      this._renderMessages();
    }
  },

  // ── 对比模式 ────────────────────────────────────────────────

  async _handleCompare() {
    if (this.compareLoading) return;
    const inputEl = document.getElementById('compare-input');
    const query = inputEl.value.trim();
    if (!query) return;

    this.compareLoading = true;
    this.compareResults = null;

    const resultsEl = document.getElementById('compare-results');
    resultsEl.innerHTML = `
      <div class="compare-loading">
        <div class="loading-dots"><span></span><span></span><span></span></div>
        <p>正在并行运行 ${this.agents.length} 个 Agent...</p>
      </div>
    `;
    inputEl.disabled = true;

    try {
      const resp = await AgentAPI.compare({
        query,
        agent_types: this.agents.map(a => a.type),
        session_id: this.activeSessionId,
        chat_history: [],
      });

      this.compareResults = resp.comparison?.results || {};
      const totalTime = resp.comparison?.total_time_ms;
      resultsEl.innerHTML = (totalTime !== undefined ? `
        <div class="compare-summary"><span>总耗时: <strong>${totalTime.toFixed(0)}ms</strong></span></div>
      ` : '') + this._renderCompareResults();
    } catch (err) {
      resultsEl.innerHTML = `<div class="compare-error-panel"><p>❌ 对比失败: ${this._escapeHTML(err.message)}</p></div>`;
    } finally {
      this.compareLoading = false;
      inputEl.disabled = false;
    }
  },

  // ── 工具函数 ────────────────────────────────────────────────

  async _handleFeedback(msgIdx, value) {
    const session = this.activeSession;
    if (!session || !session.messages[msgIdx]) return;

    const msg = session.messages[msgIdx];
    const newFeedback = value === 1 ? 'up' : 'down';

    // 再次点击同一按钮 = 取消反馈
    if (msg.feedback === newFeedback) {
      msg.feedback = null;
      msg.feedbackComment = null;
      this._updateFeedbackBar(msgIdx, null, null);
      return;
    }

    msg.feedback = newFeedback;
    msg.feedbackComment = null;   // 重置旧评论

    if (value === 1) {
      // 点赞：立即提交，无需评论
      this._updateFeedbackBar(msgIdx, 'up', 'ok');   // 'ok' 表示已提交
      await this._submitFeedbackToBackend(msgIdx, 1, null);
    } else {
      // 点踩：先展示评论框，等用户填写
      this._updateFeedbackBar(msgIdx, 'down', null);  // null = 评论框展开中
    }
  },

  async _submitFeedbackComment(msgIdx, skip) {
    /**
     * 用户点击"提交"或"跳过"后，发送点踩反馈到后端
     * skip=true 时不带 comment
     */
    const session = this.activeSession;
    if (!session || !session.messages[msgIdx]) return;

    const msg = session.messages[msgIdx];

    // 读取输入框内容
    const msgEl = document.querySelector(`.message-agent[data-idx="${msgIdx}"]`);
    let comment = null;
    if (!skip && msgEl) {
      const textarea = msgEl.querySelector('.feedback-comment-input');
      comment = textarea ? textarea.value.trim() : null;
    }

    // 用 __skip__ 作为"明确跳过"标记，和 null（未提交）区分
    msg.feedbackComment = skip ? '__skip__' : (comment || '__skip__');

    // 更新 UI（关闭评论框，显示感谢）
    this._updateFeedbackBar(msgIdx, 'down', msg.feedbackComment);

    // 提交后端
    await this._submitFeedbackToBackend(msgIdx, 0, skip ? null : comment);
  },

  async _submitFeedbackToBackend(msgIdx, value, comment) {
    const session = this.activeSession;
    if (!session) return;
    const msg = session.messages[msgIdx];
    const traceId = (msg && msg.trace_id) || null;
    // 传 trace_id + session_id：后端优先用 trace_id，
    // 若 trace_id 不像 Langfuse UUID 则从 session_id 重新计算
    try {
      await AgentAPI.feedback({
        traceId,
        value,
        comment,
        messageIndex: msgIdx,
        sessionId: this.activeSessionId,  // fallback
      });
      console.log(`[AgentPage] 反馈已提交: traceId=${traceId} sessionId=${this.activeSessionId} value=${value} comment=${comment} idx=${msgIdx}`);
    } catch (err) {
      console.warn('[AgentPage] 反馈提交失败（不影响使用）:', err.message);
    }
  },

  _updateFeedbackBar(msgIdx, feedback, comment) {
    /**
     * 局部更新指定消息的反馈栏，不重渲染整个消息列表
     * feedback : null | 'up' | 'down'
     * comment  : null（点踩展开评论框中） | '__skip__'（明确跳过） | string（已提交） | 'ok'（点赞已提交）
     */
    const msgEl = document.querySelector(`.message-agent[data-idx="${msgIdx}"]`);
    if (!msgEl) return;

    const barEl = msgEl.querySelector('.feedback-bar');
    if (!barEl) {
      const bubble = msgEl.querySelector('.message-bubble');
      if (bubble) {
        bubble.insertAdjacentHTML('beforeend', this._renderFeedbackBar(msgIdx, feedback, comment));
      }
      return;
    }

    // 用 innerHTML 重渲整个反馈栏（状态复杂，局部 patch 容易出错）
    const newHtml = this._renderFeedbackBar(msgIdx, feedback, comment);
    const tmp = document.createElement('div');
    tmp.innerHTML = newHtml;
    const newBar = tmp.querySelector('.feedback-bar');
    if (newBar) barEl.replaceWith(newBar);
  },

  _formatHistory(messages) {
    return (messages || []).slice(-20).map(msg => ({
      role: msg.role === 'user' ? 'user' : 'assistant',
      content: msg.content,
    }));
  },

  _scrollToBottom() {
    const el = document.getElementById('agent-messages');
    if (el) el.scrollTop = el.scrollHeight;
  },

  _escapeHTML(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  },

  _escapeAttr(str) {
    return String(str || '').replace(/"/g, '&quot;');
  },

  _agentLabel(type) {
    return { simple: 'Simple', advanced: 'Advanced', claw: 'Claw' }[type] || type;
  },

  _agentIcon(type) {
    return { simple: '🔹', advanced: '🔸', claw: '🦞' }[type] || '🤖';
  },
};

const AgentPage = window.AgentPage;
