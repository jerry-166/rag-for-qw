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
          <div class="glass"><div class="state">
            <div class="glyph" style="color:var(--danger)">⚠</div>
            <div class="title">页面加载失败</div>
            <p class="desc">${this._escapeHTML(err.message || '未知错误')}</p>
            <button onclick="window.AgentPage.render()" class="btn btn-sm mt4">重试</button>
          </div></div>
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

    const delOk = await window.UI.confirm({
      title: '删除会话',
      message: `确定删除「${name}」？历史记录将被彻底删除。`,
      okText: '删除',
      danger: true
    });
    if (!delOk) return;

    // 如果是历史会话（存在后端文件），调用真正的删除接口
    if (session && session.isHistory) {
      try {
        await AgentAPI.deleteSession(id);
      } catch (e) {
        // request() 已自动 toast 错误；后端未删除，保留本地条目保持一致
        return;
      }
    } else {
      try { await AgentAPI.clearSession(id); } catch (e) { /* 本地新会话无后端文件，忽略 */ }
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
      <div class="grid agent-layout" style="display:grid;grid-template-columns:250px 1fr;align-items:stretch;gap:var(--sp-4);min-height:0;height:100%">

        <!-- 会话侧栏：grid stretch 跟随主区高度，内部独立滚动 -->
        <aside class="glass p4 col" id="agent-sidebar" style="gap:2px;display:flex;flex-direction:column;min-height:0;overflow:hidden;padding:var(--sp-4)">
          <div class="row between mb4" style="padding:0 var(--sp-2);flex:none;display:flex;align-items:center;justify-content:space-between">
            <span class="label-caps">会话</span>
            <button class="icon-btn" id="agent-new-session" title="新建对话">＋</button>
          </div>
          <div class="col" id="sidebar-sessions" style="gap:2px;overflow-y:auto;min-height:0;flex:1 1 auto">
            ${this._buildSessionList()}
          </div>
        </aside>

        <div class="col" id="agent-main" style="display:flex;flex-direction:column;min-height:0;min-width:0;gap:var(--sp-3);height:100%">
          <header class="topbar" style="position:static;margin-bottom:0;flex:none">
            <span class="crumb">AI Agent</span>
            <div class="seg" style="margin-left:var(--sp-4)" id="agent-mode-seg">
              <button class="${!this.compareMode ? 'on' : ''}" id="mode-single" title="单 Agent 对话">对话</button>
              <button class="${this.compareMode ? 'on accent' : ''}" id="mode-compare" title="多 Agent 对比">对比</button>
            </div>
            <div class="spacer"></div>
            <select class="select" id="agent-type-select" style="width:180px;height:32px" title="选择 Agent">${this._buildAgentTabsOptions()}</select>
            <button class="icon-btn" id="agent-clear-btn" title="清空当前会话">🗑</button>
          </header>

          ${this._buildCapabilitiesHint()}

          <div id="agent-content" style="flex:1 1 auto;min-height:0;display:flex;flex-direction:column;overflow:hidden">
            ${this.compareMode ? this._renderCompareView() : this._renderChatView()}
          </div>
        </div>
      </div>
    `;
  },

  _buildSessionList() {
    // sessions 已在 _loadHistorySessions 中按 updatedAt 降序排列（最新的在前）
    // 直接渲染，不再 reverse
    if (this.sessions.length === 0) return '<p class="t3" style="font-size:var(--fs-sm);padding:var(--sp-3)">暂无会话</p>';
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
        <div class="sess ${s.id === this.activeSessionId ? 'on' : ''}" data-session-id="${s.id}" style="display:flex;gap:var(--sp-3);padding:var(--sp-3);border-radius:var(--r-sm);cursor:pointer;border:1px solid transparent;transition:all var(--dur-2) var(--ease-out)">
          <div><b style="font-size:var(--fs-sm)">${this._escapeHTML(s.name)}</b><p class="t3" style="font-size:var(--fs-xs)">${metaParts.join(' · ') || '新会话'}</p></div>
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
      <div class="agent-pane col" style="display:flex;flex-direction:column;min-height:0;min-width:0;flex:1 1 auto;gap:var(--sp-3);overflow:hidden">
        <div class="glass chat-scroll" id="agent-messages" style="flex:1 1 0;overflow-y:auto;min-height:120px;padding:var(--sp-5)">
          ${this._renderMessagesHTML()}
        </div>

        <div class="glass p4" id="agent-kb-bar" style="display:flex;flex-wrap:nowrap;align-items:center;gap:var(--sp-2);margin-top:var(--sp-3);min-width:0;overflow:hidden">
          <span class="t3" style="font-size:var(--fs-xs);flex:none">知识库：</span>
          <select id="kb-select" class="select" style="height:30px;font-size:var(--fs-xs);flex:1 1 0;min-width:120px;width:auto;max-width:100%">
            <option value="" ${!this.selectedKbId ? 'selected' : ''}>不限知识库（全局检索）</option>
            ${this.knowledgeBases.map(kb => `<option value="${kb.id}" ${this.selectedKbId === kb.id ? 'selected' : ''}>🗂 ${this._escapeHTML(kb.kb_name)}</option>`).join('')}
          </select>
          <span class="t3" style="font-size:var(--fs-xs);flex:none">模式：</span>
          <select id="retrieval-mode-select" class="select" style="height:30px;font-size:var(--fs-xs);flex:0 0 auto;width:auto;min-width:120px">
            <option value="advanced" ${this.selectedRetrievalMode === 'advanced' ? 'selected' : ''}>摘要+子问题</option>
            <option value="native" ${this.selectedRetrievalMode === 'native' ? 'selected' : ''}>原文匹配</option>
            <option value="hybrid" ${this.selectedRetrievalMode === 'hybrid' ? 'selected' : ''}>三路融合</option>
          </select>
          ${selectedKb ? `<span class="t3 kb-bar-hint" style="font-size:var(--fs-xs);flex:none;margin-left:auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">已选：${this._escapeHTML(selectedKb.kb_name)}</span>` : `<span class="t3 kb-bar-hint" style="font-size:var(--fs-xs);flex:none;margin-left:auto">全局模式</span>`}
        </div>

        <div class="glass composer" style="display:flex;gap:var(--sp-3);padding:var(--sp-4);align-items:flex-end;margin-top:var(--sp-3);flex:none">
          <textarea id="agent-input" class="textarea grow" rows="1" style="border:0;background:transparent;box-shadow:none;resize:none;max-height:140px;overflow-y:hidden;line-height:1.5" placeholder="输入问题，Enter 发送 · Shift+Enter 换行 · 自动长高，超长出滚动条"></textarea>
          <button class="btn btn-primary" id="agent-send-btn" style="border-radius:var(--r-pill);width:44px;height:44px;padding:0;justify-content:center;flex:none" title="发送">➤</button>
        </div>
      </div>
    `;
  },

  _buildAgentTabsOptions() {
    return this.agents.map(agent =>
      `<option value="${agent.type}" ${agent.type === this.selectedAgent ? 'selected' : ''}>Agent：${this._agentLabel(agent.type)}</option>`
    ).join('');
  },

  _renderCompareView() {
    return `
      <div class="col" style="gap:var(--sp-4)">
        <div class="glass p5">
          <p class="t2" style="font-size:var(--fs-sm)">同时运行所有 Agent，对比回答质量、处理速度和引用来源</p>
        </div>
        <div id="compare-results" class="col" style="gap:var(--sp-4)">
          ${this.compareResults ? this._renderCompareResults() : `
            <div class="glass"><div class="state">
              <div class="glyph">⚖</div>
              <div class="title">输入问题开始对比</div>
              <p class="desc">将并行运行所有 Agent</p>
            </div></div>
          `}
        </div>
        <div class="glass composer" style="display:flex;gap:var(--sp-3);padding:var(--sp-4);align-items:flex-end">
          <textarea id="compare-input" class="textarea grow" rows="1" style="border:0;background:transparent;box-shadow:none;resize:none" placeholder="输入要对比的问题..."></textarea>
          <button class="btn btn-primary" id="compare-send-btn" style="border-radius:var(--r-pill);width:44px;height:44px;padding:0;justify-content:center;flex:none" title="开始对比">⚡</button>
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
        <div class="state">
          <div class="glyph float-anim">✦</div>
          <div class="title">开始对话</div>
          <p class="desc">当前模式：${kbHint}</p>
          <div class="row wrap mt4" style="gap:6px;justify-content:center">
            ${['RAG 和 Fine-tuning 的区别是什么？', '什么是向量检索？', '如何提升 RAG 的召回率？'].map(q =>
              `<button class="btn btn-sm example-chip" data-query="${this._escapeAttr(q)}">${q}</button>`
            ).join('')}
          </div>
        </div>
      `;
    }
    return this.currentMessages.map((msg, idx) => this._renderMessage(msg, idx)).join('');
  },

  _renderMessage(msg, idx) {
    if (msg.role === 'user') {
      return `
        <div class="msg user" data-idx="${idx}" style="display:flex;gap:var(--sp-3);max-width:78%;margin-left:auto;flex-direction:row-reverse;margin-bottom:var(--sp-5)">
          <div class="bubble" style="padding:var(--sp-3) var(--sp-4);border-radius:var(--r-lg);background:var(--accent-soft);border:1px solid transparent;color:var(--text-1);border-top-right-radius:var(--r-xs)">${this._escapeHTML(msg.content)}</div>
        </div>
      `;
    }

    const isStreaming = msg._streaming || false;
    const citations = msg.citations || [];
    const sources = msg.sources || [];
    const feedback = msg.feedback || null;
    const faqBadge = msg._faqHit
      ? '<span class="badge accent"><i class="dot"></i>FAQ 命中 · 直返</span>' : '';

    return `
      <div class="msg ai" data-idx="${idx}" style="display:flex;gap:var(--sp-3);max-width:78%;margin-bottom:var(--sp-5)">
        <div class="avatar" style="width:30px;height:30px;font-size:11px;flex:none;border-radius:50%;display:grid;place-items:center;background:linear-gradient(135deg,var(--accent-strong),var(--accent-deep));color:var(--accent-on);font-weight:700">AI</div>
        <div class="col grow" style="gap:var(--sp-2)">
          <div class="bubble glass" style="padding:var(--sp-3) var(--sp-4);border-radius:var(--r-lg);border-top-left-radius:var(--r-xs);box-shadow:inset 0 1px 0 var(--glass-edge)">
            <div class="row wrap" style="gap:6px;margin-bottom:var(--sp-2)">
              <span class="badge">${this._agentLabel(msg.agent_type || this.selectedAgent)}</span>
              ${msg.kb_name ? `<span class="badge">🗂 ${this._escapeHTML(msg.kb_name)}</span>` : ''}
              ${msg.processing_time ? `<span class="badge">耗时 ${(msg.processing_time / 1000).toFixed(1)}s</span>` : ''}
              ${sources.length > 0 ? `<span class="badge info">📚 ${sources.length} 条引用</span>` : ''}
              ${faqBadge}
            </div>
            <div class="message-content ${isStreaming ? 'streaming-text' : ''}" id="msg-content-${idx}" style="font-size:var(--fs-md);line-height:1.6">
              ${this._renderMarkdown(msg.content)}${isStreaming ? '<span class="cursor-blink"></span>' : ''}
            </div>
          </div>
          ${sources.length > 0 ? this._renderSourcesPanel(sources, '精排来源') : ''}
          ${!isStreaming ? this._renderFeedbackBar(idx, feedback) : ''}
        </div>
      </div>
    `;
  },

  _renderFeedbackBar(msgIdx, feedback, comment = '') {
    const upActive   = feedback === 'up'   ? 'accent' : '';
    const downActive = feedback === 'down' ? 'danger' : '';
    const showCommentBox = feedback === 'down' && !comment;
    const showThanks     = (feedback === 'up') || (feedback === 'down' && comment !== undefined && comment !== null && comment !== '__skip__');

    return `
      <div class="feedback-bar row wrap" data-msg-idx="${msgIdx}" style="gap:var(--sp-2);padding-left:40px">
        <span class="t3" style="font-size:var(--fs-xs)">对此回答：</span>
        <button class="icon-btn feedback-btn ${upActive}" style="width:26px;height:26px;font-size:13px" title="这个回答很有帮助" data-feedback-idx="${msgIdx}" data-feedback-value="1">👍</button>
        <button class="icon-btn feedback-btn ${downActive}" style="width:26px;height:26px;font-size:13px" title="这个回答需要改进" data-feedback-idx="${msgIdx}" data-feedback-value="0">👎</button>
        ${showThanks ? '<span class="badge ok">已反馈，感谢！</span>' : ''}
        ${showCommentBox ? `
          <div class="col" data-comment-idx="${msgIdx}" style="gap:var(--sp-2);width:100%;margin-top:var(--sp-2)">
            <textarea class="textarea" style="height:60px" placeholder="（可选）请简述问题所在，帮助我们改进……" maxlength="300" rows="2"></textarea>
            <div class="row" style="gap:var(--sp-2)">
              <button class="btn btn-sm btn-primary feedback-comment-submit" data-comment-idx="${msgIdx}">提交</button>
              <button class="btn btn-sm btn-ghost feedback-comment-skip" data-comment-idx="${msgIdx}">跳过</button>
            </div>
          </div>
        ` : ''}
      </div>
    `;
  },

  _renderSourcesPanel(sources, title, collapsed = true) {
    if (!sources || sources.length === 0) return '';
    const panelId = `src-panel-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    return `
      <div class="sources-panel glass" id="${panelId}" style="border-radius:var(--r-sm);margin-top:var(--sp-2);overflow:hidden;${collapsed ? 'max-height:36px' : ''}">
        <div class="sources-header row between" style="padding:var(--sp-2) var(--sp-3);cursor:pointer" onclick="var p=document.getElementById('${panelId}');if(p){p.style.maxHeight=p.style.maxHeight==='36px'?'':'36px'}">
          <span class="t3" style="font-size:var(--fs-xs)">🔍 ${this._escapeHTML(title)} (${sources.length})</span>
          <span class="t3">▼</span>
        </div>
        <div class="sources-list col" style="gap:var(--sp-2);padding:0 var(--sp-3) var(--sp-3)">
          ${sources.map((s, si) => `
            <div class="glass p4" data-source-idx="${si}">
              <div class="row between" style="gap:var(--sp-2)">
                <span class="badge ${s.source === 'keyword' ? '' : s.source === 'reranked' ? 'accent' : 'info'}">${this._escapeHTML(s.source || 'unknown')}</span>
                <span class="num t3" style="font-size:var(--fs-xs)">${typeof s.score === 'number' ? (s.score * 100).toFixed(1) + '%' : s.score}</span>
              </div>
              ${s.content ? `<p class="t2 mt2" style="font-size:var(--fs-sm)">${this._escapeHTML(s.content.slice(0, 200))}${s.content.length > 200 ? '…' : ''}</p>` : ''}
              ${s.chunk_text ? `<p class="t3 mt2 mono" style="font-size:var(--fs-xs)">${this._escapeHTML(s.chunk_text.slice(0, 200))}${s.chunk_text.length > 200 ? '…' : ''}</p>` : ''}
              ${s.metadata?.filename ? `<span class="badge mt2">📄 ${this._escapeHTML(s.metadata.filename)}</span>` : ''}
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
    const msgEl = document.querySelector(`.msg.ai[data-idx="${msgIdx}"]`);
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
            const panel = h.closest('.sources-panel');
            if (panel) {
              const isCollapsed = panel.style.maxHeight === '36px';
              panel.style.maxHeight = isCollapsed ? '' : '36px';
            }
          };
        });
      }
    }

    this._scrollToBottom();
  },

  _renderCompareResults() {
    const results = this.compareResults;
    const agentOrder = Object.keys(results);
    if (agentOrder.length === 0) return '<div class="glass"><div class="state"><div class="title">暂无对比结果</div></div></div>';

    return agentOrder.map(type => {
      const r = results[type];
      if (r.error) {
        return `
          <div class="glass card" data-agent="${type}" style="border-left:2px solid var(--danger)">
            <div class="row between mb4">
              <span class="badge">${this._agentLabel(type)}</span>
              <span class="badge danger">错误</span>
            </div>
            <p class="t2" style="font-size:var(--fs-sm)">${this._escapeHTML(r.error)}</p>
          </div>
        `;
      }
      return `
        <div class="glass card" data-agent="${type}">
          <div class="row between mb4">
            <span class="badge accent">${this._agentLabel(type)}</span>
            <div class="row" style="gap:6px">
              <span class="badge">⏱ ${r.processing_time ? r.processing_time.toFixed(0) + 'ms' : '—'}</span>
              <span class="badge info">📚 ${r.sources_count ?? 0}</span>
            </div>
          </div>
          <div style="font-size:var(--fs-sm);line-height:1.6">${this._renderMarkdown(r.content || '')}</div>
        </div>
      `;
    }).join('');
  },

  _buildCapabilitiesHint() {
    if (this.compareMode) return '';
    const agent = this.agents.find(a => a.type === this.selectedAgent);
    if (!agent || !agent.capabilities) return '';
    return `
      <div class="glass p4 row wrap" style="gap:6px;margin-bottom:var(--sp-4)">
        <span class="t3" style="font-size:var(--fs-xs)">能力：</span>
        ${agent.capabilities.map(c => `<span class="badge">${c}</span>`).join('')}
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
      const ok = await window.UI.confirm({
        title: '清空会话',
        message: '确定清空当前会话消息？',
        okText: '清空',
        danger: true
      });
      if (!ok) return;
      if (this.activeSession) {
        try {
          await AgentAPI.clearSession(this.activeSessionId);
        } catch (e) {
          // request() 已自动 toast 错误；后端未清空，保留本地消息保持一致
          return;
        }
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
    document.querySelectorAll('.sess[data-session-id]').forEach(item => {
      item.addEventListener('click', (e) => {
        const id = item.dataset.sessionId;
        if (id && id !== this.activeSessionId) {
          this._switchSession(id);
        }
      });
    });

    // 会话删除（线框 05 没有单独删除按钮，删除通过右键或滑动——这里暂保留 hover 删除逻辑用 UI.confirm）
    // 当前 _buildSessionList 没渲染删除按钮，删除走 _deleteSession 直接调用
  },

  _refreshKbBar() {
    // 圈 4：更新选择条右侧提示文字
    const bar = document.getElementById('agent-kb-bar');
    if (!bar) return;
    const hintEl = bar.querySelector('.kb-bar-hint');
    const selectedKb = this.knowledgeBases.find(kb => kb.id === this.selectedKbId);
    if (hintEl) {
      hintEl.textContent = selectedKb
        ? `已选：${selectedKb.kb_name} · Agent 将优先在此知识库中检索`
        : '全局模式 · Agent 将在全量数据中自由检索';
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

  /** Stage 3：渲染"帮助成长"补全卡片（检索失败引导，文档 06；圈 4 对齐线框 05 supplement 样式） */
  _renderSupplementCard(msgIdx) {
    const msgContentEl = document.getElementById(`msg-content-${msgIdx}`);
    if (!msgContentEl) return;
    const host = msgContentEl.parentElement;
    if (!host || host.querySelector('.supplement-card')) return; // 防重复

    const session = this.activeSession;
    const userQuery = (session?.messages?.[msgIdx - 1]?.role === 'user')
      ? session.messages[msgIdx - 1].content : '';

    const card = document.createElement('div');
    card.className = 'supplement';
    card.style.cssText = 'border-radius:var(--r-md);padding:var(--sp-4);background:var(--accent-soft);box-shadow:inset 0 1px 0 var(--glass-edge),0 0 24px var(--accent-glow);border:1px solid transparent;margin-top:var(--sp-3)';
    card.innerHTML = `
      <div class="row between">
        <b style="font-size:var(--fs-sm)">✦ 这个问题知识库还没有覆盖</b>
        <span class="badge accent">沉淀为记忆</span>
      </div>
      <p class="t2 mt2" style="font-size:var(--fs-sm)">把标准答案补充进来，下次直接命中 FAQ 秒回（写入默认私有库，候选满阈值命中自动升格）。</p>
      <div class="row mt4">
        <input type="text" id="supp-q-${msgIdx}" class="input grow" style="background:rgba(0,0,0,.15)" value="${this._escapeHTML(userQuery)}" placeholder="问题" />
        <input type="text" id="supp-a-${msgIdx}" class="input grow" style="background:rgba(0,0,0,.15)" placeholder="补充答案要点…" />
        <button class="btn btn-primary btn-sm supplement-submit" data-msg-idx="${msgIdx}" style="height:38px">提交补全</button>
      </div>
      <button class="btn btn-sm btn-ghost supplement-dismiss" style="margin-top:var(--sp-2)">忽略</button>
    `;
    card.querySelector('.supplement-submit')?.addEventListener('click', () => this.submitSupplement(msgIdx));
    card.querySelector('.supplement-dismiss')?.addEventListener('click', () => card.remove());
    host.appendChild(card);
  },

  /** Stage 3：提交补全（写入路径由后端 fork/PR 规则判定） */
  async submitSupplement(msgIdx) {
    const qEl = document.getElementById(`supp-q-${msgIdx}`);
    const aEl = document.getElementById(`supp-a-${msgIdx}`);
    const question = (qEl?.value || '').trim();
    const answer = (aEl?.value || '').trim();
    if (!question || !answer) {
      window.App.showToast('问题和答案都需要填写', 'error');
      return;
    }
    try {
      const result = await window.FaqAPI.supplement({
        question, answer, kb_id: this.selectedKbId,
      });
      window.App.showToast(result.message || '已记录', 'success');
      const card = qEl.closest('.supplement');
      if (card) card.remove();
    } catch (e) { /* request() 已自动 toast */ }
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
              break;

            case 'chunk':
              if (data.chunk) {
                fullContent += data.chunk;
                session.messages[msgIdx].content = fullContent;
                if (msgContentEl) {
                  // 05a 批次 2：流式渲染节流 — 每 100ms 最多一次 marked.parse 全量重渲，
                  // 避免每个 token 都 innerHTML 全量重排（长回答卡顿）；流结束后终渲兜底
                  const now = performance.now();
                  if (this._lastRenderTs === undefined || now - this._lastRenderTs >= 100) {
                    this._lastRenderTs = now;
                    msgContentEl.innerHTML = this._renderMarkdown(fullContent) + '<span class="cursor-blink"></span>';
                    this._scrollToBottom();
                  }
                }
              }
              // Stage 3：捕获 FAQ 命中 / 补全引导标记（StreamChunk.to_sse 把 metadata 展开到顶层）
              if (data.suggest_supplement) {
                session.messages[msgIdx]._suggestSupplement = true;
              }
              if (data.faq_hit) {
                session.messages[msgIdx]._faqHit = true;
              }
              break;

            case 'done':
              // 流结束 — 标记状态 + 兜底渲染来源面板
              session.messages[msgIdx]._streaming = false;
              session.messages[msgIdx].content = fullContent || '（无回复内容）';
              this._lastRenderTs = undefined; // 重置节流计时，下一轮流式重新计
              // done 事件中的 trace_id 比 connected 更可靠（CallbackHandler 执行后 trace 才确定）
              if (data.trace_id) {
                session.messages[msgIdx].trace_id = data.trace_id;
              }
              if (msgContentEl) {
                msgContentEl.innerHTML = this._renderMarkdown(fullContent || '（无回复内容）');
                msgContentEl.classList.remove('streaming-text');
                msgContentEl.querySelectorAll('.cursor-blink').forEach(c => c.remove());
              }
              // 【关键兜底】流结束后强制渲染来源面板
              // 防止 retrieved/reranked 事件丢失或时序问题时用户看不到来源
              const srcCount = (session.messages[msgIdx].sources?.length || 0)
                            + (session.messages[msgIdx].rawSources?.length || 0);
              if (srcCount > 0) {
                this._renderSourcePanelOnly(msgIdx);
              }
              // Stage 3：检索失败引导补全（后端标记为主，关键词为兜底——
              // 防止 suggest_supplement 标记在链路中丢失时入口完全消失）
              const msg = session.messages[msgIdx];
              if (msg._suggestSupplement || /知识库中(没有|未检索到)|没有检索到相关/.test(fullContent || '')) {
                this._renderSupplementCard(msgIdx);
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
      <div class="glass"><div class="state">
        <div class="glyph float-anim">⚖</div>
        <div class="title">正在并行运行 ${this.agents.length} 个 Agent</div>
        <div class="progress indeterminate" style="width:120px;margin-top:8px"><i></i></div>
      </div></div>
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
        <div class="glass p4 row between"><span class="t3" style="font-size:var(--fs-xs)">总耗时</span><b class="num">${totalTime.toFixed(0)}ms</b></div>
      ` : '') + this._renderCompareResults();
    } catch (err) {
      resultsEl.innerHTML = `<div class="glass"><div class="state"><div class="glyph" style="color:var(--danger)">✕</div><div class="title">对比失败</div><p class="desc">${this._escapeHTML(err.message)}</p></div></div>`;
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
    const msgEl = document.querySelector(`.msg.ai[data-idx="${msgIdx}"]`);
    let comment = null;
    if (!skip && msgEl) {
      const textarea = msgEl.querySelector('.feedback-bar textarea, .textarea');
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
    } catch (err) {
      // 提交失败：回滚 UI 到未反馈状态（避免"已反馈"的虚假成功）+ 明确提示
      console.warn('[AgentPage] 反馈提交失败:', err.message);
      window.App.showToast('反馈提交失败，请稍后重试', 'error');
      msg.feedback = null;
      msg.feedbackComment = null;
      this._updateFeedbackBar(msgIdx, null, null);
    }
  },

  _updateFeedbackBar(msgIdx, feedback, comment) {
    /**
     * 局部更新指定消息的反馈栏，不重渲染整个消息列表
     * feedback : null | 'up' | 'down'
     * comment  : null（点踩展开评论框中） | '__skip__'（明确跳过） | string（已提交） | 'ok'（点赞已提交）
     */
    const msgEl = document.querySelector(`.msg.ai[data-idx="${msgIdx}"]`);
    if (!msgEl) return;

    const barEl = msgEl.querySelector('.feedback-bar');
    if (!barEl) {
      const bubble = msgEl.querySelector('.bubble');
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
