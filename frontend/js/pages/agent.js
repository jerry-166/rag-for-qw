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
      // 初始化一个默认会话
      if (this.sessions.length === 0) {
        this._createSession('新对话');
      }

      // 并行加载：Agent 列表 + 知识库列表
      await Promise.all([
        this._loadAgents(),
        this._loadKnowledgeBases(),
      ]);

      console.log('[AgentPage] 开始渲染布局');
      this._renderLayout();
      this._bindEvents();
      this._renderMessages();

      // 预热在后台异步完成，前端无需感知

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

  _switchSession(id) {
    if (this.isStreaming) return; // 流式中不允许切换
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

    try { await AgentAPI.clearSession(id); } catch (e) { /* ignore */ }
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
    if (this.sessions.length === 0) return '<p class="sidebar-empty">暂无会话</p>';
    return this.sessions.slice().reverse().map(s => `
      <div class="sidebar-session-item ${s.id === this.activeSessionId ? 'active' : ''}" data-session-id="${s.id}">
        <span class="session-icon">💬</span>
        <span class="session-name" title="${this._escapeAttr(s.name)}">${this._escapeHTML(s.name)}</span>
        <button class="session-delete-btn" data-delete-id="${s.id}" title="删除此会话">×</button>
      </div>
    `).join('');
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
    const noneActive = this.selectedKbId === null;
    const noneChip = `
      <button class="kb-chip ${noneActive ? 'active' : ''}" data-kb-id="null" title="不绑定知识库，在全量数据中检索">
        🔓 不限知识库
      </button>
    `;
    const kbChips = this.knowledgeBases.map(kb => `
      <button class="kb-chip ${this.selectedKbId === kb.id ? 'active' : ''}" data-kb-id="${kb.id}" title="${this._escapeAttr(kb.description || kb.kb_name)}">
        📂 ${this._escapeHTML(kb.kb_name)}
      </button>
    `).join('');

    if (this.knowledgeBases.length === 0) {
      return `${noneChip}<span class="kb-chip-empty">（暂无知识库，可前往「知识库」页面创建）</span>`;
    }
    return noneChip + kbChips;
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

    return `
      <div class="message message-agent" data-idx="${idx}">
        <div class="message-avatar agent-avatar-icon">🤖</div>
        <div class="message-bubble">
          <div class="message-meta">
            <span class="agent-tag ${msg.agent_type || this.selectedAgent}">${this._agentLabel(msg.agent_type || this.selectedAgent)}</span>
            ${msg.kb_name ? `<span class="kb-ref-badge">📂 ${this._escapeHTML(msg.kb_name)}</span>` : ''}
            ${msg.processing_time ? `<span class="processing-time">⏱ ${msg.processing_time}ms</span>` : ''}
            ${msg.sources_count ? `<span class="sources-count">📚 ${msg.sources_count} 条引用</span>` : ''}
          </div>
          <div class="message-content ${isStreaming ? 'streaming-text' : ''}" id="msg-content-${idx}">
            ${this._renderMarkdown(msg.content)}
          </div>
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
        </div>
      </div>
    `;
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
    const tabs = this.agents.map(agent => `
      <button class="agent-tab ${agent.type === this.selectedAgent ? 'active' : ''}" data-agent="${agent.type}">
        ${this._agentIcon(agent.type)}
        <span class="agent-tab-label">${this._agentLabel(agent.type)}</span>
      </button>
    `).join('');
    return `<div class="agent-tabs">${tabs}</div>`;
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

    // Agent Tab 切换
    document.querySelectorAll('.agent-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        const type = tab.dataset.agent;
        if (type === this.selectedAgent) return;
        this.selectedAgent = type;
        this._renderLayout();
        this._bindEvents();
        this._renderMessages();
      });
    });

    // 知识库 chip 切换
    this._bindKbChips();

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
              session.messages[msgIdx]._streaming = false;
              session.messages[msgIdx].content = fullContent || '（无回复内容）';
              if (msgContentEl) {
                msgContentEl.innerHTML = this._renderMarkdown(fullContent || '（无回复内容）');
                msgContentEl.classList.remove('streaming-text');
              }
              break;

            case 'error':
              session.messages[msgIdx]._streaming = false;
              session.messages[msgIdx].content = `❌ 错误: ${data.error}`;
              break;

            case 'thinking':
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
