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
            <div class="kb-icon">📚</div>
            <div class="kb-actions">
              <button class="btn-icon" title="编辑" onclick="KnowledgeBasesPage.editKnowledgeBase(${kb.id})">✏️</button>
              <button class="btn-icon" title="删除" onclick="KnowledgeBasesPage.deleteKnowledgeBase(${kb.id})">🗑️</button>
            </div>
          </div>
          <div class="kb-name">${kb.kb_name}</div>
          <div class="kb-desc">${kb.description || '无描述'}</div>
          <div class="kb-meta">
            <span>创建于 ${new Date(kb.created_at).toLocaleDateString()}</span>
          </div>
        </div>
      `).join('') + `
        <div class="kb-card kb-card-add" onclick="KnowledgeBasesPage.showCreateModal()">
          <div class="add-icon">+</div>
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

  async createKnowledgeBase() {
    const name = document.getElementById('kb-name').value.trim();
    const description = document.getElementById('kb-description').value.trim();
    
    if (!name) {
      window.App.showToast('请输入知识库名称', 'error');
      return;
    }
    
    try {
      await window.KnowledgeBaseAPI.create(name, description);
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
    
    try {
      await window.KnowledgeBaseAPI.update(kbId, name, description);
      window.App.showToast('知识库更新成功', 'success');
      document.querySelector('.modal-overlay').remove();
      this.loadKnowledgeBases();
    } catch (error) {
      window.App.showToast('更新失败: ' + error.message, 'error');
    }
  }
};

window.KnowledgeBasesPage = KnowledgeBasesPage;