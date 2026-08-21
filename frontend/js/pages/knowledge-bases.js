/**
 * 知识库页面
 */
const KnowledgeBasesPage = {
  async render() {
    const container = document.getElementById('page-container');
    container.innerHTML = `
      <div class="page-header">
        <div>
          <h1 class="page-title">知识库管理</h1>
          <p class="page-desc">管理您的知识库，上传和组织文档</p>
        </div>
        <button class="btn btn-primary" id="create-kb-btn">
          <span>+ 创建知识库</span>
        </button>
      </div>
      <div id="kb-list" class="kb-grid">
        <!-- 知识库列表将在这里渲染 -->
        <div class="loading-state">
          <div class="loading-spinner"></div>
          <p>加载中...</p>
        </div>
      </div>
    `;
    
    await this.loadKnowledgeBases();
    this.initEvents();
  },

  async loadKnowledgeBases() {
    const container = document.getElementById('kb-list');
    try {
      // 兼容性检查：确保 API 已挂载
      if (!window.KnowledgeBaseAPI || typeof window.KnowledgeBaseAPI.list !== 'function') {
        throw new Error('KnowledgeBaseAPI 未就绪，请刷新页面重试');
      }
      const response = await window.KnowledgeBaseAPI.list();
      // 确保 response 存在且有 knowledge_bases 属性
      if (!response || !Array.isArray(response.knowledge_bases)) {
        throw new Error('Invalid response format');
      }
      this.knowledgeBases = response.knowledge_bases;
      
      if (this.knowledgeBases.length === 0) {
        container.innerHTML = `
          <div class="empty-state">
            <div class="empty-icon">🗂️</div>
            <div class="empty-title">暂无知识库</div>
            <div class="empty-desc">点击右上角按钮创建您的第一个知识库</div>
          </div>
        `;
        return;
      }
      
      container.innerHTML = this.knowledgeBases.map(kb => `
        <div class="kb-card" data-kb-id="${kb.id}">
          <div class="kb-card-header">
            <div class="kb-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6c0-1.66 3.58-3 8-3s8 1.34 8 3-3.58 3-8 3-8-1.34-8-3z"/><path d="M4 6v6c0 1.66 3.58 3 8 3s8-1.34 8-3V6"/><path d="M4 12v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6"/></svg>
            </div>
            <div class="kb-actions">
              <button class="icon-btn" title="分享（协作）" aria-label="分享" onclick="KnowledgeBasesPage.showShareModal(${kb.id})">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/></svg>
              </button>
              <button class="icon-btn" title="克隆为我的副本" aria-label="克隆" onclick="KnowledgeBasesPage.cloneKnowledgeBase(${kb.id})">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              </button>
              <button class="icon-btn" title="编辑" aria-label="编辑" onclick="KnowledgeBasesPage.editKnowledgeBase(${kb.id})">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z"/></svg>
              </button>
              <button class="icon-btn" title="删除" aria-label="删除" onclick="KnowledgeBasesPage.deleteKnowledgeBase(${kb.id})">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6"/></svg>
              </button>
            </div>
          </div>
          <div class="kb-name">${this._esc(kb.kb_name)}</div>
          <div class="kb-desc">${this._esc(kb.description) || '无描述'}</div>
          <div class="kb-badges">${this._kbBadges(kb)}</div>
          <div class="kb-meta">
            <span>更新于 ${new Date(kb.created_at).toLocaleDateString()}</span>
          </div>
        </div>
      `).join('') + `
        <div class="kb-card kb-card-add" onclick="KnowledgeBasesPage.showCreateModal()" title="创建知识库">
          <div class="add-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>
          </div>
          <div class="add-label">创建知识库</div>
        </div>
      `;
      
      // 添加点击事件
      this.knowledgeBases.forEach(kb => {
        const card = document.querySelector(`.kb-card[data-kb-id="${kb.id}"]`);
        if (card) {
          card.addEventListener('click', (e) => {
            if (!e.target.closest('.kb-actions')) {
              window.App.navigate('documents', { kb_id: kb.id });
            }
          });
        }
      });
    } catch (error) {
      console.error('加载知识库失败:', error);
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">❌</div>
          <div class="empty-title">加载失败</div>
          <div class="empty-desc">${error.message || '无法加载知识库列表'}</div>
          <button class="btn btn-secondary" onclick="KnowledgeBasesPage.loadKnowledgeBases()">
            重新加载
          </button>
        </div>
      `;
    }
  },

  initEvents() {
    document.getElementById('create-kb-btn').addEventListener('click', () => {
      this.showCreateModal();
    });
  },

  showCreateModal(kb = null) {
    const isEdit = !!kb;
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.innerHTML = `
      <div class="modal">
        <div class="modal-header">
          <h3 class="modal-title">${isEdit ? '编辑知识库' : '创建知识库'}</h3>
          <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">×</button>
        </div>
        <div class="modal-body">
          <div class="form-field">
            <label>知识库名称</label>
            <input type="text" id="kb-name" placeholder="输入知识库名称" value="${kb?.kb_name || ''}" required />
          </div>
          <div class="form-field">
            <label>描述（可选）</label>
            <textarea id="kb-description" placeholder="输入知识库描述" rows="3">${kb?.description || ''}</textarea>
          </div>
          <div class="form-field">
            <label>切割策略（默认跟随全局）</label>
            <select id="kb-chunk-strategy">
              <option value="" ${!kb?.chunk_strategy ? 'selected' : ''}>跟随全局配置</option>
              <option value="auto" ${kb?.chunk_strategy === 'auto' ? 'selected' : ''}>自动探测</option>
              <option value="markdown" ${kb?.chunk_strategy === 'markdown' ? 'selected' : ''}>Markdown 标题切割</option>
              <option value="recursive" ${kb?.chunk_strategy === 'recursive' ? 'selected' : ''}>递归字符切割</option>
            </select>
          </div>
          <div class="form-field">
            <label>增强生成（勾选启用，默认跟随全局）</label>
            <label class="kb-enhancer-item">
              <input type="checkbox" id="kb-enh-subq" ${this._enhChecked(kb, 'sub_question')}> 子问题生成
            </label>
            <label class="kb-enhancer-item">
              <input type="checkbox" id="kb-enh-summary" ${this._enhChecked(kb, 'summary')}> 摘要生成
            </label>
            <div class="form-hint">两者均不勾选 = 该库走纯原文检索（不消耗 LLM token）</div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" onclick="this.closest('.modal-overlay').remove()">
            取消
          </button>
          <button class="btn btn-primary" onclick="KnowledgeBasesPage.${isEdit ? 'updateKnowledgeBase' : 'createKnowledgeBase'}(${kb?.id || 'null'})">
            ${isEdit ? '保存' : '创建'}
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  },

  _enhChecked(kb, name) {
    // 编辑态按 KB 已配置回显；新建态默认勾选（跟随全局默认双开）
    if (!kb || kb.enhancers == null) return 'checked';
    return kb.enhancers.includes(name) ? 'checked' : '';
  },

  _collectStrategy() {
    const strategy = document.getElementById('kb-chunk-strategy').value || null;
    const enhancers = [];
    if (document.getElementById('kb-enh-subq').checked) enhancers.push('sub_question');
    if (document.getElementById('kb-enh-summary').checked) enhancers.push('summary');
    return { strategy, enhancers };
  },

  async createKnowledgeBase() {
    const name = document.getElementById('kb-name').value.trim();
    const description = document.getElementById('kb-description').value.trim();

    if (!name) {
      window.App.showToast('请输入知识库名称', 'error');
      return;
    }

    const { strategy, enhancers } = this._collectStrategy();
    try {
      await window.KnowledgeBaseAPI.create(name, description, strategy, enhancers);
      window.App.showToast('知识库创建成功', 'success');
      document.querySelector('.modal-overlay').remove();
      this.loadKnowledgeBases();
    } catch (error) {
      window.App.showToast('创建失败: ' + error.message, 'error');
    }
  },

  editKnowledgeBase(kbId) {
    const kb = this.knowledgeBases.find(kb => kb.id === kbId);
    if (kb) {
      this.showCreateModal(kb);
    }
  },

  async deleteKnowledgeBase(kbId) {
    if (!confirm('确定要删除这个知识库吗？')) {
      return;
    }
    
    try {
      await window.KnowledgeBaseAPI.delete(kbId);
      window.App.showToast('知识库删除成功', 'success');
      this.loadKnowledgeBases();
    } catch (error) {
      window.App.showToast('删除失败: ' + error.message, 'error');
    }
  },

  async updateKnowledgeBase(kbId) {
    const name = document.getElementById('kb-name').value.trim();
    const description = document.getElementById('kb-description').value.trim();

    if (!name) {
      window.App.showToast('请输入知识库名称', 'error');
      return;
    }

    const { strategy, enhancers } = this._collectStrategy();
    try {
      await window.KnowledgeBaseAPI.update(kbId, name, description, strategy, enhancers);
      window.App.showToast('知识库更新成功', 'success');
      document.querySelector('.modal-overlay').remove();
      this.loadKnowledgeBases();
    } catch (error) {
      window.App.showToast('更新失败: ' + error.message, 'error');
    }
  },

  /* ==================== Stage 3：分享 / 克隆（fork-PR 协作） ==================== */

  async showShareModal(kbId) {
    const kb = this.knowledgeBases.find(k => k.id === kbId);
    if (!kb) return;

    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.innerHTML = `
      <div class="modal">
        <div class="modal-header">
          <h3 class="modal-title">分享「${this._esc(kb.kb_name)}」</h3>
          <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">×</button>
        </div>
        <div class="modal-body">
          <div class="form-field">
            <label>分享给用户（用户名）</label>
            <input type="text" id="share-username" placeholder="输入用户名" />
          </div>
          <div class="form-field">
            <label class="kb-share-toggle" for="share-can-write">
              <span class="switch" aria-hidden="true"></span>
              <input type="checkbox" id="share-can-write" checked />
              允许直接写入（关闭则对方仅能提交 PR，由我审核）
            </label>
          </div>
          <div class="form-field">
            <label>已分享列表</label>
            <div id="share-list" style="font-size: .85rem; color: var(--text2);">加载中...</div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" onclick="this.closest('.modal-overlay').remove()">关闭</button>
          <button class="btn btn-primary" onclick="KnowledgeBasesPage.submitShare(${kbId})">分享</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    this._loadShareList(kbId);
  },

  async _loadShareList(kbId) {
    const el = document.getElementById('share-list');
    if (!el) return;
    try {
      const resp = await window.FaqAPI.listShares(kbId);
      const items = resp.items || [];
      if (!items.length) {
        el.innerHTML = '<span style="color: var(--text3);">尚未分享给任何人</span>';
        return;
      }
      el.innerHTML = items.map(s => `
        <div style="display: flex; align-items: center; gap: 8px; margin: 4px 0;" class="kb-share-row">
          <span style="flex: 1;">${this._esc(s.shared_to_username || `用户#${s.shared_to_user_id}`)}</span>
          ${s.can_write_directly
            ? '<span class="badge badge-green">可写入</span>'
            : '<span class="badge badge-gray">仅 PR</span>'}
          ${s.shared_to_username
            ? `<button class="btn btn-sm btn-ghost"
                 onclick="KnowledgeBasesPage.unshare(${kbId}, '${this._esc(s.shared_to_username)}')">取消分享</button>`
            : ''}
        </div>`).join('');
    } catch (e) {
      el.innerHTML = `<span style="color: var(--red);">加载失败: ${this._esc(e.message)}</span>`;
    }
  },

  async submitShare(kbId) {
    const username = document.getElementById('share-username').value.trim();
    const canWrite = document.getElementById('share-can-write').checked;
    if (!username) {
      window.App.showToast('请输入用户名', 'error');
      return;
    }
    try {
      await window.FaqAPI.shareKb({ kb_id: kbId, username, can_write_directly: canWrite });
      window.App.showToast(`已分享给 ${username}`, 'success');
      this._loadShareList(kbId);
    } catch (e) {
      window.App.showToast('分享失败: ' + e.message, 'error');
    }
  },

  async unshare(kbId, username) {
    try {
      await window.FaqAPI.unshareKb({ kb_id: kbId, username });
      window.App.showToast('已取消分享', 'success');
      this._loadShareList(kbId);
    } catch (e) {
      window.App.showToast('取消失败: ' + e.message, 'error');
    }
  },

  async cloneKnowledgeBase(kbId) {
    const kb = this.knowledgeBases.find(k => k.id === kbId);
    const name = prompt('克隆副本名称（留空使用默认名）：',
      kb ? `${kb.kb_name}（克隆）` : '');
    if (name === null) return; // 用户取消
    try {
      const result = await window.FaqAPI.cloneKb(kbId, name.trim() || null);
      window.App.showToast(`克隆成功（文档 ${result.vectors?.chunks ?? '-'} 个向量已搬运）`, 'success');
      this.loadKnowledgeBases();
    } catch (e) {
      window.App.showToast('克隆失败: ' + e.message, 'error');
    }
  },

  _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  },

  /* 圈 2：KB 卡片策略徽章（线框 01：策略语义上卡片级） */
  _kbBadges(kb) {
    const badges = [];
    // 切割策略：未配置 = 跟随全局；配置了 auto = "auto 切割"
    const strategy = kb.chunk_strategy;
    badges.push(strategy
      ? `<span class="badge badge-info">${strategy === 'auto' ? 'auto 切割' : this._esc(strategy)}</span>`
      : `<span class="badge badge-gray">跟随全局</span>`);
    // 增强器：sub_question + summary → "子问题+摘要"；部分 → 单项；无 → "纯原文"
    const enh = kb.enhancers == null ? null : kb.enhancers;
    if (enh && enh.includes('sub_question') && enh.includes('summary')) {
      badges.push('<span class="badge badge-accent">子问题+摘要</span>');
    } else if (enh && enh.length) {
      badges.push(`<span class="badge badge-accent">${enh.includes('sub_question') ? '子问题' : '摘要'}</span>`);
    } else if (enh && enh.length === 0) {
      badges.push('<span class="badge badge-gray">纯原文</span>');
    }
    return badges.join('');
  }
};

window.KnowledgeBasesPage = KnowledgeBasesPage;