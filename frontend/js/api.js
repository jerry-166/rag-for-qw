/**
 * API 服务层 - 封装所有后端接口调用
 */
const API_BASE = 'http://localhost:8003';

// Token 管理
const TokenManager = {
  get() { return localStorage.getItem('rag_token'); },
  set(token) { localStorage.setItem('rag_token', token); },
  clear() { localStorage.removeItem('rag_token'); localStorage.removeItem('rag_user'); },
};

// 用户信息管理
const UserManager = {
  get() {
    try { return JSON.parse(localStorage.getItem('rag_user') || 'null'); } catch { return null; }
  },
  set(user) { localStorage.setItem('rag_user', JSON.stringify(user)); },
  clear() { localStorage.removeItem('rag_user'); },
};

// 通用请求函数
async function request(path, options = {}) {
  const token = TokenManager.get();
  const headers = { ...options.headers };

  if (token && !options._skipAuth) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  // 如果不是 FormData 且不是 URLSearchParams 且没有明确指定 Content-Type，则设置 Content-Type
  if (!(options.body instanceof FormData) && !(options.body instanceof URLSearchParams) && !headers['Content-Type']) {
    if (options.body) headers['Content-Type'] = 'application/json';
  }

  try {
    const resp = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
    });

    // 401 → 跳转登录
    if (resp.status === 401) {
      TokenManager.clear();
      window.App && window.App.navigate('auth');
      throw new Error('登录已过期，请重新登录');
    }

    // 根据responseType处理响应
    if (options.responseType === 'blob') {
      const blob = await resp.blob();
      if (!resp.ok) {
        throw new Error(`请求失败 (${resp.status})`);
      }
      return blob;
    } else {
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || `请求失败 (${resp.status})`);
      }
      return data;
    }
  } catch (err) {
    if (err.name === 'TypeError' && err.message.includes('fetch')) {
      throw new Error('无法连接到服务器，请检查后端是否已启动');
    }
    throw err;
  }
}

// ===== Auth API =====
const AuthAPI = {
  async login(username, password) {
    const form = new URLSearchParams();
    form.append('username', username);
    form.append('password', password);
    return request('/api/auth/login', {
      method: 'POST',
      body: form,
      _skipAuth: true,
    });
  },

  async register(username, email, password) {
    return request('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, email, password }),
      _skipAuth: true,
    });
  },
};

// ===== 知识库 API =====
const KnowledgeBaseAPI = {
  async list() {
    return request('/api/knowledge-bases');
  },

  async create(kb_name, description = '') {
    return request('/api/knowledge-bases', {
      method: 'POST',
      body: JSON.stringify({ kb_name, description }),
    });
  },

  async update(kb_id, kb_name, description = '') {
    return request(`/api/knowledge-bases/${kb_id}`, {
      method: 'PUT',
      body: JSON.stringify({ kb_name, description }),
    });
  },

  async delete(kb_id) {
    return request(`/api/knowledge-bases/${kb_id}`, { method: 'DELETE' });
  },
};

// ===== 文档 API =====
const DocumentAPI = {
  async list(kb_id = null) {
    const q = kb_id ? `?kb_id=${kb_id}` : '';
    return request(`/api/documents${q}`);
  },

  async upload(file, kb_id = null) {
    const form = new FormData();
    form.append('file', file);
    if (kb_id) form.append('kb_id', kb_id);
    return request('/api/upload/pdf', { method: 'POST', body: form });
  },

  async getMarkdown(file_id) {
    return request(`/api/markdown/${file_id}`);
  },

  async split(file_id) {
    return request(`/api/process/split/${file_id}`, { method: 'POST' });
  },

  async generate(file_id) {
    return request(`/api/process/generate/${file_id}`, { method: 'POST' });
  },

  async importToMilvus(file_id) {
    return request(`/api/process/import/${file_id}`, { method: 'POST' });
  },

  async fullProcess(file_id) {
    return request(`/api/process/full/${file_id}`, { method: 'POST' });
  },

  async getResult(file_id) {
    return request(`/api/process/result/${file_id}`);
  },

  async getPreview(file_id) {
    return request(`/api/documents/${file_id}/preview`);
  },

  async delete(file_id) {
    return request(`/api/documents/${file_id}`, { method: 'DELETE' });
  },

  async getPDF(file_id) {
    return request(`/api/pdf/${file_id}`, { 
      method: 'GET',
      responseType: 'blob' 
    });
  },

  async getStatsOverview() {
    return request('/api/stats/overview');
  },
};

// ===== Agent API =====
const AgentAPI = {
  /**
   * 列出所有已注册的 Agent
   * @returns {Promise<{agents: Array, default: string}>}
   */
  async list() {
    return request('/api/agent/list');
  },

  /**
   * 查询 Agent 预热状态
   * @returns {Promise<{status: string, ready: boolean, label: string, elapsed_s?: number, error?: string}>}
   */
  async preheatStatus() {
    return request('/api/agent/preheat-status');
  },

  /**
   * Agent 服务健康检查
   * @returns {Promise<{registry: string, agents: object}>}
   */
  async health() {
    return request('/api/agent/health');
  },

  /**
   * 单 Agent 对话（非流式）
   * @param {Object} opts
   * @param {string}   opts.query            - 用户查询
   * @param {string}   [opts.agent_type='claw'] - simple | advanced | claw
   * @param {string}   [opts.session_id]      - 会话 ID
   * @param {Array}    [opts.chat_history]    - 对话历史 [{role, content}]
   * @param {number}   [opts.knowledge_base_id]
   */
  async chat({ query, agent_type = 'claw', session_id = null, chat_history = [], knowledge_base_id = null }) {
    return request('/api/agent/chat', {
      method: 'POST',
      body: JSON.stringify({
        query,
        agent_type,
        session_id,
        chat_history,
        ...(knowledge_base_id ? { knowledge_base_id } : {}),
      }),
    });
  },

  /**
   * 流式对话（SSE）
   * 返回一个 ReadableStream reader，消费者可通过 read() 逐条获取 SSE 行
   *
   * @param {Object} opts
   * @param {string}   opts.query
   * @param {string}   [opts.agent_type='claw']
   * @param {string}   [opts.session_id]
   * @param {Array}    [opts.chat_history]
   * @param {number}   [opts.knowledge_base_id]
   * @returns {Promise<ReadableStream>}  SSE 流
   */
  async chatStream({ query, agent_type = 'claw', session_id = null, chat_history = [], knowledge_base_id = null }) {
    const token = TokenManager.get();
    const body = {
      query,
      agent_type,
      session_id,
      chat_history,
    };
    if (knowledge_base_id) body.knowledge_base_id = knowledge_base_id;

    const resp = await fetch(`${API_BASE}/api/agent/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    });

    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.detail || `请求失败 (${resp.status})`);
    }

    return resp.body;
  },

  /**
   * 多 Agent 对比
   * @param {Object} opts
   * @param {string}   opts.query
   * @param {string[]} [opts.agent_types]  - 指定类型，不传则对比全部
   * @param {string}   [opts.session_id]
   * @param {Array}    [opts.chat_history]
   * @returns {Promise<{status, comparison: {query, total_time_ms, results}}>}
   */
  async compare({ query, agent_types = null, session_id = null, chat_history = [] }) {
    return request('/api/agent/compare', {
      method: 'POST',
      body: JSON.stringify({ query, agent_types, session_id, chat_history }),
    });
  },

  /**
   * 获取会话历史
   * @param {string} sessionId
   * @param {number} [limit=20]
   */
  async getHistory(sessionId, limit = 20) {
    return request(`/api/agent/session/${encodeURIComponent(sessionId)}/history?limit=${limit}`);
  },

  /**
   * 列出所有历史会话
   * @param {number} [limit=50]
   */
  async listSessions(limit = 50) {
    return request(`/api/agent/sessions?limit=${limit}`);
  },

  /**
   * 清空会话（只清消息，保留文件）
   * @param {string} sessionId
   */
  async clearSession(sessionId) {
    return request(`/api/agent/session/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
  },

  /**
   * 彻底删除会话文件
   * @param {string} sessionId
   */
  async deleteSession(sessionId) {
    return request(`/api/agent/session/${encodeURIComponent(sessionId)}?action=delete`, { method: 'DELETE' });
  },
};

// ===== 检索 API =====
const SearchAPI = {
  /**
   * @param {Object} opts
   * @param {string} opts.query
   * @param {number} [opts.limit=5]
   * @param {number|null} [opts.knowledge_base_id]
   * @param {boolean} [opts.use_rerank=true]  是否启用 Reranker 精排
   * @param {Object|null} [opts.metadata_filter]
   */
  _buildBody(opts) {
    const { query, limit = 5, knowledge_base_id = null, use_rerank = true, metadata_filter = null } = opts;
    const body = { query, limit };
    if (knowledge_base_id) body.knowledge_base_id = knowledge_base_id;
    if (use_rerank !== undefined) body.use_rerank = use_rerank;
    if (metadata_filter) body.metadata_filter = metadata_filter;
    return JSON.stringify(body);
  },

  async vectorSearch(query, limit = 5, knowledge_base_id = null, options = {}) {
    const opts = { query, limit, knowledge_base_id, ...options };
    return request('/api/milvus/query', {
      method: 'POST',
      body: this._buildBody(opts),
    });
  },

  async keywordSearch(query, limit = 5, knowledge_base_id = null, options = {}) {
    const opts = { query, limit, knowledge_base_id, ...options };
    return request('/api/elasticsearch/search', {
      method: 'POST',
      body: this._buildBody(opts),
    });
  },

  async hybridSearch(query, limit = 5, knowledge_base_id = null, options = {}) {
    const opts = { query, limit, knowledge_base_id, ...options };
    return request('/api/hybrid/search', {
      method: 'POST',
      body: this._buildBody(opts),
    });
  },
};
