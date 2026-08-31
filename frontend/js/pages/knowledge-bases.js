/**
 * 知识库页面
 */
const KnowledgeBasesPage = {
  async render() {
    const container = document.getElementById('page-container');
    container.innerHTML = `
      <div class="row between mb6">
        <div>
          <h1 class="h-title">知识库管理</h1>
          <p class="t2 mt2" style="font-size:var(--fs-sm)">组织你的知识空间：上传文档、配置策略、协作共享</p>
        </div>
        <div class="row" style="gap:var(--sp-2)">
          <input type="search" class="input" id="kb-search" style="width:200px;height:34px" placeholder="搜索知识库…" />
          <button class="btn btn-primary" id="create-kb-btn">＋ 创建知识库</button>
        </div>
      </div>
      <div id="kb-list" class="grid kb">
        <div class="skeleton" style="height:120px"></div>
      </div>
    `;

    await this.loadKnowledgeBases();
    this.initEvents();
  },

  async loadKnowledgeBases() {
    const container = document.getElementById('kb-list');
    try {
      if (!window.KnowledgeBaseAPI || typeof window.KnowledgeBaseAPI.list !== 'function') {
        throw new Error('KnowledgeBaseAPI 未就绪，请刷新页面重试');
      }
      const response = await window.KnowledgeBaseAPI.list();
      if (!response || !Array.isArray(response.knowledge_bases)) {
        throw new Error('Invalid response format');
      }
      this.knowledgeBases = response.knowledge_bases;
      this.knowledgeBases.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
      this._renderKbList();
    } catch (error) {
      console.error('加载知识库失败:', error);
      container.innerHTML = `
        <div class="glass card center" style="padding:var(--sp-10)">
          <div class="glyph" style="font-size:32px;color:var(--danger)">✕</div>
          <p class="mt2" style="font-weight:600">加载失败</p>
          <p class="t2 mt2" style="font-size:var(--fs-sm)">${error.message || '无法加载知识库列表'}</p>
          <button class="btn btn-sm mt4" onclick="KnowledgeBasesPage.loadKnowledgeBases()">重新加载</button>
        </div>
      `;
    }
  },

  _renderKbList() {
    const container = document.getElementById('kb-list');
    if (!container) return;
    const term = (document.getElementById('kb-search')?.value || '').toLowerCase();
    const filtered = term
      ? this.knowledgeBases.filter(kb => (kb.kb_name || '').toLowerCase().includes(term) || (kb.description || '').toLowerCase().includes(term))
      : this.knowledgeBases;

    if (filtered.length === 0) {
      container.innerHTML = `
        <div class="glass card center" style="padding:var(--sp-10)">
          <div class="glyph" style="font-size:32px">${term ? '🔍' : '🗂️'}</div>
          <p class="mt2" style="font-weight:600">${term ? '无匹配结果' : '暂无知识库'}</p>
          <p class="t2 mt2" style="font-size:var(--fs-sm)">${term ? '尝试调整搜索关键词' : '点击右上角按钮创建您的第一个知识库'}</p>
        </div>
      `;
      return;
    }

    container.innerHTML = filtered.map(kb => {
      // is_owner===false 时为"共享给我的库"：隐藏 编辑/删除/分享（后端仅 owner/admin 可写，点击必 403），仅保留克隆（可读即可克隆）与查看
      const isOwner = kb.is_owner !== false;
      const manageBtns = isOwner ? `
            <button class="icon-btn" title="分享（协作）" aria-label="分享" onclick="KnowledgeBasesPage.showShareModal(${kb.id})">🤝</button>
            <button class="icon-btn" title="编辑" aria-label="编辑" onclick="KnowledgeBasesPage.editKnowledgeBase(${kb.id})">✎</button>
            <button class="icon-btn" title="删除" aria-label="删除" onclick="KnowledgeBasesPage.deleteKnowledgeBase(${kb.id})">🗑</button>` : '';
      const sharedBadge = isOwner ? '' : `<span style="font-size:var(--fs-xs);padding:2px 8px;border-radius:999px;background:var(--accent-soft);color:var(--text-2)">共享给我的</span>`;
      return `
      <div class="glass card card-hover" data-kb-id="${kb.id}">
        <div class="row between">
          <span class="brand-mark" style="width:38px;height:38px">📚</span>
          <div class="row" style="gap:2px">
            ${manageBtns}
            <button class="icon-btn" title="克隆为我的副本" aria-label="克隆" onclick="KnowledgeBasesPage.cloneKnowledgeBase(${kb.id})">⧉</button>
          </div>
        </div>
        <h3 class="mt4" style="font-size:var(--fs-lg);font-weight:620">${sharedBadge}${this._esc(kb.kb_name)}</h3>
        <p class="t2 mt2" style="font-size:var(--fs-sm)">${this._esc(kb.description) || '无描述'}</p>
        <div class="row mt4 wrap" style="gap:6px">${this._kbBadges(kb)}</div>
        <p class="t3 mt4" style="font-size:var(--fs-xs)">更新于 ${new Date(kb.created_at).toLocaleDateString()}</p>
      </div>
    `;}).join('') + `
      <button class="glass card card-hover center" style="border-style:dashed;color:var(--text-2);cursor:pointer;font:inherit" onclick="KnowledgeBasesPage.showCreateModal()" title="创建知识库">
        <div style="font-size:28px">＋</div>
        <p class="mt2">创建知识库</p>
      </button>
    `;

    filtered.forEach(kb => {
      const card = container.querySelector(`.glass.card[data-kb-id="${kb.id}"]`);
      if (card) {
        card.addEventListener('click', (e) => {
          if (!e.target.closest('.icon-btn')) {
            window.App.navigate('documents', { kb_id: kb.id });
          }
        });
      }
    });
  },

  initEvents() {
    document.getElementById('create-kb-btn').addEventListener('click', () => {
      this.showCreateModal();
    });
    const searchEl = document.getElementById('kb-search');
    if (searchEl) searchEl.addEventListener('input', () => this._renderKbList());
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
    this._bindModalClose(modal);
  },

  _bindModalClose(overlay) {
    const close = () => overlay.remove();
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) close();
    });
    const onKey = (e) => { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', onKey); } };
    document.addEventListener('keydown', onKey);
    const observer = new MutationObserver(() => {
      if (!document.body.contains(overlay)) {
        document.removeEventListener('keydown', onKey);
        observer.disconnect();
      }
    });
    observer.observe(document.body, { childList: true });
  },

  _enhChecked(kb, name) {
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
    if (!name) { window.App.showToast('请输入知识库名称', 'error'); return; }
    const { strategy, enhancers } = this._collectStrategy();
    const done = window.btnLoading(document.querySelector('.modal-overlay .btn-primary'), '创建中…');
    try {
      await window.KnowledgeBaseAPI.create(name, description, strategy, enhancers);
      window.App.showToast('知识库创建成功', 'success');
      document.querySelector('.modal-overlay').remove();
      this.loadKnowledgeBases();
    } catch (error) { this._toastWriteError(error); }
    finally { done(); }
  },

  _showConfirm(opts) {
    return window.UI.confirm({
      title: opts.title, message: opts.message,
      okText: opts.confirmText || '确定', cancelText: opts.cancelText || '取消',
      danger: !!opts.danger
    });
  },

  _showPrompt(opts) {
    return window.UI.prompt({
      title: opts.title, message: opts.message,
      defaultValue: opts.defaultValue || '', placeholder: opts.placeholder || '',
      okText: opts.confirmText || '确定', cancelText: opts.cancelText || '取消'
    });
  },

  editKnowledgeBase(kbId) {
    const kb = this.knowledgeBases.find(kb => kb.id === kbId);
    if (kb && kb.is_owner === false) {
      window.App.showToast('这是他人共享的知识库，你只有查看权限（如需修改请先克隆为自己的副本）', 'warning');
      return;
    }
    if (kb) this.showCreateModal(kb);
  },

  async deleteKnowledgeBase(kbId) {
    const kb = this.knowledgeBases.find(k => k.id === kbId);
    if (kb && kb.is_owner === false) {
      window.App.showToast('这是他人共享的知识库，你只有查看权限，无法删除', 'warning');
      return;
    }
    const ok = await this._showConfirm({
      title: '删除知识库',
      message: `确定要删除「${kb?.kb_name || ''}」吗？该操作不可恢复，所有文档与向量都会一并清除。`,
      confirmText: '删除', danger: true
    });
    if (!ok) return;
    // 确认弹窗已关闭、无按钮可挂 loading；删除涉及 PG+Milvus+ES 清理可能耗时，用全屏遮罩持续反馈
    window.App.showLoading('正在删除知识库及全部数据，请稍候…');
    try {
      await window.KnowledgeBaseAPI.delete(kbId);
      window.App.hideLoading();
      window.App.showToast('知识库删除成功', 'success');
      this.loadKnowledgeBases();
    } catch (error) {
      window.App.hideLoading();
      this._toastWriteError(error);
    }
  },

  async updateKnowledgeBase(kbId) {
    const name = document.getElementById('kb-name').value.trim();
    const description = document.getElementById('kb-description').value.trim();
    if (!name) { window.App.showToast('请输入知识库名称', 'error'); return; }
    const { strategy, enhancers } = this._collectStrategy();
    const done = window.btnLoading(document.querySelector('.modal-overlay .btn-primary'), '保存中…');
    try {
      await window.KnowledgeBaseAPI.update(kbId, name, description, strategy, enhancers);
      window.App.showToast('知识库更新成功', 'success');
      document.querySelector('.modal-overlay').remove();
      this.loadKnowledgeBases();
    } catch (error) { this._toastWriteError(error); }
    finally { done(); }
  },

  async showShareModal(kbId) {
    const kb = this.knowledgeBases.find(k => k.id === kbId);
    if (!kb) return;
    if (kb.is_owner === false) {
      window.App.showToast('只有知识库所有者才能设置分享', 'warning');
      return;
    }
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
    this._bindModalClose(modal);
    this._loadShareList(kbId);
  },

  async _loadShareList(kbId) {
    const el = document.getElementById('share-list');
    if (!el) return;
    try {
      const resp = await window.FaqAPI.listShares(kbId);
      const items = resp.items || [];
      if (!items.length) { el.innerHTML = '<span style="color: var(--text3);">尚未分享给任何人</span>'; return; }
      el.innerHTML = items.map(s => `
        <div style="display: flex; align-items: center; gap: 8px; margin: 4px 0;" class="kb-share-row">
          <span style="flex: 1;">${this._esc(s.shared_to_username || `用户#${s.shared_to_user_id}`)}</span>
          ${s.can_write_directly ? '<span class="badge ok">可写入</span>' : '<span class="badge">仅 PR</span>'}
          ${s.shared_to_username ? `<button class="btn btn-sm btn-ghost" onclick="KnowledgeBasesPage.unshare(${kbId}, '${this._esc(s.shared_to_username)}')">取消分享</button>` : ''}
        </div>`).join('');
    } catch (e) {
      el.innerHTML = `<span style="color: var(--red);">加载失败: ${this._esc(e.message)}</span>`;
    }
  },

  async submitShare(kbId) {
    const username = document.getElementById('share-username').value.trim();
    const canWrite = document.getElementById('share-can-write').checked;
    if (!username) { window.App.showToast('请输入用户名', 'error'); return; }
    const done = window.btnLoading(document.querySelector('.modal-overlay .btn-primary'), '分享中…');
    try {
      await window.FaqAPI.shareKb({ kb_id: kbId, username, can_write_directly: canWrite });
      window.App.showToast(`已分享给 ${username}`, 'success');
      this._loadShareList(kbId);
    } catch (e) { this._toastWriteError(e); }
    finally { done(); }
  },

  async unshare(kbId, username) {
    try {
      await window.FaqAPI.unshareKb({ kb_id: kbId, username });
      window.App.showToast('已取消分享', 'success');
      this._loadShareList(kbId);
    } catch (e) { this._toastWriteError(e); }
  },

  async cloneKnowledgeBase(kbId) {
    const kb = this.knowledgeBases.find(k => k.id === kbId);
    const name = await this._showPrompt({
      title: '克隆知识库', message: '为克隆副本起个名字（留空使用默认名）',
      defaultValue: kb ? `${kb.kb_name}（克隆）` : '', placeholder: '输入新名称', confirmText: '开始克隆'
    });
    if (name === null) return;
    // 克隆 = PG 全量复制 + Milvus 向量搬运，可能耗时数十秒：必须用全屏遮罩持续反馈（toast 3s 就消失）
    window.App.showLoading('正在克隆知识库，向量搬运可能需要一些时间，请勿关闭页面…');
    try {
      const result = await window.FaqAPI.cloneKb(kbId, name.trim() || null);
      window.App.hideLoading();
      window.App.showToast(`克隆成功（${result.vectors?.chunks ?? '-'} 个向量已搬运）`, 'success');
      this.loadKnowledgeBases();
    } catch (e) {
      window.App.hideLoading();
      this._toastWriteError(e);
    }
  },

  _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  },

  // 写操作失败兜底：request() 已自动 toast 时跳过（_autoToasted 标记），否则补 toast
  // 历史教训：曾因页面层纯依赖全局自动 toast（旧缓存版本无该逻辑）导致 403 静默失败
  _toastWriteError(error) {
    if (error && error._autoToasted) return;
    window.App.showToast(error?.message || '操作失败，请重试', 'error');
  },

  _kbBadges(kb) {
    const badges = [];
    const strategy = kb.chunk_strategy;
    badges.push(strategy
      ? `<span class="badge info">${strategy === 'auto' ? 'auto 切割' : this._esc(strategy)}</span>`
      : `<span class="badge">跟随全局</span>`);
    const enh = kb.enhancers == null ? null : kb.enhancers;
    if (enh && enh.includes('sub_question') && enh.includes('summary')) {
      badges.push('<span class="badge accent">子问题+摘要</span>');
    } else if (enh && enh.length) {
      badges.push(`<span class="badge accent">${enh.includes('sub_question') ? '子问题' : '摘要'}</span>`);
    } else if (enh && enh.length === 0) {
      badges.push('<span class="badge">纯原文</span>');
    }
    return badges.join('');
  }
};

window.KnowledgeBasesPage = KnowledgeBasesPage;
