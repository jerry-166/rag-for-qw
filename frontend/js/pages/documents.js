/**
 * 文档管理页面
 */
const DocumentsPage = {
  currentKbId: null,
  selectedFiles: [],
  
  async render(params = {}) {
    this.currentKbId = params.kb_id || null;
    this.selectedFiles = [];
    
    const container = document.getElementById('page-container');
    container.innerHTML = `
      <div class="page-header">
        <div>
          <h1 class="page-title">文档管理</h1>
          <p class="page-desc">上传和管理您的文档</p>
        </div>
        <button class="btn btn-primary" id="refresh-docs-btn">
          <span>🔄 刷新</span>
        </button>
      </div>
      
      <!-- 上传区域 -->
      <div class="upload-zone" id="upload-zone">
        <input type="file" id="file-input" accept=".pdf" multiple style="display: none;" />
        <div class="upload-icon">📁</div>
        <div class="upload-title">点击或拖拽文件到此处上传</div>
        <div class="upload-sub">支持 PDF 格式文件</div>
        <div class="upload-limit">单个文件不超过 50MB</div>
        <div class="upload-file-list" id="file-list">
          <!-- 上传文件列表 -->
        </div>
      </div>
      
      <!-- 文档列表 -->
      <div class="doc-toolbar" style="margin-top: 20px;">
        <div class="search-input-wrap">
          <span class="search-icon">🔍</span>
          <input type="search" placeholder="搜索文档..." id="doc-search" />
        </div>
        <select id="doc-filter">
          <option value="all">全部状态</option>
          <option value="uploaded">已上传</option>
          <option value="processing">处理中</option>
          <option value="completed">已完成</option>
          <option value="failed">失败</option>
        </select>
      </div>
      
      <div class="doc-table-wrap">
        <table id="doc-table">
          <thead>
            <tr>
              <th>文件名</th>
              <th>大小</th>
              <th>状态</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody id="doc-table-body">
            <!-- 文档列表将在这里渲染 -->
            <tr>
              <td colspan="5" style="text-align: center; padding: 40px;">
                <div class="loading-spinner"></div>
                <p style="margin-top: 12px; color: var(--text3);">加载中...</p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    `;
    
    this.initEvents();
    await this.loadDocuments();
  },

  initEvents() {
    // 上传区域事件
    const uploadZone = document.getElementById('upload-zone');
    const fileInput = document.getElementById('file-input');
    
    uploadZone.addEventListener('click', () => {
      fileInput.click();
    });
    
    uploadZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      uploadZone.classList.add('drag-over');
    });
    
    uploadZone.addEventListener('dragleave', () => {
      uploadZone.classList.remove('drag-over');
    });
    
    uploadZone.addEventListener('drop', (e) => {
      e.preventDefault();
      uploadZone.classList.remove('drag-over');
      if (e.dataTransfer.files.length) {
        this.handleFiles(e.dataTransfer.files);
      }
    });
    
    fileInput.addEventListener('change', (e) => {
      if (e.target.files.length) {
        this.handleFiles(e.target.files);
      }
    });
    
    // 刷新按钮
    document.getElementById('refresh-docs-btn').addEventListener('click', () => {
      this.loadDocuments();
    });
    
    // 搜索和过滤
    document.getElementById('doc-search').addEventListener('input', () => {
      this.filterDocuments();
    });
    
    document.getElementById('doc-filter').addEventListener('change', () => {
      this.filterDocuments();
    });
  },

  handleFiles(files) {
    const fileList = document.getElementById('file-list');
    
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      if (file.type === 'application/pdf') {
        this.selectedFiles.push(file);
        const fileItem = document.createElement('div');
        fileItem.className = 'upload-file-item';
        fileItem.innerHTML = `
          <span class="upload-file-icon">📄</span>
          <span class="upload-file-name">${file.name}</span>
          <span class="upload-file-size">${(file.size / 1024 / 1024).toFixed(2)} MB</span>
          <button class="upload-file-remove" onclick="this.closest('.upload-file-item').remove(); DocumentsPage.selectedFiles = DocumentsPage.selectedFiles.filter(f => f.name !== '${file.name}');">×</button>
        `;
        fileList.appendChild(fileItem);
      }
    }
    
    if (this.selectedFiles.length > 0) {
      // 自动上传
      this.uploadFiles();
    }
  },

  async uploadFiles() {
    if (this.selectedFiles.length === 0) return;
    
    try {
      for (const file of this.selectedFiles) {
        await window.DocumentAPI.upload(file, this.currentKbId);
        window.App.showToast(`文件 ${file.name} 上传成功`, 'success');
      }
      
      // 清空文件列表
      document.getElementById('file-list').innerHTML = '';
      this.selectedFiles = [];
      
      // 重新加载文档列表
      await this.loadDocuments();
    } catch (error) {
      window.App.showToast('上传失败: ' + error.message, 'error');
    }
  },

  async loadDocuments() {
    const tableBody = document.getElementById('doc-table-body');
    try {
      const response = await window.DocumentAPI.list(this.currentKbId);
      const documents = response.documents || [];
      
      // 调试信息：查看返回的文档列表
      console.log('文档列表响应:', response);
      console.log('文档列表:', documents);
      documents.forEach((doc, index) => {
        console.log(`文档${index}:`, doc);
        console.log(`文档${index}的file_id:`, doc.file_id);
      });
      
      if (documents.length === 0) {
        tableBody.innerHTML = `
          <tr>
            <td colspan="5" style="text-align: center; padding: 40px;">
              <div class="empty-state">
                <div class="empty-icon">📄</div>
                <div class="empty-title">暂无文档</div>
                <div class="empty-desc">点击上方上传区域添加文档</div>
              </div>
            </td>
          </tr>
        `;
        return;
      }
      
      tableBody.innerHTML = documents.map(doc => `
        <tr>
          <td class="td-name">${doc.filename}</td>
          <td>${doc.file_size ? (doc.file_size / 1024 / 1024).toFixed(2) + ' MB' : '未知'}</td>
          <td><span class="status-chip status-${doc.status}">${this.getStatusText(doc.status)}</span></td>
          <td>${new Date(doc.created_at).toLocaleString()}</td>
          <td class="td-actions">
            <button class="btn btn-sm btn-secondary" onclick="DocumentsPage.processDocument('${doc.file_id}')">
              处理
            </button>
            <button class="btn btn-sm btn-danger" onclick="DocumentsPage.deleteDocument('${doc.file_id}')">
              删除
            </button>
          </td>
        </tr>
      `).join('');
    } catch (error) {
      tableBody.innerHTML = `
        <tr>
          <td colspan="5" style="text-align: center; padding: 40px;">
            <div class="empty-state">
              <div class="empty-icon">❌</div>
              <div class="empty-title">加载失败</div>
              <div class="empty-desc">${error.message || '无法加载文档列表'}</div>
              <button class="btn btn-secondary" onclick="DocumentsPage.loadDocuments()">
                重新加载
              </button>
            </div>
          </td>
        </tr>
      `;
    }
  },

  getStatusText(status) {
    const statusMap = {
      'uploaded': '已上传',
      'processing': '处理中',
      'completed': '已完成',
      'failed': '失败',
      'chunk_done': '已切割',
      'generated': '已生成'
    };
    return statusMap[status] || status;
  },

  processDocument(docId) {
    window.App.navigate('pipeline', { doc_id: docId });
  },

  async deleteDocument(docId) {
    if (!confirm('确定要删除这个文档吗？')) {
      return;
    }
    
    try {
      await window.DocumentAPI.delete(docId);
      window.App.showToast('文档删除成功', 'success');
      await this.loadDocuments();
    } catch (error) {
      window.App.showToast('删除失败: ' + error.message, 'error');
    }
  },

  filterDocuments() {
    const searchTerm = document.getElementById('doc-search').value.toLowerCase();
    const filterStatus = document.getElementById('doc-filter').value;
    const tableBody = document.getElementById('doc-table-body');
    
    // 获取所有文档行
    const rows = tableBody.querySelectorAll('tr');
    
    let visibleCount = 0;
    
    rows.forEach(row => {
      // 检查是否是空状态或加载状态的行
      if (row.querySelector('.empty-state') || row.querySelector('.loading-spinner')) {
        return;
      }
      
      // 获取行数据
      const fileName = row.querySelector('.td-name').textContent.toLowerCase();
      const status = row.querySelector('.status-chip').textContent;
      
      // 检查搜索条件
      const matchesSearch = searchTerm === '' || fileName.includes(searchTerm);
      
      // 检查状态过滤
      const matchesFilter = filterStatus === 'all' || 
        (filterStatus === 'uploaded' && status === '已上传') ||
        (filterStatus === 'processing' && status === '处理中') ||
        (filterStatus === 'completed' && status === '已完成') ||
        (filterStatus === 'failed' && status === '失败');
      
      // 显示或隐藏行
      if (matchesSearch && matchesFilter) {
        row.style.display = '';
        visibleCount++;
      } else {
        row.style.display = 'none';
      }
    });
    
    // 检查是否没有匹配的文档
    if (visibleCount === 0 && rows.length > 0) {
      // 检查是否所有行都是隐藏的
      const allHidden = Array.from(rows).every(row => {
        return row.style.display === 'none' || row.querySelector('.empty-state') || row.querySelector('.loading-spinner');
      });
      
      if (allHidden) {
        tableBody.innerHTML = `
          <tr>
            <td colspan="5" style="text-align: center; padding: 40px;">
              <div class="empty-state">
                <div class="empty-icon">🔍</div>
                <div class="empty-title">没有找到匹配的文档</div>
                <div class="empty-desc">尝试调整搜索条件或筛选选项</div>
                <button class="btn btn-secondary" onclick="DocumentsPage.loadDocuments()">
                  重置筛选
                </button>
              </div>
            </td>
          </tr>
        `;
      }
    }
  }
};

window.DocumentsPage = DocumentsPage;