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

// ===== 检索 API =====
const SearchAPI = {
  async vectorSearch(query, limit = 5, knowledge_base_id = null) {
    return request('/api/milvus/query', {
      method: 'POST',
      body: JSON.stringify({ query, limit, knowledge_base_id }),
    });
  },

  async keywordSearch(query, limit = 5, knowledge_base_id = null) {
    return request('/api/elasticsearch/search', {
      method: 'POST',
      body: JSON.stringify({ query, limit, knowledge_base_id }),
    });
  },

  async hybridSearch(query, limit = 5, knowledge_base_id = null) {
    return request('/api/hybrid/search', {
      method: 'POST',
      body: JSON.stringify({ query, limit, knowledge_base_id }),
    });
  },
};
