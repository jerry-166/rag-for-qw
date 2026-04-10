/**
 * 文档处理流水线页面
 */
const PipelinePage = {
  currentDocId: null,
  currentStep: 0,
  steps: [
    { id: 0, title: '上传 & 解析', status: 'pending' },
    { id: 1, title: '文档切割', status: 'pending' },
    { id: 2, title: '生成增强', status: 'pending' },
    { id: 3, title: '嵌入入库', status: 'pending' }
  ],
  documentData: null,
  markdownContent: '',
  chunks: [],
  selectedChunk: null,
  generationResults: {},
  importResults: null,
  timings: { upload: 0, split: 0, generate: 0, import: 0 },
  stats: {
    chunksCount: 0,
    subQuestionsCount: 0,
    summariesCount: 0,
    vectorCount: 0,
    vectorDim: 0
  },
  
  async render(params = {}) {
    this.currentDocId = params.doc_id || params.fileId || null;
    this.currentStep = 0;
    this.steps = [
      { id: 0, title: '上传 & 解析', status: 'pending' },
      { id: 1, title: '文档切割', status: 'pending' },
      { id: 2, title: '生成增强', status: 'pending' },
      { id: 3, title: '嵌入入库', status: 'pending' }
    ];
    this.documentData = null;
    this.markdownContent = '';
    this.chunks = [];
    this.selectedChunk = null;
    this.generationResults = {};
    this.importResults = null;
    this.timings = { upload: 0, split: 0, generate: 0, import: 0 };
    this.stats = {
      chunksCount: 0,
      subQuestionsCount: 0,
      summariesCount: 0,
      vectorCount: 0,
      vectorDim: 0
    };
    
    const container = document.getElementById('page-container');
    
    if (!this.currentDocId) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">❌</div>
          <div class="empty-title">文档ID缺失</div>
          <div class="empty-desc">请从文档管理页面选择一个文档进行处理</div>
          <button class="btn btn-primary" onclick="window.App.navigate('documents')">
            返回文档管理
          </button>
        </div>
      `;
      return;
    }
    
    container.innerHTML = `
      <div class="pipeline-steps" id="pipeline-steps">
        ${this.steps.map((step, index) => `
          <div class="step-item ${step.status === 'done' ? 'done' : step.status === 'active' ? 'active' : ''}" onclick="PipelinePage.goToStep(${index})"><div class="step-badge">${step.status === 'done' ? '✓' : step.id + 1}</div>
            <div class="step-label">${step.title}</div>
          </div>
          ${index < this.steps.length - 1 ? `<div class="step-connector ${step.status === 'done' ? 'done' : ''}"></div>` : ''}
        `).join('')}
      </div>
      
      <div id="step-content">
        <!-- 步骤内容将在这里渲染 -->
        <div class="loading-state">
          <div class="loading-spinner"></div>
          <p>加载中...</p>
        </div>
      </div>
    `;
    
    try {
      await this.loadDocumentInfo();
      await this.renderStepContent();
    } catch (error) {
      console.error('渲染流水线页面失败:', error);
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">❌</div>
          <div class="empty-title">页面加载失败</div>
          <div class="empty-desc">${error.message || '未知错误'}</div>
          <button class="btn btn-primary" onclick="window.App.navigate('documents')">
            返回文档管理
          </button>
        </div>
      `;
    }
  },

  async loadDocumentInfo() {
    try {
      // 尝试获取文档信息
      let docStatus = 'uploaded'; // 默认状态
      
      try {
        const result = await window.DocumentAPI.getResult(this.currentDocId);
        this.documentData = result;
        docStatus = result.status;
        // 从数据库中提取时间字段，更新timings对象
        if (result.upload_time) this.timings.upload = result.upload_time;
        if (result.split_time) this.timings.split = result.split_time;
        if (result.generate_time) this.timings.generate = result.generate_time;
        if (result.import_time) this.timings.import = result.import_time;
      } catch (error) {
        // 如果获取结果失败（例如文件尚未处理完成），尝试获取文档基本信息
        try {
          const docInfo = await window.DocumentAPI.getPreview(this.currentDocId);
          this.documentData = docInfo;
          docStatus = docInfo.status;
          // 从数据库中提取时间字段，更新timings对象
          if (docInfo.upload_time) this.timings.upload = docInfo.upload_time;
          if (docInfo.split_time) this.timings.split = docInfo.split_time;
          if (docInfo.generate_time) this.timings.generate = docInfo.generate_time;
          if (docInfo.import_time) this.timings.import = docInfo.import_time;
        } catch (e) {
          // 如果获取基本信息也失败，显示错误提示，但继续设置默认状态
          console.error('加载文档信息失败:', e);
          window.App.showToast('加载文档信息失败，使用默认状态', 'warning');
          // 设置默认的documentData，避免后续操作出错
          this.documentData = {
            filename: '未知文件',
            status: 'uploaded',
            file_size: 0
          };
        }
      }
      
      // 更新步骤状态
      if (docStatus === 'completed') {
        this.steps.forEach(step => step.status = 'done');
        // 对于completed状态，直接展示第四步（嵌入入库）
        this.steps[3].status = 'active';
        this.currentStep = 3;
      } else if (docStatus === 'generated') {
        this.steps[0].status = 'done';
        this.steps[1].status = 'done';
        this.steps[2].status = 'done';
        this.steps[3].status = 'pending';
        // 对于generated状态，展示第三步（生成增强）
        this.steps[2].status = 'active';
        this.currentStep = 2;
      } else if (docStatus === 'chunk_done') {
        this.steps[0].status = 'done';
        this.steps[1].status = 'done';
        this.steps[2].status = 'pending';
        this.steps[3].status = 'pending';
        // 对于chunk_done状态，展示第二步（文档切割）
        this.steps[1].status = 'active';
        this.currentStep = 1;
      } else if (docStatus === 'uploaded' || docStatus === 'processing') {
        // 对于新上传的文档，从步骤0开始，显示PDF和MD对比页面
        this.steps[0].status = 'active';
        this.steps[1].status = 'pending';
        this.steps[2].status = 'pending';
        this.steps[3].status = 'pending';
        this.currentStep = 0;
      }
      
      // 确保至少有一个步骤是active
      let hasActive = false;
      for (let i = 0; i < this.steps.length; i++) {
        if (this.steps[i].status === 'active') {
          hasActive = true;
          break;
        }
      }
      
      if (!hasActive) {
        // 找到第一个pending状态的步骤并设置为active
        for (let i = 0; i < this.steps.length; i++) {
          if (this.steps[i].status === 'pending') {
            this.steps[i].status = 'active';
            this.currentStep = i;
            break;
          }
        }
      }
      
      this.updateStepsUI();
    } catch (error) {
      console.error('loadDocumentInfo错误:', error);
      window.App.showToast('加载文档信息失败: ' + error.message, 'error');
      
      // 即使出错，也要确保步骤有默认状态，从步骤0开始
      this.steps[0].status = 'done';
      this.steps[1].status = 'pending';
      this.steps[2].status = 'pending';
      this.steps[3].status = 'pending';
      this.steps[0].status = 'active'; // 从步骤0开始
      this.currentStep = 0;
      
      // 设置默认的documentData
      this.documentData = {
        filename: '未知文件',
        status: 'uploaded',
        file_size: 0
      };
      
      this.updateStepsUI();
    }
  },

  updateStepsUI() {
    const stepsContainer = document.getElementById('pipeline-steps');
    if (!stepsContainer) {
      console.error('stepsContainer not found');
      return;
    }
    
    stepsContainer.innerHTML = this.steps.map((step, index) => `
      <div class="step-item ${step.status === 'done' ? 'done' : step.status === 'active' ? 'active' : ''}" onclick="PipelinePage.goToStep(${index})">
        <div class="step-badge">${step.status === 'done' ? '✓' : step.id + 1}</div>
        <div class="step-label">${step.title}</div>
      </div>
      ${index < this.steps.length - 1 ? `<div class="step-connector ${step.status === 'done' ? 'done' : ''}"></div>` : ''}
    `).join('');
  },

  goToStep(stepIndex) {
    // 检查步骤索引是否有效
    if (!this.steps[stepIndex]) {
      console.error('Invalid step index:', stepIndex);
      return;
    }
    
    // 如果文档已完成，允许访问所有步骤
    if (this.documentData?.status === 'completed') {
      this.currentStep = stepIndex;
      this.renderStepContent();
      return;
    }
    
    // 只能跳转到已完成或当前步骤
    if (this.steps[stepIndex].status === 'done' || this.steps[stepIndex].status === 'active') {
      this.currentStep = stepIndex;
      this.renderStepContent();
    } else {
      // 如果步骤尚未完成，显示提示
      window.App.showToast('该步骤尚未完成，请先完成前面的步骤', 'warning');
    }
  },

  async renderStepContent() {
    const contentContainer = document.getElementById('step-content');
    
    switch (this.currentStep) {
      case 0:
        await this.renderStep1(contentContainer);
        break;
      case 1:
        await this.renderStep2(contentContainer);
        break;
      case 2:
        await this.renderStep3(contentContainer);
        break;
      case 3:
        await this.renderStep4(contentContainer);
        break;
    }
  },

  async renderStep1(container) {
    container.innerHTML = `
      <div class="pipeline-panel">
        <div class="pipeline-panel-header">
          <div class="panel-icon" style="background: #7c3aed22;">📄</div>
          <div>
            <div class="panel-title">Step 1 · PDF 解析 → Markdown 转换</div>
            <div class="panel-subtitle">对比原始 PDF 和结构化 Markdown 内容</div>
          </div>
          <div style="flex: 1;"></div>
          <span class="api-tag"><span class="api-method post">POST</span>/api/upload/pdf</span>
          <span class="api-tag"><span class="api-method get">GET</span>/api/markdown/{file_id}</span>
          <span class="api-tag"><span class="api-method get">GET</span>/api/pdf/{file_id}</span>
          <span class="badge ${this.steps[0].status === 'done' ? 'badge-green' : this.steps[0].status === 'active' ? 'badge-blue' : 'badge-gray'}">
            ${this.steps[0].status === 'done' ? '✓ 已完成' : this.steps[0].status === 'active' ? '⚡ 进行中' : '· 等待中'}
          </span>
        </div>
        
        <div class="compare-layout">
          <!-- 左：原始 PDF 预览 -->
          <div class="compare-pane">
            <div class="compare-pane-header">
              <span class="tag-pdf">PDF</span>
              原始文件预览
              <div style="flex: 1;"></div>
              <span style="color: var(--text3); font-size: .75rem;">${this.documentData?.filename || '未知文件'}</span>
            </div>
            <div class="md-viewer" style="background: #1e1e2e; color: #e2e8f0;">
              <div id="pdf-viewer" style="width: 100%; height: 100%;">
                <div style="padding: 16px; text-align: center;">
                  <div class="loading-spinner" style="margin: 20px auto;"></div>
                  <p style="color: var(--text3);">加载 PDF 中...</p>
                </div>
              </div>
            </div>
          </div>

          <!-- 右：转换后 Markdown -->
          <div class="compare-pane">
            <div class="compare-pane-header">
              <span class="tag-md">MD</span>
              解析后 Markdown
              <div style="flex: 1;"></div>
              <span style="color: var(--green); font-size: .75rem;">✓ 表格/公式已结构化</span>
            </div>
            <div class="md-viewer" id="markdown-viewer">
              <div style="padding: 16px; color: var(--text3);">加载中...</div>
            </div>
          </div>
        </div>

        <div class="pipeline-action-bar">
          <div class="action-info">
            解析完成 · 识别到 <strong style="color: var(--text)">${this.documentData?.tables_count || 0}</strong> 张表格、<strong style="color: var(--text)">${this.documentData?.formulas_count || 0}</strong> 个公式
            <span style="margin-left: 20px;">文件大小: ${this.documentData ? (this.documentData.file_size / 1024 / 1024).toFixed(2) + ' MB' : '未知'}</span>
          </div>
          <button class="btn btn-secondary" onclick="PipelinePage.downloadMarkdown()">
            ↓ 下载 Markdown
          </button>
          <button class="btn btn-secondary" onclick="PipelinePage.downloadPDF()">
            ↓ 下载 PDF
          </button>
          <button class="btn btn-primary" onclick="PipelinePage.nextStep()">
            下一步：切割文档 →
          </button>
        </div>
      </div>
    `;
    
    // 加载 Markdown 内容
    await this.loadMarkdown();
    // 加载 PDF 内容
    await this.loadPDF();
  },

  async loadPDF() {
    try {
      const pdfBlob = await window.DocumentAPI.getPDF(this.currentDocId);
      const pdfUrl = URL.createObjectURL(pdfBlob);
      const pdfViewer = document.getElementById('pdf-viewer');
      
      // 清空并设置基本样式
      pdfViewer.innerHTML = '';
      pdfViewer.style.position = 'relative';
      pdfViewer.style.width = '100%';
      pdfViewer.style.height = '100%';
      
      // 检查PDF.js是否可用
      if (typeof pdfjsLib !== 'undefined') {
        // 创建容器
        const container = document.createElement('div');
        container.style.width = '100%';
        container.style.height = '100%';
        container.style.display = 'flex';
        container.style.flexDirection = 'column';
        pdfViewer.appendChild(container);
        
        // 创建canvas容器
        const canvasContainer = document.createElement('div');
        canvasContainer.style.flex = '1';
        canvasContainer.style.overflow = 'auto';
        container.appendChild(canvasContainer);
        
        // 创建canvas元素
        const canvas = document.createElement('canvas');
        canvas.id = 'pdf-canvas';
        canvas.style.maxWidth = '100%';
        canvas.style.height = 'auto';
        canvasContainer.appendChild(canvas);
        
        try {
          // 加载PDF
          const loadingTask = pdfjsLib.getDocument(pdfUrl);
          const pdfDocument = await loadingTask.promise;
          
          // 渲染第一页
          const page = await pdfDocument.getPage(1);
          const context = canvas.getContext('2d');
          
          // 设置缩放
          const viewport = page.getViewport({ scale: 1.0 });
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          
          // 渲染页面
          const renderContext = {
            canvasContext: context,
            viewport: viewport
          };
          
          // 确保渲染完成
          const renderTask = page.render(renderContext);
          await renderTask.promise;
          
          // 创建导航栏
          const navDiv = document.createElement('div');
          navDiv.style.padding = '10px';
          navDiv.style.textAlign = 'center';
          navDiv.style.backgroundColor = 'var(--surface2)';
          navDiv.style.borderTop = '1px solid var(--border)';
          navDiv.innerHTML = `
            <p style="color: var(--text3); font-size: .8rem; margin: 0 0 10px 0;">
              第 1 页，共 ${pdfDocument.numPages} 页
            </p>
            <a href="${pdfUrl}" target="_blank" class="btn btn-sm btn-primary">
              📄 查看完整 PDF
            </a>
          `;
          container.appendChild(navDiv);
          
        } catch (pdfError) {
          console.error('PDF.js渲染失败:', pdfError);
          // PDF.js渲染失败，使用备用方案
          this.renderPDFAlternative(pdfUrl);
        }
      } else {
        // PDF.js不可用，使用备用方案
        this.renderPDFAlternative(pdfUrl);
      }
    } catch (error) {
      console.error('加载PDF失败:', error);
      document.getElementById('pdf-viewer').innerHTML = `
        <div style="padding: 16px; text-align: center; color: var(--red);">
          <p>加载 PDF 失败: ${error.message}</p>
          <p style="color: var(--text3); margin-top: 8px;">文件大小: ${this.documentData ? (this.documentData.file_size / 1024 / 1024).toFixed(2) + ' MB' : '未知'}</p>
        </div>
      `;
    }
  },

  renderPDFAlternative(pdfUrl) {
    const pdfViewer = document.getElementById('pdf-viewer');
    // 检查浏览器是否支持内置PDF查看器
    if (typeof window.PDFViewerApplication !== 'undefined') {
      // 使用内置PDF查看器
      pdfViewer.innerHTML = `<iframe src="${pdfUrl}" style="width: 100%; height: 100%; border: none;"></iframe>`;
    } else {
      // 使用链接方式
      pdfViewer.innerHTML = `
        <div style="padding: 16px;">
          <h3 style="color: #a78bfa; margin-bottom: 12px;">${this.documentData?.filename || 'PDF 文件'}</h3>
          <a href="${pdfUrl}" target="_blank" class="btn btn-primary" style="display: inline-block; margin: 10px 0;">
            📄 打开 PDF
          </a>
          <p style="color: var(--text3); margin-top: 8px;">文件大小: ${this.documentData ? (this.documentData.file_size / 1024 / 1024).toFixed(2) + ' MB' : '未知'}</p>
        </div>
      `;
    }
  },

  async downloadPDF() {
    try {
      const pdfBlob = await window.DocumentAPI.getPDF(this.currentDocId);
      const pdfUrl = URL.createObjectURL(pdfBlob);
      const a = document.createElement('a');
      a.href = pdfUrl;
      a.download = this.documentData?.filename || 'document.pdf';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(pdfUrl);
    } catch (error) {
      window.App.showToast('下载 PDF 失败: ' + error.message, 'error');
    }
  },

  async loadMarkdown() {
    try {
      const response = await window.DocumentAPI.getMarkdown(this.currentDocId);
      this.markdownContent = response.content || '';
      const viewer = document.getElementById('markdown-viewer');
      
      if (this.markdownContent) {
        // 清理Markdown内容，修复标题格式
        const cleanedContent = this._cleanMarkdown(this.markdownContent);
        
        // 检查marked函数是否存在
        if (typeof marked === 'function') {
          // 使用marked.js渲染Markdown为HTML
          const html = marked(cleanedContent);
          viewer.innerHTML = html;
        } else {
          // 如果marked函数不存在，使用简单的文本显示
          viewer.innerHTML = `<pre style="white-space: pre-wrap; font-family: monospace;">${cleanedContent}</pre>`;
        }
      } else {
        viewer.innerHTML = '<div style="padding: 16px; color: var(--text3);">暂无 Markdown 内容</div>';
      }
    } catch (error) {
      document.getElementById('markdown-viewer').innerHTML = `<div style="padding: 16px; color: var(--red);">加载失败: ${error.message}</div>`;
    }
  },

  _cleanMarkdown(markdownContent) {
    // 清理Markdown内容，修复标题格式和层级
    let lines = markdownContent.split('\n');
    let cleanedLines = [];
    
    for (let i = 0; i < lines.length; i++) {
      let line = lines[i];
      
      // 修复标题格式，确保标题后面有空格
      line = line.replace(/^(#{1,6})([^\s#])/g, '$1 $2');
      
      // 移除行尾的#号
      line = line.replace(/\s+#+$/g, '');
      
      // 检查是否是标题行
      const titleMatch = line.match(/^(#{1,6})\s+(.+)$/);
      if (titleMatch) {
        // 保留原始标题结构，不进行分割
        cleanedLines.push(line);
      } else {
        // 对于非标题行，直接添加
        cleanedLines.push(line);
      }
    }
    
    return cleanedLines.join('\n');
  },

  async renderStep2(container) {
    container.innerHTML = `
      <div class="pipeline-panel">
        <div class="pipeline-panel-header">
          <div class="panel-icon" style="background: var(--cyan-bg);">✂️</div>
          <div>
            <div class="panel-title">Step 2 · 文档切割 · Chunk 预览</div>
            <div class="panel-subtitle">基于语义边界切割，点击左侧 Chunk 查看内容</div>
          </div>
          <div style="flex: 1;"></div>
          <span class="api-tag"><span class="api-method post">POST</span>/api/process/split/{file_id}</span>
          <span class="badge ${this.steps[1].status === 'done' ? 'badge-green' : this.steps[1].status === 'active' ? 'badge-blue' : 'badge-gray'}">
            ${this.steps[1].status === 'done' ? '✓ 已完成' : this.steps[1].status === 'active' ? '⚡ 进行中' : '· 等待中'}
          </span>
        </div>

        <!-- MD 全文预览提示条 -->
        <div class="full-md-bar">
          <span style="color: var(--text3);">完整 Markdown：</span>
          <span>${this.documentData?.filename?.replace('.pdf', '.md') || 'unknown.md'}</span>
          <div style="flex: 1;"></div>
          <div class="progress-bar" style="width: 200px;">
            <div class="progress-fill" style="width: 100%;"></div>
          </div>
          <span style="color: var(--green); font-size: .75rem; margin-left: 8px;">已切割为 ${this.chunks.length || 0} 个 Chunk</span>
        </div>

        <div class="chunk-layout">
          <!-- 左：Chunk 列表 -->
          <div class="chunk-list-panel">
            <div class="chunk-list-header">
              Chunk 列表
              <span class="chunk-count-badge">${this.chunks.length || 0}</span>
            </div>
            <div class="chunk-list-scroll" id="chunk-list">
              <!-- Chunk 列表将在这里渲染 -->
              <div style="padding: 16px; text-align: center; color: var(--text3);">加载中...</div>
            </div>
          </div>

          <!-- 右：Chunk 详情 -->
          <div class="chunk-detail-panel">
            <div class="chunk-detail-title" id="chunk-detail-title">
              选择一个 Chunk 查看详情
            </div>
            <div class="chunk-detail-content" id="chunk-detail-content">
              <div style="padding: 20px; text-align: center; color: var(--text3);">
                点击左侧 Chunk 列表查看详情
              </div>
            </div>
            <div class="stats-row" id="chunk-stats">
              <!-- 统计信息将在这里渲染 -->
            </div>
          </div>
        </div>

        <div class="pipeline-action-bar">
          <div class="action-info">
            共生成 <strong style="color: var(--text)">${this.chunks.length || 0}</strong> 个 Chunk · 平均 <strong style="color: var(--text)">~${this.chunks.length ? Math.round(this.chunks.reduce((sum, chunk) => sum + (typeof chunk === 'string' ? chunk.length : chunk.content.length), 0) / this.chunks.length) : 0}</strong> 字符/Chunk
          </div>
          <button class="btn btn-ghost" onclick="PipelinePage.previousStep()">
            ← 返回解析
          </button>
          <button class="btn btn-primary" onclick="PipelinePage.nextStep()">
            下一步：生成增强 →
          </button>
        </div>
      </div>
    `;
    
    // 加载 Chunk 数据
    await this.loadChunks();
  },

  async loadChunks() {
    try {
      // 尝试从getResult获取已有chunk数据
      try {
        const result = await window.DocumentAPI.getResult(this.currentDocId);
        if (result.chunks && Array.isArray(result.chunks)) {
          this.chunks = result.chunks.map(chunk => {
            if (typeof chunk === 'string') {
              return { content: chunk, type: '文本' };
            }
            return chunk;
          });
          // 从响应中提取chunks_count
          if (result.chunks_count) {
            this.stats.chunksCount = result.chunks_count;
          }
          this.updateChunkList();
          return;
        }
      } catch (error) {
        console.log('getResult失败，尝试调用split:', error);
      }
      
      // 如果getResult失败，再调用split
      const startTime = Date.now();
      const response = await window.DocumentAPI.split(this.currentDocId);
      const endTime = Date.now();
      // 优先使用后端返回的处理时间，其次使用前端计算的时间
      this.timings.split = response.processing_time_ms !== undefined ? response.processing_time_ms : (endTime - startTime);
      
      if (response.chunks && Array.isArray(response.chunks)) {
        this.chunks = response.chunks.map(chunk => {
          if (typeof chunk === 'string') {
            return { content: chunk, type: '文本' };
          }
          return chunk;
        });
        // 从响应中提取chunks_count
        if (response.chunks_count) {
          this.stats.chunksCount = response.chunks_count;
        }
      } else {
        this.chunks = [];
      }
      this.updateChunkList();
    } catch (error) {
      document.getElementById('chunk-list').innerHTML = `<div style="padding: 16px; text-align: center; color: var(--red);">加载失败: ${error.message}</div>`;
    }
  },

  _stripMarkdown(text) {
    // 去掉 markdown 语法符号，让预览文字干净
    // 按行处理，保留标题结构
    const lines = text.split('\n');
    const cleanedLines = lines.map(line => {
      // 检查是否是标题行
      const titleMatch = line.match(/^(#{1,6})\s+(.+)$/);
      if (titleMatch) {
        // 保留标题结构，只移除markdown符号
        return titleMatch[1] + ' ' + titleMatch[2]
          .replace(/\*\*(.+?)\*\*/g, '$1') // 粗体
          .replace(/\*(.+?)\*/g, '$1')     // 斜体
          .replace(/`(.+?)`/g, '$1')       // 行内代码
          .replace(/!\[.*?\]\(.*?\)/g, '[图片]') // 图片
          .replace(/\[(.+?)\]\(.*?\)/g, '$1');    // 链接
      } else {
        // 非标题行，移除所有markdown符号
        return line
          .replace(/\*\*(.+?)\*\*/g, '$1') // 粗体
          .replace(/\*(.+?)\*/g, '$1')     // 斜体
          .replace(/`(.+?)`/g, '$1')       // 行内代码
          .replace(/!\[.*?\]\(.*?\)/g, '[图片]') // 图片
          .replace(/\[(.+?)\]\(.*?\)/g, '$1')    // 链接
          .replace(/^[-*+]\s+/, '')      // 无序列表
          .replace(/^\d+\.\s+/, '');      // 有序列表
      }
    });
    
    return cleanedLines
      .join(' ')
      .replace(/\s{2,}/g, ' ')
      .trim();
  },

  updateChunkList() {
    const chunkList = document.getElementById('chunk-list');
    if (this.chunks.length === 0) {
      chunkList.innerHTML = `<div style="padding: 16px; text-align: center; color: var(--text3);">暂无 Chunk 数据</div>`;
      return;
    }
    
    chunkList.innerHTML = this.chunks.map((chunk, index) => {
      const rawPreview = chunk.content.substring(0, 120);
      const cleanPreview = this._stripMarkdown(rawPreview).substring(0, 80);
      return `
        <div class="chunk-item ${this.selectedChunk === index ? 'active' : ''}" onclick="PipelinePage.selectChunk(${index})">
          <div class="chunk-item-header">
            <span class="chunk-num">#${index + 1}</span>
            <span class="chunk-type">${chunk.type || '文本'}</span>
          </div>
          <div class="chunk-preview">${cleanPreview}${cleanPreview.length >= 80 ? '...' : ''}</div>
        </div>
      `;
    }).join('');
  },

  selectChunk(index) {
    this.selectedChunk = index;
    const chunk = this.chunks[index];
    // 确保chunk是对象
    const chunkObj = typeof chunk === 'string' ? { content: chunk, type: '文本' } : chunk;
    document.getElementById('chunk-detail-title').innerHTML = `
      <span class="chunk-num" style="background: var(--accent);">#${index + 1}</span>
      ${chunkObj.type || '文本'}
      <div style="flex: 1;"></div>
      <span class="annotation">🔤 字符数：${chunkObj.content.length}</span>
      <span class="annotation" style="margin-left: 6px;">📏 Token 数：~${Math.round(chunkObj.content.length / 4)}</span>
    `;
    document.getElementById('chunk-detail-content').textContent = chunkObj.content;
    document.getElementById('chunk-stats').innerHTML = `
      <div class="stat-chip">📄 来源页：${chunkObj.page || '未知'}</div>
      <div class="stat-chip">🏷️ 类型：${chunkObj.type || '文本'}</div>
    `;
    this.updateChunkList();
  },

  async renderStep3(container) {
    container.innerHTML = `
      <div class="pipeline-panel">
        <div class="pipeline-panel-header">
          <div class="panel-icon" style="background: var(--yellow-bg);">🧠</div>
          <div>
            <div class="panel-title">Step 3 · 生成子问题 & 摘要</div>
            <div class="panel-subtitle">点击左侧不同 Chunk，查看对应的子问题和摘要</div>
          </div>
          <div style="flex: 1;"></div>
          <span class="api-tag"><span class="api-method post">POST</span>/api/process/generate/{file_id}</span>
          <span class="badge ${this.steps[2].status === 'done' ? 'badge-green' : this.steps[2].status === 'active' ? 'badge-blue' : 'badge-gray'}">
            ${this.steps[2].status === 'done' ? '✓ 已完成' : this.steps[2].status === 'active' ? '⚡ 进行中' : '· 等待中'}
          </span>
        </div>

        <div class="gen-layout">
          <!-- 左：Chunk 选择器 -->
          <div class="gen-chunk-selector">
            <div class="chunk-list-header">
              选择 Chunk
              <span class="chunk-count-badge">${this.chunks.length || 0}</span>
            </div>
            <div class="chunk-list-scroll" id="gen-chunk-list">
              <!-- Chunk 列表将在这里渲染 -->
              <div style="padding: 16px; text-align: center; color: var(--text3);">加载中...</div>
            </div>

            <!-- 总体进度 -->
            <div style="padding: 10px 14px; border-top: 1px solid var(--border);">
              <div style="font-size: .75rem; color: var(--text3); margin-bottom: 6px; display: flex; justify-content: space-between;">
                <span>生成进度</span><span style="color: var(--accent2)">${Object.keys(this.generationResults).length} / ${this.chunks.length}</span>
              </div>
              <div class="progress-bar">
                <div class="progress-fill" style="width: ${this.chunks.length ? (Object.keys(this.generationResults).length / this.chunks.length) * 100 : 0}%;"></div>
              </div>
            </div>
          </div>

          <!-- 右：子问题 + 摘要 -->
          <div class="gen-detail">
            <!-- 子问题区 -->
            <div class="gen-detail-half">
              <div class="gen-section-title" style="color: var(--accent2);">
                💬 子问题
                <span style="background: var(--accent); color: #fff; border-radius: 12px; padding: 1px 8px; font-size: .7rem; font-weight: 700;">${this.selectedChunk !== null && this.generationResults[this.selectedChunk] ? this.generationResults[this.selectedChunk].sub_questions.length : 0}</span>
                <div style="flex: 1;"></div>
                <span class="annotation">Chunk #${this.selectedChunk !== null ? this.selectedChunk + 1 : '0'} · ${this.selectedChunk !== null && this.chunks[this.selectedChunk] ? this.chunks[this.selectedChunk].type : '未知'}</span>
              </div>
              <div class="subq-list" id="subq-list">
                <!-- 子问题列表将在这里渲染 -->
                <div style="padding: 16px; text-align: center; color: var(--text3);">选择一个 Chunk 查看子问题</div>
              </div>
            </div>

            <!-- 摘要区 -->
            <div class="gen-detail-half">
              <div class="gen-section-title" style="color: var(--cyan);">
                📝 摘要
                <div style="flex: 1;"></div>
                <span class="annotation">~${this.selectedChunk !== null && this.generationResults[this.selectedChunk] ? this.generationResults[this.selectedChunk].summary.length : 0} 字</span>
              </div>
              <div class="summary-box" id="summary-box">
                <div style="padding: 16px; text-align: center; color: var(--text3);">选择一个 Chunk 查看摘要</div>
              </div>
              <div class="stats-row" id="gen-stats">
                <!-- 统计信息将在这里渲染 -->
              </div>
            </div>
          </div>
        </div>

        <div class="pipeline-action-bar">
          <div class="action-info">
            已生成 <strong style="color: var(--text)">${Object.keys(this.generationResults).length}/${this.chunks.length}</strong> 个 Chunk 的增强内容
          </div>
          <button class="btn btn-ghost" onclick="PipelinePage.previousStep()">
            ← 返回切割
          </button>
          <button class="btn btn-primary" onclick="PipelinePage.nextStep()">
            下一步：嵌入入库 →
          </button>
        </div>
      </div>
    `;
    
    // 加载生成结果
    await this.loadGenerationResults();
  },

  async loadGenerationResults() {
    try {
      // 尝试从getResult获取已有生成结果
      try {
        const result = await window.DocumentAPI.getResult(this.currentDocId);
        if (result.sub_questions && result.summaries) {
          this.generationResults = {};
          result.sub_questions.forEach((subqs, index) => {
            this.generationResults[index] = {
              sub_questions: subqs,
              summary: result.summaries[index] || ''
            };
          });
          // 计算子问题和摘要数量
          let subQuestionsCount = 0;
          let summariesCount = 0;
          result.sub_questions.forEach((subqs, index) => {
            subQuestionsCount += subqs.length;
            if (result.summaries[index]) {
              summariesCount++;
            }
          });
          this.stats.subQuestionsCount = subQuestionsCount;
          this.stats.summariesCount = summariesCount;
          this.updateGenChunkList();
          // 如果有生成结果，自动选择第一个chunk
          if (Object.keys(this.generationResults).length > 0) {
            this.selectGenChunk(0);
          }
          return;
        }
      } catch (error) {
        console.log('getResult失败，尝试调用generate:', error);
      }
      
      // 如果getResult失败，再调用generate
      const startTime = Date.now();
      this.showLoading('正在处理');
      const response = await window.DocumentAPI.generate(this.currentDocId);
      this.hideLoading();
      const endTime = Date.now();
      // 优先使用后端返回的处理时间，其次使用前端计算的时间
      this.timings.generate = response.processing_time_ms !== undefined ? response.processing_time_ms : (endTime - startTime);
      
      // 处理后端返回的results对象
      this.generationResults = response.results || {};
      // 从响应中提取sub_questions_count和summaries_count
      if (response.sub_questions_count) {
        this.stats.subQuestionsCount = response.sub_questions_count;
      }
      if (response.summaries_count) {
        this.stats.summariesCount = response.summaries_count;
      }
      this.updateGenChunkList();
      // 如果有生成结果，自动选择第一个chunk
      if (Object.keys(this.generationResults).length > 0) {
        this.selectGenChunk(0);
      }
    } catch (error) {
      this.hideLoading();
      document.getElementById('gen-chunk-list').innerHTML = `<div style="padding: 16px; text-align: center; color: var(--red);">加载失败: ${error.message}</div>`;
    }
  },

  updateGenChunkList() {
    const chunkList = document.getElementById('gen-chunk-list');
    if (this.chunks.length === 0) {
      chunkList.innerHTML = `<div style="padding: 16px; text-align: center; color: var(--text3);">暂无 Chunk 数据</div>`;
      return;
    }
    
    chunkList.innerHTML = this.chunks.map((chunk, index) => {
      const hasResult = this.generationResults[index] !== undefined;
      return `
        <div class="chunk-item ${this.selectedChunk === index ? 'active' : ''}" onclick="PipelinePage.selectGenChunk(${index})">
          <div class="chunk-item-header">
            <span class="chunk-num">#${index + 1}</span>
            <span class="chunk-type" style="color: ${hasResult ? 'var(--green)' : 'var(--text3)'}">${hasResult ? '✓ 已生成' : '待处理'}</span>
          </div>
          <div class="chunk-preview">${chunk.type || '文本'}</div>
        </div>
      `;
    }).join('');
  },

  selectGenChunk(index) {
    this.selectedChunk = index;
    const result = this.generationResults[index];
    
    if (result) {
      document.getElementById('subq-list').innerHTML = result.sub_questions.map((q, i) => `
        <div class="subq-item">
          <span class="subq-icon">❓</span>
          ${q}
        </div>
      `).join('');
      
      document.getElementById('summary-box').innerHTML = result.summary || '<div style="padding: 16px; text-align: center; color: var(--text3);">暂无摘要</div>';
      
      document.getElementById('gen-stats').innerHTML = `
        <div class="stat-chip">🔤 摘要压缩比：${result.summary ? (this.chunks[index].content.length / result.summary.length).toFixed(1) + 'x' : 'N/A'}</div>
        <div class="stat-chip">📊 关键词：${result.keywords ? result.keywords.join(', ') : 'N/A'}</div>
      `;
    } else {
      document.getElementById('subq-list').innerHTML = `<div style="padding: 16px; text-align: center; color: var(--text3);">该 Chunk 尚未生成增强内容</div>`;
      document.getElementById('summary-box').innerHTML = `<div style="padding: 16px; text-align: center; color: var(--text3);">该 Chunk 尚未生成增强内容</div>`;
      document.getElementById('gen-stats').innerHTML = '';
    }
    
    this.updateGenChunkList();
  },

  async renderStep4(container) {
    container.innerHTML = `
      <div class="pipeline-panel">
        <div class="pipeline-panel-header">
          <div class="panel-icon" style="background: var(--green-bg);">🚀</div>
          <div>
            <div class="panel-title">Step 4 · 嵌入向量化 & 导入 Milvus</div>
            <div class="panel-subtitle">生成向量嵌入并写入向量数据库，完成知识库构建</div>
          </div>
          <div style="flex: 1;"></div>
          <span class="api-tag"><span class="api-method post">POST</span>/api/process/import/{file_id}</span>
          <span class="badge ${this.steps[3].status === 'done' ? 'badge-green' : this.steps[3].status === 'active' ? 'badge-blue' : 'badge-gray'}">
            ${this.steps[3].status === 'done' ? '✓ 已完成' : this.steps[3].status === 'active' ? '⚡ 进行中' : '· 等待中'}
          </span>
        </div>

        <!-- 导入成功状态 -->
        <div class="import-success-layout">
          <div class="success-circle">✅</div>
          <div class="success-title">导入 Milvus 成功！</div>
          <div class="success-subtitle">
            文档 <strong>${this.documentData?.filename || '未知文件'}</strong> 已完成全部处理流程，知识库已就绪。
          </div>

          <!-- 统计卡片：先用占位符，数据回来后由 _fillImportStats() 填充 -->
          <div class="milvus-stats-grid">
            <div class="milvus-stat-card">
              <span class="milvus-stat-val" id="stat-chunk-count">
                <span class="loading-spinner" style="width:18px;height:18px;border-width:2px;display:inline-block;"></span>
              </span>
              <div class="milvus-stat-label">Chunk 总数</div>
            </div>
            <div class="milvus-stat-card">
              <span class="milvus-stat-val" id="stat-vector-count">
                <span class="loading-spinner" style="width:18px;height:18px;border-width:2px;display:inline-block;"></span>
              </span>
              <div class="milvus-stat-label">向量总数</div>
            </div>
            <div class="milvus-stat-card">
              <span class="milvus-stat-val" id="stat-subq-count">
                <span class="loading-spinner" style="width:18px;height:18px;border-width:2px;display:inline-block;"></span>
              </span>
              <div class="milvus-stat-label">子问题向量</div>
            </div>
            <div class="milvus-stat-card">
              <span class="milvus-stat-val" id="stat-vec-dim" style="color: var(--green)">
                <span class="loading-spinner" style="width:18px;height:18px;border-width:2px;display:inline-block;"></span>
              </span>
              <div class="milvus-stat-label">向量维度</div>
            </div>
          </div>

          <!-- 处理时间线：id 化，数据回来后回填 -->
          <div class="milvus-timeline" style="max-width: 600px; width: 100%; margin-top: 30px;">
            <div class="timeline-item">
              <span class="timeline-icon">📤</span>
              <span class="timeline-label">PDF 上传 & 解析</span>
              <span class="timeline-status">✓ 完成</span>
              <span class="timeline-time" id="tl-upload">-</span>
            </div>
            <div class="timeline-item">
              <span class="timeline-icon">✂️</span>
              <span class="timeline-label">文档切割 (<span id="tl-chunk-count">${this.chunks.length || '?'}</span> Chunks)</span>
              <span class="timeline-status">✓ 完成</span>
              <span class="timeline-time" id="tl-split">-</span>
            </div>
            <div class="timeline-item">
              <span class="timeline-icon">🧠</span>
              <span class="timeline-label">LLM 生成子问题 & 摘要</span>
              <span class="timeline-status">✓ 完成</span>
              <span class="timeline-time" id="tl-generate">-</span>
            </div>
            <div class="timeline-item">
              <span class="timeline-icon">⚡</span>
              <span class="timeline-label">嵌入向量生成</span>
              <span class="timeline-status">✓ 完成</span>
              <span class="timeline-time" id="tl-embed">-</span>
            </div>
            <div class="timeline-item">
              <span class="timeline-icon">🗄️</span>
              <span class="timeline-label">写入 Milvus Collection</span>
              <span class="timeline-status">✓ 完成</span>
              <span class="timeline-time" id="tl-import">-</span>
            </div>
          </div>
        </div>

        <div class="pipeline-action-bar">
          <div class="action-info" id="step4-total-time">
            总耗时 <strong style="color: var(--green)">计算中...</strong> · Collection: <strong style="color: var(--text)">rag_knowledge_base</strong>
          </div>
          <button class="btn btn-ghost" onclick="PipelinePage.previousStep()">
            ← 返回生成
          </button>
          <button class="btn btn-primary" onclick="window.App.navigate('search')">
            🔍 去检索验证
          </button>
          <button class="btn btn-success" onclick="window.App.navigate('documents')">
            + 处理下一个文档
          </button>
        </div>
      </div>
    `;
    
    // 加载导入结果
    await this.loadImportResults();
  },

  async loadImportResults() {
    try {
      const startTime = Date.now();
      const response = await window.DocumentAPI.importToMilvus(this.currentDocId);
      const endTime = Date.now();
      // 优先使用后端返回的处理时间，其次使用前端计算的时间
      this.timings.import = response.processing_time_ms !== undefined ? response.processing_time_ms : (endTime - startTime);
      
      // 从response中提取信息，如果没有详细信息，使用默认值
      // 时间格式化函数，将毫秒转换为合适的单位并保留两位小数
      const formatTime = (ms) => {
        if (!ms) return 'N/A';
        if (ms < 1000) {
          return ms.toFixed(2) + 'ms';
        } else {
          return (ms / 1000).toFixed(2) + 's';
        }
      };
      
      const totalTimeMs = this.timings.upload + this.timings.split + this.timings.generate + this.timings.import;
      
      this.importResults = {
        chunk_count: response.chunk_count || this.chunks.length || 0,
        vector_count: response.vector_count || this.chunks.length || 0,
        sub_question_count: response.sub_question_count || Object.keys(this.generationResults).length || 0,
        vector_dim: response.vector_dim || 1024,
        total_time: formatTime(totalTimeMs),
        timeline: {
          upload: formatTime(this.timings.upload),
          split: formatTime(this.timings.split),
          generate: formatTime(this.timings.generate),
          embed: 'N/A',
          import: formatTime(this.timings.import)
        }
      };
      
      // 从响应中提取vector_count和vector_dim
      if (response.vector_count) {
        this.stats.vectorCount = response.vector_count;
      }
      if (response.vector_dim) {
        this.stats.vectorDim = response.vector_dim;
      }
      
      // 立即回填统计数据到 DOM，无需用户重新点击
      this._fillImportStats();
      
      // 加载全局统计信息
      await this.loadStatsOverview();

      // import 成功，标记 step4 为 done
      if (this.steps[3] && this.steps[3].status !== 'done') {
        this.steps[3].status = 'done';
        this.updateStepsUI();
      }
    } catch (error) {
      window.App.showToast('加载导入结果失败: ' + error.message, 'error');
      // 即使失败也要回填（显示 0）
      this._fillImportStats();
    }
  },

  /** 将 importResults / stats 数据回填到 Step4 DOM 中（不重渲染整个页面） */
  _fillImportStats() {
    const r = this.importResults || {};
    const s = this.stats;

    // 统计卡片
    const setEl = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };
    setEl('stat-chunk-count',  s.chunksCount  || r.chunk_count         || this.chunks.length || 0);
    setEl('stat-vector-count', s.vectorCount   || r.vector_count        || 0);
    setEl('stat-subq-count',   s.subQuestionsCount || r.sub_question_count || 0);
    setEl('stat-vec-dim',      s.vectorDim     || r.vector_dim          || 1024);

    // 时间线
    const tl = r.timeline || {};
    // 时间格式化函数，将毫秒转换为合适的单位并保留两位小数
    const formatTime = (ms) => {
      if (!ms) return 'N/A';
      if (ms < 1000) {
        return ms.toFixed(2) + 'ms';
      } else {
        return (ms / 1000).toFixed(2) + 's';
      }
    };
    setEl('tl-upload',   tl.upload   || formatTime(this.timings.upload));
    setEl('tl-split',    tl.split    || formatTime(this.timings.split));
    setEl('tl-generate', tl.generate || formatTime(this.timings.generate));
    setEl('tl-embed',    tl.embed    || 'N/A');
    setEl('tl-import',   tl.import   || formatTime(this.timings.import));
    setEl('tl-chunk-count', this.chunks.length || r.chunk_count || 0);

    // action bar 总耗时
    const totalBar = document.getElementById('step4-total-time');
    if (totalBar) {
      // 时间格式化函数，将毫秒转换为合适的单位并保留两位小数
      const formatTime = (ms) => {
        if (!ms) return '0.00s';
        if (ms < 1000) {
          return ms.toFixed(2) + 'ms';
        } else {
          return (ms / 1000).toFixed(2) + 's';
        }
      };
      const totalTime = r.total_time || formatTime(this.timings.upload + this.timings.split + this.timings.generate + this.timings.import);
      totalBar.innerHTML = `总耗时 <strong style="color: var(--green)">${totalTime}</strong> · Collection: <strong style="color: var(--text)">rag_knowledge_base</strong>`;
    }
  },

  async loadStatsOverview() {
    try {
      const response = await window.DocumentAPI.getStatsOverview();
      // 检查response是否包含data字段
      const stats = response.data || response;
      
      // 更新全局统计信息
      document.getElementById('global-documents').textContent = stats.total_documents || 0;
      document.getElementById('global-chunks').textContent = stats.total_chunks || 0;
      document.getElementById('global-sub-questions').textContent = stats.total_sub_questions || 0;
      document.getElementById('global-summaries').textContent = stats.total_summaries || 0;
      
      // 如果是admin用户，添加用户统计
      if (stats.is_admin) {
        const statsGrid = document.querySelector('div[style*="grid-template-columns: repeat(auto-fit, minmax(200px, 1fr))"]');
        if (statsGrid) {
          // 检查是否已存在用户统计卡片
          if (!document.getElementById('global-users')) {
            const userCard = document.createElement('div');
            userCard.style.cssText = 'padding: 16px; background: var(--surface1); border-radius: 8px; border: 1px solid var(--border);';
            userCard.innerHTML = `
              <div style="font-size: .8rem; color: var(--text3); margin-bottom: 8px;">👥 总用户数</div>
              <div style="font-size: 1.5rem; font-weight: 700; color: var(--text);" id="global-users">${stats.total_users || 0}</div>
            `;
            statsGrid.appendChild(userCard);
          }
        }
      }
    } catch (error) {
      console.error('加载统计概览失败:', error);
      // 加载失败时不显示错误，保持默认的"加载中..."状态
    }
  },

  async nextStep() {
    if (this.currentStep < this.steps.length - 1) {
      // 显示加载状态
      this.showLoading('正在处理');
      
      try {
        // 检查当前步骤是否已完成
        if (this.steps[this.currentStep].status !== 'done') {
          // 根据当前步骤执行相应的处理
          switch (this.currentStep) {
            case 0:
              // Step 1: 解析PDF -> Markdown（已经完成）
              this.steps[this.currentStep].status = 'done';
              break;
            case 1:
              // Step 2: 文档切割
              try {
                this.showLoading('正在处理');
                await window.DocumentAPI.split(this.currentDocId);
                this.steps[this.currentStep].status = 'done';
                window.App.showToast('处理完成', 'success');
              } catch (error) {
                window.App.showToast('处理失败: ' + error.message, 'error');
                this.hideLoading();
                return;
              }
              break;
            case 2:
              // Step 3: 生成增强
              try {
                this.showLoading('正在处理');
                await window.DocumentAPI.generate(this.currentDocId);
                this.steps[this.currentStep].status = 'done';
                window.App.showToast('处理完成', 'success');
              } catch (error) {
                window.App.showToast('处理失败: ' + error.message, 'error');
                this.hideLoading();
                return;
              }
              break;
          }
        }
        
        // 跳转到下一步
        this.currentStep++;
        
        // 检查是否是嵌入入库步骤，且文档状态已完成
        if (this.currentStep === 3 && this.documentData?.status === 'completed') {
          // 文档已完成，跳过嵌入入库步骤
          this.steps[this.currentStep].status = 'done';
          window.App.showToast('文档已完成处理，跳过嵌入入库步骤', 'info');
          this.updateStepsUI();
          await this.renderStepContent();
        } else {
          // 如果是嵌入入库步骤，renderStep4 内部会调用 loadImportResults
          if (this.currentStep === 3) {
            // 不在这里调 API，renderStep4 -> loadImportResults 会统一处理
            this.steps[this.currentStep].status = 'active';
          } else {
            this.steps[this.currentStep].status = 'active';
          }
          this.updateStepsUI();
          await this.renderStepContent();
        }
      } catch (error) {
        window.App.showToast('操作失败: ' + error.message, 'error');
      } finally {
        // 隐藏加载状态
        this.hideLoading();
      }
    }
  },

  previousStep() {
    if (this.currentStep > 0) {
      this.steps[this.currentStep].status = 'pending';
      this.currentStep--;
      this.steps[this.currentStep].status = 'active';
      this.updateStepsUI();
      this.renderStepContent();
    }
  },

  downloadMarkdown() {
    if (!this.markdownContent) {
      window.App.showToast('暂无 Markdown 内容', 'error');
      return;
    }
    
    const blob = new Blob([this.markdownContent], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = (this.documentData?.filename?.replace('.pdf', '.md') || 'document.md');
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  showLoading(message = '加载中...') {
    // 检查是否已存在加载元素
    let loadingElement = document.getElementById('pipeline-loading');
    if (!loadingElement) {
      loadingElement = document.createElement('div');
      loadingElement.id = 'pipeline-loading';
      loadingElement.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 9999;
        flex-direction: column;
        color: white;
        font-size: 16px;
      `;
      document.body.appendChild(loadingElement);
    }
    
    loadingElement.innerHTML = `
      <div style="text-align: center;">
        <div class="loading-spinner" style="width: 50px; height: 50px; border: 4px solid rgba(255, 255, 255, 0.3); border-top: 4px solid white; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 20px;"></div>
        <div>${message}</div>
      </div>
      <style>
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      </style>
    `;
    loadingElement.style.display = 'flex';
  },

  hideLoading() {
    const loadingElement = document.getElementById('pipeline-loading');
    if (loadingElement) {
      loadingElement.style.display = 'none';
    }
  }
};

window.PipelinePage = PipelinePage;