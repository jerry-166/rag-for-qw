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
        <div class="glass"><div class="state">
          <div class="glyph" style="color:var(--danger)">✕</div>
          <div class="title">文档ID缺失</div>
          <div class="desc">请从文档管理页面选择一个文档进行处理</div>
          <button class="btn btn-sm" onclick="window.App.navigate('documents')">返回文档管理</button>
        </div></div>
      `;
      return;
    }
    
    container.innerHTML = `
      <div class="row between mb4">
        <button class="btn btn-sm btn-ghost" id="pipe-back-btn">← 返回文档管理</button>
        <span class="badge" id="pipe-file-badge">${this.documentData ? '' : '加载中…'}</span>
        <div class="spacer"></div>
        <span class="t3 mono" id="pipe-meta-note" style="font-size:var(--fs-xs)"></span>
      </div>
      <div class="glass p6 mb4" id="stepper-card">
        <div class="stepper" id="pipeline-steps">
          ${this.steps.map((step, index) => `
            <div class="step ${step.status === 'done' ? 'done' : step.status === 'active' ? 'running' : ''}" data-step="${index}">
              <span class="orb">${step.status === 'done' ? '✓' : index + 1}</span>
              <div><div class="s-name">${step.title}</div><div class="s-sub num" data-sub="${index}">${step.status === 'done' ? '完成' : '等待'}</div></div>
            </div>
            ${index < this.steps.length - 1 ? `<div class="step-link" data-link="${index}"><i style="transform:scaleX(0)"></i></div>` : ''}
          `).join('')}
        </div>
        <div class="num row between mt6" id="stepper-detail" style="font-size:var(--fs-sm)"></div>
        <div class="progress mt2" id="stepper-progress"><i style="width:0%"></i></div>
      </div>

      <div class="grid stats mb4" id="pipe-stats" style="display:none"></div>
      <div id="pipe-error-card" style="display:none"></div>

      <div id="step-content">
        <div class="skeleton" style="height:200px"></div>
      </div>
    `;

    const backBtn = document.getElementById('pipe-back-btn');
    if (backBtn) backBtn.addEventListener('click', () => window.App.navigate('documents'));
    // 步骤切换点击
    document.querySelectorAll('#pipeline-steps .step').forEach(el => {
      el.addEventListener('click', () => this.goToStep(parseInt(el.dataset.step)));
    });
    
    try {
      await this.loadDocumentInfo();
      await this.refreshProgress();
      const badge = document.getElementById('pipe-file-badge');
      if (badge) badge.textContent = this.documentData?.filename || this.currentDocId;
      const note = document.getElementById('pipe-meta-note');
      if (note) note.textContent = `file_id ${this.currentDocId} · stage: ${this._lastProgress?.stage || '—'}`;
      await this.renderStepContent();
    } catch (error) {
      console.error('渲染流水线页面失败:', error);
      container.innerHTML = `
        <div class="glass"><div class="state">
          <div class="glyph" style="color:var(--danger)">✕</div>
          <div class="title">页面加载失败</div>
          <div class="desc">${error.message || '未知错误'}</div>
          <button class="btn btn-sm" onclick="window.App.navigate('documents')">返回文档管理</button>
        </div></div>
      `;
    }
  },

  async loadDocumentInfo() {
    try {
      // 直接用 getPreview 获取文档基本信息（包含 status 和时间字段）
      // 不再使用 getResult 做探针——它要求 status=completed，新文档必然失败，白白浪费一次请求
      let docStatus = 'uploaded'; // 默认状态
      
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
        console.error('加载文档信息失败:', e);
        window.App.showToast('加载文档信息失败，使用默认状态', 'warning');
        this.documentData = { filename: '未知文件', status: 'uploaded', file_size: 0 };
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
    if (!stepsContainer) return;

    // 由 progress 数据推导 stepper 状态（优先），否则回退到 steps 数组
    const p = this._lastProgress;
    let fill = [0, 1, 1, 1]; // 每条连线填充比例（进入下一步的程度）
    let stageIdx = this.currentStep; // 当前进行中的步骤下标（0-3）
    if (p) {
      const stage = p.stage;
      const sp = p.stage_progress || {};
      let ratio = 0;
      if (sp.total > 0) ratio = Math.min(sp.done / sp.total, 1);
      if (stage === 'awaiting_split') { stageIdx = 1; fill = [1, 0, 0, 0]; }
      else if (stage === 'generating') { stageIdx = 2; fill = [1, ratio, 0, 0]; }
      else if (stage === 'awaiting_import') { stageIdx = 3; fill = [1, 1, 0, 0]; }
      else if (stage === 'importing') { stageIdx = 3; fill = [1, 1, 1, 0.5]; }
      else if (stage === 'done') { stageIdx = 4; fill = [1, 1, 1, 1]; }
      else if (stage === 'failed') { stageIdx = this.currentStep; }
      this._stageRatio = ratio;
    } else {
      // 无 progress 数据时按 steps 数组推导
      let done = -1;
      for (let i = 0; i < 4; i++) if (this.steps[i].status === 'done' || this.steps[i].status === 'active') done = i;
      fill = fill.map((_, i) => (i < done ? 1 : 0));
      this._stageRatio = 0;
    }

    stepsContainer.innerHTML = this.steps.map((step, index) => {
      const cls = index < stageIdx ? 'done' : (index === stageIdx && stageIdx < 4 ? 'running' : '');
      const sub = this._stepSubtitle(index, p);
      return `
        <div class="step ${cls}" data-step="${index}">
          <span class="orb">${index < stageIdx || stageIdx >= 4 ? '✓' : index + 1}</span>
          <div><div class="s-name">${step.title}</div><div class="s-sub num" data-sub="${index}">${sub}</div></div>
        </div>
        ${index < this.steps.length - 1 ? `<div class="step-link" data-link="${index}"><i style="transform:scaleX(${fill[index]})"></i></div>` : ''}
      `;
    }).join('');
    stepsContainer.querySelectorAll('.step').forEach(el => {
      el.addEventListener('click', () => this.goToStep(parseInt(el.dataset.step)));
    });

    // 吞吐明细行 + 阶段进度条
    this._renderStepperDetail(p);
    // 6 统计卡 + 失败卡
    this._renderStats(p);
  },

  /** 步骤副标题：真实 timing_ms / stage_progress */
  _stepSubtitle(index, p) {
    const t = (p && p.timing_ms) || this.timings || {};
    const fmt = this._fmtTime;
    if (index === 0) return this.documentData?.upload_time != null ? fmt(this.documentData.upload_time) : '完成';
    if (index === 1) {
      const parts = [];
      if (t.split_time != null || this.timings.split) parts.push(fmt(t.split_time ?? this.timings.split));
      if (p?.total_chunks) parts.push(p.total_chunks + ' chunks');
      if (parts.length) return parts.join(' · ');
      return this.steps[1].status === 'done' ? '完成' : '等待';
    }
    if (index === 2) {
      const sp = p?.stage_progress;
      if (sp && sp.total > 0) return `${sp.done}/${sp.total}`;
      if (t.generate_time != null || this.timings.generate) return fmt(t.generate_time ?? this.timings.generate);
      return this.steps[2].status === 'done' ? '完成' : '等待';
    }
    if (index === 3) {
      if (t.import_time != null || this.timings.import) return fmt(t.import_time ?? this.timings.import);
      return this.steps[3].status === 'done' ? '完成' : '等待';
    }
    return '';
  },

  _fmtTime(ms) {
    if (ms == null || isNaN(ms)) return '—';
    return ms < 1000 ? Math.round(ms) + 'ms' : (ms / 1000).toFixed(1) + 's';
  },

  /** 吞吐明细行：本阶段进度 / 已运行 / 预计剩余 + 历史耗时；底部进度条 */
  _renderStepperDetail(p) {
    const detail = document.getElementById('stepper-detail');
    const bar = document.querySelector('#stepper-progress > i');
    if (!detail) return;
    if (!p) {
      detail.innerHTML = `<span class="t3">等待进度数据…</span>`;
      return;
    }
    const sp = p.stage_progress || {};
    const ratio = this._stageRatio || 0;
    if (bar) bar.style.width = Math.round(ratio * 100) + '%';

    const t = p.timing_ms || {};
    const hist = ['切割', '生成', '导入']
      .map(([label, key]) => t[key + '_time'] != null ? `${label} ${this._fmtTime(t[key + '_time'])}` : null)
      .filter(Boolean);
    const map = { 切割: 'split', 生成: 'generate', 导入: 'import' };
    const histStr = ['切割', '生成', '导入']
      .map(l => t[map[l] + '_time'] != null ? `${l} ${this._fmtTime(t[map[l] + '_time'])}` : null)
      .filter(Boolean).join(' · ');

    if (p.stage === 'done') {
      detail.innerHTML = `<span>全部完成 · 共 <b class="num">${p.total_chunks}</b> chunks</span>
        <span class="t3" style="font-size:var(--fs-xs)">历史耗时：${histStr || '—'}</span>`;
      if (bar) bar.style.width = '100%';
      return;
    }
    if (p.stage === 'failed') {
      detail.innerHTML = `<span style="color:var(--danger)">处理失败${p.last_error ? ' · ' + this._esc(p.last_error.message || '') : ''}</span>
        <span class="t3" style="font-size:var(--fs-xs)">历史耗时：${histStr || '—'}</span>`;
      return;
    }
    const stageName = { awaiting_split: '文档切割', generating: '生成增强', awaiting_import: '嵌入入库', importing: '嵌入入库' }[p.stage] || p.stage;
    detail.innerHTML = `
      <span>当前阶段 <b>${stageName}</b>${sp.total > 0 ? ` · 进度 <b class="num">${sp.done}/${sp.total}</b>` : ''}</span>
      <span class="t3" style="font-size:var(--fs-xs)">历史耗时：${histStr || '—'}</span>`;
  },

  /** 6 统计卡 + 失败卡（线框 03 §全文档累计统计带 / 失败态） */
  _renderStats(p) {
    const el = document.getElementById('pipe-stats');
    const errEl = document.getElementById('pipe-error-card');
    if (!el) return;
    const s = this.stats;
    const t = (p && p.timing_ms) || this.timings || {};
    const chunksCount = s.chunksCount || (p && p.total_chunks) || 0;
    if (chunksCount > 0) {
      const avgChars = this.chunks.length > 0
        ? Math.round(this.chunks.reduce((a, c) => a + (c.content ? c.content.length : 0), 0) / this.chunks.length)
        : 0;
      const subqCount = s.subQuestionsCount;
      const summaryCount = s.summariesCount;
      const entityCount = s.entityCount || 0;
      const vectorCount = s.vectorCount;
      const vectorDim = s.vectorDim;
      const totalMs = (t.split_time || 0) + (t.generate_time || 0) + (t.import_time || 0);
      const parts = [];
      if (t.split_time != null) parts.push(`切割 ${this._fmtTime(t.split_time)}`);
      if (t.generate_time != null) parts.push(`生成 ${this._fmtTime(t.generate_time)}`);
      if (t.import_time != null) parts.push(`导入 ${this._fmtTime(t.import_time)}`);
      el.style.display = '';
      el.innerHTML = `
        <div class="glass p4"><div class="label-caps">Chunks</div><b class="num" style="font-size:var(--fs-2xl)">${chunksCount}</b><div class="t3" style="font-size:var(--fs-xs)">平均 ${avgChars} 字/chunk</div></div>
        <div class="glass p4"><div class="label-caps">子问题</div><b class="num" style="font-size:var(--fs-2xl)">${subqCount || '—'}</b><div class="t3" style="font-size:var(--fs-xs)">${summaryCount > 0 ? '均 ' + (subqCount / Math.max(summaryCount, 1)).toFixed(1) + ' 个/chunk' : '待生成'}</div></div>
        <div class="glass p4"><div class="label-caps">摘要</div><b class="num" style="font-size:var(--fs-2xl)">${summaryCount || '—'}</b><div class="t3" style="font-size:var(--fs-xs)">已生成 ${summaryCount} chunk</div></div>
        <div class="glass p4"><div class="label-caps">实体</div><b class="num" style="font-size:var(--fs-2xl)">${entityCount || '—'}</b><div class="t3" style="font-size:var(--fs-xs)">${entityCount ? `关系 ${s.entityRelationCount || '?'} 条` : '未启用'}</div></div>
        <div class="glass p4"><div class="label-caps">向量</div><b class="num" style="font-size:var(--fs-2xl)">${vectorCount || '—'}</b><div class="t3" style="font-size:var(--fs-xs)">${vectorCount ? `维度 ${vectorDim}` : '待导入'}</div></div>
        <div class="glass p4"><div class="label-caps">累计耗时</div><b class="num" style="font-size:var(--fs-2xl)">${totalMs > 0 ? this._fmtTime(totalMs) : '—'}</b><div class="t3" style="font-size:var(--fs-xs)">${parts.join(' + ') || '—'}</div></div>
      `;
    } else {
      el.style.display = 'none';
    }
    // 失败卡
    if (errEl) {
      if (p && p.last_error) {
        const e = p.last_error;
        errEl.style.display = '';
        errEl.innerHTML = `
          <div class="glass p5 mt4" style="border-color:var(--danger)">
            <div class="row between">
              <div class="row" style="gap:var(--sp-3)">
                <span style="color:var(--danger);font-size:20px">✕</span>
                <div>
                  <b>${e.operation || '处理'}阶段失败</b>
                  <p class="t2 mono" style="font-size:var(--fs-xs)">${e.operation || ''} · ${this._esc(e.message || '')} · ${e.at || ''}</p>
                </div>
              </div>
              <button class="btn btn-sm btn-primary" onclick="PipelinePage.retryFromFailure()">从失败点重试</button>
            </div>
          </div>`;
      } else {
        errEl.style.display = 'none';
      }
    }
  },

  retryFromFailure() {
    const p = this._lastProgress;
    if (!p || !p.last_error) return;
    const op = p.last_error.operation || '';
    if (op.includes('split') || op.includes('import')) {
      this.currentStep = op.includes('split') ? 1 : 3;
      this.renderStepContent();
    } else {
      this.currentStep = 2;
      this.renderStepContent();
    }
  },

  _esc(s) { return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },

  /** 拉取进度接口并刷新 stepper（页面进入 + 各阶段操作后调用） */
  async refreshProgress() {
    try {
      const p = await window.DocumentAPI.getProgress(this.currentDocId);
      this._lastProgress = p;
      // timing_ms 回填（真实历史耗时替代 N/A）
      if (p.timing_ms) {
        if (p.timing_ms.split_time != null) this.timings.split = p.timing_ms.split_time;
        if (p.timing_ms.generate_time != null) this.timings.generate = p.timing_ms.generate_time;
        if (p.timing_ms.import_time != null) this.timings.import = p.timing_ms.import_time;
      }
      if (p.total_chunks) this.stats.chunksCount = p.total_chunks;
      // 步骤 done 标记同步（断点恢复：重进页面时按状态机点亮）
      const st = p.document_status;
      if (st === 'completed') this.steps.forEach(s => s.status = 'done');
      else if (st === 'generated') { this.steps[0].status = this.steps[1].status = this.steps[2].status = 'done'; }
      else if (st === 'chunk_done') { this.steps[0].status = this.steps[1].status = 'done'; }
      this.updateStepsUI();
    } catch { /* 进度接口失败不阻断页面 */ }
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
    const stepStatus = this.steps[0].status;
    container.innerHTML = `
      <div class="glass p6">
        <div class="row between mb4">
          <div class="row" style="gap:var(--sp-3)">
            <span style="font-size:24px">📄</span>
            <div>
              <h2 class="h-section">Step 1 · PDF 解析 → Markdown 转换</h2>
              <p class="t3 mt2" style="font-size:var(--fs-xs)">对比原始 PDF 和结构化 Markdown 内容</p>
            </div>
          </div>
          <div class="row" style="gap:var(--sp-2)">
            <span class="badge ${stepStatus === 'done' ? 'ok' : stepStatus === 'active' ? 'info' : ''}">${stepStatus === 'done' ? '✓ 已完成' : stepStatus === 'active' ? '⚡ 进行中' : '· 等待中'}</span>
          </div>
        </div>

        <div class="grid" style="grid-template-columns:1fr 1fr;gap:var(--sp-4)">
          <div class="glass">
            <div class="row between p4" style="border-bottom:1px solid var(--glass-border)">
              <span class="badge info">PDF</span>
              <span class="t3" style="font-size:var(--fs-xs)">${this.documentData?.filename || '未知文件'}</span>
            </div>
            <div id="pdf-viewer" style="height:400px;overflow:auto">
              <div class="state"><div class="glyph float-anim">📄</div><p class="desc">加载 PDF 中...</p></div>
            </div>
          </div>
          <div class="glass">
            <div class="row between p4" style="border-bottom:1px solid var(--glass-border)">
              <span class="badge ok">MD</span>
              <span class="t3" style="font-size:var(--fs-xs);color:var(--ok)">✓ 表格/公式已结构化</span>
            </div>
            <div id="markdown-viewer" style="height:400px;overflow:auto;padding:var(--sp-4)">
              <div class="skeleton" style="height:100%"></div>
            </div>
          </div>
        </div>

        <div class="row between mt6" style="border-top:1px solid var(--glass-border);padding-top:var(--sp-4)">
          <span class="t2" style="font-size:var(--fs-sm)">解析完成 · 识别到 <b class="num">${this.documentData?.tables_count || 0}</b> 张表格、<b class="num">${this.documentData?.formulas_count || 0}</b> 个公式 · <span class="t3">文件大小: ${this.documentData ? (this.documentData.file_size / 1024 / 1024).toFixed(2) + ' MB' : '未知'}</span></span>
          <div class="row" style="gap:var(--sp-2)">
            <button class="btn btn-sm" onclick="PipelinePage.downloadMarkdown()">↓ 下载 MD</button>
            <button class="btn btn-sm" onclick="PipelinePage.downloadPDF()">↓ 下载 PDF</button>
            <button class="btn btn-primary btn-sm" onclick="PipelinePage.nextStep()">下一步：切割 →</button>
          </div>
        </div>
      </div>
    `;

    await this.loadMarkdown();
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
        <div class="state"><div class="glyph" style="color:var(--danger)">✕</div><div class="title">加载 PDF 失败</div><p class="desc">${error.message}<br>文件大小: ${this.documentData ? (this.documentData.file_size / 1024 / 1024).toFixed(2) + ' MB' : '未知'}</p></div>
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
        <div class="state"><div class="glyph">📄</div><div class="title">${this.documentData?.filename || 'PDF 文件'}</div><a href="${pdfUrl}" target="_blank" class="btn btn-sm btn-primary mt4">📄 打开 PDF</a><p class="t3 mt4" style="font-size:var(--fs-xs)">文件大小: ${this.documentData ? (this.documentData.file_size / 1024 / 1024).toFixed(2) + ' MB' : '未知'}</p></div>
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
      document.getElementById('markdown-viewer').innerHTML = `<div class="state"><div class="glyph" style="color:var(--danger)">✕</div><div class="title">加载失败</div><p class="desc">${error.message}</p></div>`;
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
    const stepStatus = this.steps[1].status;
    container.innerHTML = `
      <div class="glass p6">
        <div class="row between mb4">
          <div class="row" style="gap:var(--sp-3)">
            <span style="font-size:24px">✂</span>
            <div>
              <h2 class="h-section">Step 2 · 文档切割 · Chunk 预览</h2>
              <p class="t3 mt2" style="font-size:var(--fs-xs)">基于语义边界切割，点击左侧 Chunk 查看内容</p>
            </div>
          </div>
          <span class="badge ${stepStatus === 'done' ? 'ok' : stepStatus === 'active' ? 'info' : ''}">${stepStatus === 'done' ? '✓ 已完成' : stepStatus === 'active' ? '⚡ 进行中' : '· 等待中'}</span>
        </div>

        <div class="glass p4 row between mb4" style="font-size:var(--fs-sm)">
          <span class="t3" style="font-size:var(--fs-xs)">完整 Markdown：</span>
          <span class="mono t2">${this.documentData?.filename?.replace('.pdf', '.md') || 'unknown.md'}</span>
          <div class="spacer"></div>
          <span class="t3 mono num" id="md-bar-timing" style="font-size:var(--fs-xs)">${this.timings.split ? this._fmtTime(this.timings.split) : ''}</span>
          <span class="badge ok">已切割 ${this.chunks.length || 0} 个 Chunk</span>
        </div>

        <div class="grid" style="grid-template-columns:300px 1fr;gap:var(--sp-4)">
          <div class="glass col" style="gap:0;max-height:500px">
            <div class="row between p4" style="border-bottom:1px solid var(--glass-border)">
              <span class="label-caps">Chunk 列表</span>
              <span class="badge num">${this.chunks.length || 0}</span>
            </div>
            <div id="chunk-list" style="overflow:auto;flex:1">
              <div class="skeleton" style="height:60px;margin:var(--sp-2)"></div>
            </div>
          </div>
          <div class="glass p5 col" style="gap:var(--sp-3)">
            <div class="row between" id="chunk-detail-title"><span class="t2" style="font-size:var(--fs-sm)">选择一个 Chunk 查看详情</span></div>
            <div id="chunk-detail-content" class="mono t2" style="font-size:var(--fs-xs);white-space:pre-wrap;background:var(--glass-1-bg);border-radius:var(--r-sm);padding:var(--sp-3);max-height:300px;overflow:auto">
              <p class="t3">点击左侧 Chunk 列表查看详情</p>
            </div>
            <div class="row wrap" id="chunk-stats" style="gap:6px"></div>
          </div>
        </div>

        <div class="row between mt6" style="border-top:1px solid var(--glass-border);padding-top:var(--sp-4)">
          <span class="t2" style="font-size:var(--fs-sm)">共 <b class="num">${this.chunks.length || 0}</b> 个 Chunk · 平均 <b class="num">~${this.chunks.length ? Math.round(this.chunks.reduce((sum, chunk) => sum + (typeof chunk === 'string' ? chunk.length : chunk.content.length), 0) / this.chunks.length) : 0}</b> 字符/Chunk</span>
          <div class="row" style="gap:var(--sp-2)">
            <button class="btn btn-sm btn-ghost" onclick="PipelinePage.previousStep()">← 返回解析</button>
            <button class="btn btn-sm btn-primary" onclick="PipelinePage.nextStep()">下一步：生成增强 →</button>
          </div>
        </div>
      </div>
    `;

    await this.loadChunks();
  },

  async loadChunks() {
    try {
      // 直接调用 split 接口（后端有幂等保护：已切割的文档会直接返回缓存结果）
      // 不再使用 getResult 做探针——新文档必然失败，白白浪费一次请求
      const startTime = Date.now();
      this.showLoading('正在切割文档...');
      const response = await window.DocumentAPI.split(this.currentDocId);
      this.hideLoading();
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
      
      // 切割完成后标记步骤完成（如果尚未标记）
      if (this.steps[1] && this.steps[1].status !== 'done') {
        this.steps[1].status = 'done';
      }
      this.refreshProgress();

      this.updateChunkList();
    } catch (error) {
      this.hideLoading();
      const el = document.getElementById('chunk-list');
      if (el) el.innerHTML = `<div class="state"><div class="glyph" style="color:var(--danger)">✕</div><p class="desc">加载失败: ${error.message}</p></div>`;
    }
  },

  _stripMarkdown(text) {
    // 去掉 markdown 语法符号，让预览文字干净
    // 按行处理，只保留文本内容
    const lines = text.split('\n');
    const cleanedLines = lines.map(line => {
      // 检查是否是标题行
      const titleMatch = line.match(/^(#{1,6})\s+(.+)$/);
      if (titleMatch) {
        // 只保留标题文本，不保留Markdown标题符号
        return titleMatch[2]
          .replace(/\*\*(.+?)\*\*/g, '$1') // 粗体
          .replace(/\*(.+?)\*/g, '$1')     // 斜体
          .replace(/`(.+?)`/g, '$1')       // 行内代码
          .replace(/!\[.*?\]\(.*?\)/g, '[图片]') // 图片
          .replace(/\[(.+?)\]\(.*?\)/g, '$1');    // 链接
      } else {
        // 非标题行，移除所有markdown符号
        let cleaned = line
          .replace(/\*\*(.+?)\*\*/g, '$1') // 粗体
          .replace(/\*(.+?)\*/g, '$1')     // 斜体
          .replace(/`(.+?)`/g, '$1')       // 行内代码
          .replace(/!\[.*?\]\(.*?\)/g, '[图片]') // 图片
          .replace(/\[(.+?)\]\(.*?\)/g, '$1')    // 链接
          .replace(/^[-*+]\s+/, '')      // 无序列表
          .replace(/^\d+\.\s+/, '');      // 有序列表
        
        // 处理markdown表格：移除表格分隔符，但保留单元格内容
        // 避免表格分割线（如 |---|---|）占据太多预览空间
        if (cleaned.includes('|')) {
          // 移除表格分隔行（通常包含连续的 - 或 =）
          if (cleaned.match(/^[\s\|]*[-=]+[\s\|]*$/)) {
            return ''; // 表格分隔行直接忽略
          }
          // 对于表格内容行，移除 | 符号，用空格分隔单元格
          // 首先移除行首尾的 |，然后分割单元格
          cleaned = cleaned.replace(/^\||\|$/g, ''); // 移除行首尾的 |
          // 分割单元格，过滤空单元格，合并内容
          const cells = cleaned.split('|').map(cell => cell.trim()).filter(cell => cell);
          if (cells.length > 0) {
            // 取前两个单元格内容，避免表格内容过长
            cleaned = cells.slice(0, 2).join(' - ');
          } else {
            cleaned = '';
          }
        }
        
        return cleaned;
      }
    }).filter(line => line.trim() !== ''); // 过滤空行
    
    // 限制总长度，避免过长的预览
    const result = cleanedLines
      .join(' ')
      .replace(/\s{2,}/g, ' ')
      .trim();
    
    // 如果结果仍然太长，进一步截断
    return result.length > 200 ? result.substring(0, 197) + '...' : result;
  },

  _escapeHtml(text) {
    // 转义 HTML 特殊字符，防止内容中的 < > 等被解析为标签
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  updateChunkList() {
    const chunkList = document.getElementById('chunk-list');
    if (this.chunks.length === 0) {
      chunkList.innerHTML = `<div class="state"><div class="glyph">📄</div><p class="desc">暂无 Chunk 数据</p></div>`;
      return;
    }

    chunkList.innerHTML = this.chunks.map((chunk, index) => {
      const rawPreview = chunk.content.substring(0, 120);
      const cleanPreview = this._escapeHtml(this._stripMarkdown(rawPreview).substring(0, 80));
      const isActive = this.selectedChunk === index;
      return `
        <div class="chunk-item ${isActive ? 'on' : ''}" onclick="PipelinePage.selectChunk(${index})" style="display:flex;gap:var(--sp-3);padding:var(--sp-3);border-radius:var(--r-sm);cursor:pointer;border:1px solid transparent;transition:all var(--dur-2) var(--ease-out);${isActive ? 'background:var(--accent-soft);border-color:transparent' : ''}">
          <span style="width:30px;height:30px;border-radius:var(--r-xs);display:grid;place-items:center;background:var(--glass-2-bg);font-size:var(--fs-xs);font-weight:640;${isActive ? 'background:var(--accent);color:var(--accent-on)' : ''}">${index + 1}</span>
          <div>
            <div class="row between"><b style="font-size:var(--fs-sm)">Chunk #${index + 1}</b><span class="badge" style="height:18px;font-size:10px">${this._escapeHtml(chunk.type || '文本')}</span></div>
            <p class="t3" style="font-size:var(--fs-xs)">${cleanPreview}${cleanPreview.length >= 80 ? '...' : ''}</p>
          </div>
        </div>
      `;
    }).join('');
  },

  selectChunk(index) {
    this.selectedChunk = index;
    const chunk = this.chunks[index];
    const chunkObj = typeof chunk === 'string' ? { content: chunk, type: '文本' } : chunk;
    document.getElementById('chunk-detail-title').innerHTML = `
      <span class="badge accent">#${index + 1}</span>
      <span class="t2" style="font-size:var(--fs-sm)">${chunkObj.type || '文本'}</span>
      <div class="spacer"></div>
      <span class="badge">🔤 ${chunkObj.content.length} 字</span>
      <span class="badge">📏 ~${Math.round(chunkObj.content.length / 4)} tokens</span>
    `;
    document.getElementById('chunk-detail-content').textContent = chunkObj.content;
    document.getElementById('chunk-stats').innerHTML = `
      <span class="badge">📄 来源页：${chunkObj.page || '未知'}</span>
      <span class="badge">🏷️ 类型：${chunkObj.type || '文本'}</span>
    `;
    this.updateChunkList();
  },

  async renderStep3(container) {
    const stepStatus = this.steps[2].status;
    container.innerHTML = `
      <div class="glass p6">
        <div class="row between mb4">
          <div class="row" style="gap:var(--sp-3)">
            <span style="font-size:24px">🧠</span>
            <div>
              <h2 class="h-section">Step 3 · 生成子问题 & 摘要</h2>
              <p class="t3 mt2" style="font-size:var(--fs-xs)">点击左侧不同 Chunk，查看对应的子问题和摘要</p>
            </div>
          </div>
          <span class="badge ${stepStatus === 'done' ? 'ok' : stepStatus === 'active' ? 'info' : ''}">${stepStatus === 'done' ? '✓ 已完成' : stepStatus === 'active' ? '⚡ 进行中' : '· 等待中'}</span>
        </div>

        <div id="missing-banner" class="glass p4 mb4" style="display:none;background:var(--warn-bg);border-color:transparent"></div>

        <div class="grid" style="grid-template-columns:300px 1fr;gap:var(--sp-4)">
          <div class="glass col" style="gap:0;max-height:500px">
            <div class="row between p4" style="border-bottom:1px solid var(--glass-border)">
              <span class="label-caps">Chunk 明细（${this.chunks.length}）</span>
              <span class="t3" style="font-size:var(--fs-xs)">完成 ${Object.keys(this.generationResults).length} · 排队 ${Math.max(0, this.chunks.length - Object.keys(this.generationResults).length)}</span>
            </div>
            <div id="gen-chunk-list" style="overflow:auto;flex:1">
              <div class="skeleton" style="height:60px;margin:var(--sp-2)"></div>
            </div>
            <div style="padding:var(--sp-3);border-top:1px solid var(--glass-border)">
              <div class="row between mb2"><span class="t3" style="font-size:var(--fs-xs)">生成进度</span><span class="num t3" style="font-size:var(--fs-xs);color:var(--accent)">${Object.keys(this.generationResults).length} / ${this.chunks.length}</span></div>
              <div class="progress"><i style="width:${this.chunks.length ? (Object.keys(this.generationResults).length / this.chunks.length) * 100 : 0}%"></i></div>
            </div>
          </div>

          <div class="col" style="gap:var(--sp-4)">
            <div class="glass p5">
              <div class="row between mb4">
                <span class="label-caps" style="color:var(--accent)">💬 子问题</span>
                <span class="badge accent num">${this.selectedChunk !== null && this.generationResults[this.selectedChunk] ? this.generationResults[this.selectedChunk].sub_questions.length : 0}</span>
                <div class="spacer"></div>
                <span class="t3" style="font-size:var(--fs-xs)">Chunk #${this.selectedChunk !== null ? this.selectedChunk + 1 : '0'}</span>
              </div>
              <div id="subq-list" class="col" style="gap:var(--sp-2)">
                <p class="t3 center" style="font-size:var(--fs-sm)">选择一个 Chunk 查看子问题</p>
              </div>
            </div>
            <div class="glass p5">
              <div class="row between mb4">
                <span class="label-caps" style="color:var(--info)">📝 摘要</span>
                <div class="spacer"></div>
                <span class="t3 num" style="font-size:var(--fs-xs)">~${this.selectedChunk !== null && this.generationResults[this.selectedChunk] ? this.generationResults[this.selectedChunk].summary.length : 0} 字</span>
              </div>
              <div id="summary-box" class="t2" style="font-size:var(--fs-sm);line-height:1.6;border-left:2px solid var(--accent);padding-left:var(--sp-3)">
                <p class="t3">选择一个 Chunk 查看摘要</p>
              </div>
              <div class="row wrap mt4" id="gen-stats" style="gap:6px"></div>
            </div>
          </div>
        </div>

        <div class="row between mt6" style="border-top:1px solid var(--glass-border);padding-top:var(--sp-4)">
          <span class="t2" style="font-size:var(--fs-sm)">已生成 <b class="num">${Object.keys(this.generationResults).length}/${this.chunks.length}</b> 个 Chunk 的增强内容</span>
          <div class="row" style="gap:var(--sp-2)">
            <button class="btn btn-sm btn-ghost" onclick="PipelinePage.previousStep()">← 返回切割</button>
            <button class="btn btn-sm btn-primary" onclick="PipelinePage.nextStep()">下一步：嵌入入库 →</button>
          </div>
        </div>
      </div>
    `;

    await this._ensureChunksLoaded();
    await this.loadGenerationResults();
  },

  /**
   * 确保_chunks数据已加载
   * 当用户跳过第2步（文档切割）直接进入第3/4步时，
   * this.chunks仍为空数组，会导致后续读取chunk.content时报错
   * 此方法在渲染step3/4前静默加载chunks数据（后端split接口对已切割文档返回缓存）
   */
  async _ensureChunksLoaded() {
    if (this.chunks.length > 0) {
      return; // 已有数据，无需重复加载
    }
    try {
      const response = await window.DocumentAPI.split(this.currentDocId);
      if (response.chunks && Array.isArray(response.chunks)) {
        this.chunks = response.chunks.map(chunk => {
          if (typeof chunk === 'string') {
            return { content: chunk, type: '文本' };
          }
          return chunk;
        });
        if (response.chunks_count) {
          this.stats.chunksCount = response.chunks_count;
        }
        // 更新UI中的chunk计数显示
        const countBadge = document.querySelector('.chunk-count-badge');
        if (countBadge) countBadge.textContent = this.chunks.length;
      }
    } catch (error) {
      console.error('静默加载chunks失败:', error);
      // 不阻断流程，让后续方法处理空chunks的情况
    }
  },

  async loadGenerationResults() {
    try {
      // 直接调用 generate 接口（后端有幂等保护：已生成的文档会直接返回缓存结果）
      // 不再使用 getResult 做探针——新文档必然失败，白白浪费一次请求
      const startTime = Date.now();
      this.showLoading('正在生成增强内容...');
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
      
      // 生成完成后标记步骤完成（如果尚未标记）
      if (this.steps[2] && this.steps[2].status !== 'done') {
        this.steps[2].status = 'done';
      }
      this.refreshProgress();

      this.updateGenChunkList();
      // 如果有生成结果，自动选择第一个chunk
      if (Object.keys(this.generationResults).length > 0) {
        this.selectGenChunk(0);
      }

      // 文档 03 §3.5：Step 3 完成后做缺口检测（轻量查询，零 LLM 调用）
      this._checkMissingEnhancements();
    } catch (error) {
      this.hideLoading();
      const el = document.getElementById('gen-chunk-list');
      if (el) el.innerHTML = `<div class="state"><div class="glyph" style="color:var(--danger)">✕</div><p class="desc">加载失败: ${error.message}</p></div>`;
    }
  },

  /** 缺口检测：启用集 > 已生成集时显示黄色提示条 + 显性补生成按钮（文档 03） */
  async _checkMissingEnhancements() {
    const banner = document.getElementById('missing-banner');
    if (!banner) return;
    try {
      const r = await window.DocumentAPI.missingEnhancements(this.currentDocId);
      if (!r.need_backfill) {
        banner.style.display = 'none';
        return;
      }
      const parts = [];
      if (r.missing.sub_question > 0) parts.push(`子问题 ×${r.missing.sub_question}`);
      if (r.missing.summary > 0) parts.push(`摘要 ×${r.missing.summary}`);
      banner.innerHTML = `
        <div class="row" style="gap:var(--sp-3);align-items:center">
          <span style="font-size:18px;color:var(--warn)">⚠</span>
          <div class="grow">
            <b style="font-size:var(--fs-sm)">检测到增强缺口</b>
            <span class="t2" style="font-size:var(--fs-sm)"> · ${r.missing_chunks} 个 Chunk 缺失（${parts.join('、')}）</span>
          </div>
          <button class="btn btn-sm btn-primary" onclick="PipelinePage.backfillEnhancements()">一键补生成</button>
          <button class="btn btn-sm btn-ghost" onclick="document.getElementById('missing-banner').style.display='none'">忽略</button>
        </div>
      `;
      banner.style.display = 'block';
    } catch (e) {
      // 检测失败静默降级，不阻断正常流程
      banner.style.display = 'none';
    }
  },

  /** 显性补生成：用户点击后重新走 generate（后端增量模式，只补缺失字段） */
  async backfillEnhancements() {
    const banner = document.getElementById('missing-banner');
    if (banner) banner.style.display = 'none';
    window.App.showToast('开始补生成缺失增强...', 'info');
    await this.loadGenerationResults();
  },

  updateGenChunkList() {
    const chunkList = document.getElementById('gen-chunk-list');
    if (this.chunks.length === 0) {
      chunkList.innerHTML = `<div style="padding: 16px; text-align: center; color: var(--text3);">暂无 Chunk 数据</div>`;
      return;
    }
    
    chunkList.innerHTML = this.chunks.map((chunk, index) => {
      const hasResult = this.generationResults[index] !== undefined;
      const chunkObj = typeof chunk === 'string' ? { content: chunk, type: '文本' } : chunk;
      const chars = (chunkObj.content || '').length;
      const subqCount = hasResult ? this.generationResults[index].sub_questions.length : 0;
      const hasSummary = hasResult && this.generationResults[index].summary;
      const isActive = this.selectedChunk === index;
      const statusBadge = hasResult
        ? '<span class="badge ok" style="height:18px;font-size:10px">✓ ' + this._fmtTime(this.timings.generate / Math.max(this.chunks.length, 1)) + '</span>'
        : (index === this.chunks.findIndex((c, i) => !this.generationResults[i]) && this._lastProgress?.stage === 'generating'
          ? '<span class="badge warn" style="height:18px;font-size:10px">◌ 生成中</span>'
          : '<span class="badge" style="height:18px;font-size:10px">排队</span>');
      return `
        <div class="chunk-item ${isActive ? 'on' : ''}" onclick="PipelinePage.selectGenChunk(${index})">
          <span class="cid">${index + 1}</span>
          <div class="grow">
            <div class="row between"><b style="font-size:var(--fs-sm)">Chunk #${index + 1}</b>${statusBadge}</div>
            <p class="t3" style="font-size:var(--fs-xs)">${chars} 字 · ${subqCount} 子问题 · 摘要${hasSummary ? '✓' : '◌'}${this.stats.entityCount ? ' · ' + (chunkObj.entities || '?') + ' 实体' : ''}</p>
          </div>
        </div>
      `;
    }).join('');
  },

  selectGenChunk(index) {
    this.selectedChunk = index;
    const result = this.generationResults[index];
    const chunk = this.chunks[index] || { content: '', type: '未知' }; // 防御：chunk不存在时用默认值
    
    if (result) {
      document.getElementById('subq-list').innerHTML = result.sub_questions.map((q, i) => `
        <div class="glass p3" style="border-radius:var(--r-sm);font-size:var(--fs-sm);color:var(--text-2)">${q}</div>
      `).join('');

      document.getElementById('summary-box').innerHTML = result.summary || '<p class="t3">暂无摘要</p>';

      document.getElementById('gen-stats').innerHTML = `
        <span class="badge">压缩比 ${result.summary ? (chunk.content.length / result.summary.length).toFixed(1) + 'x' : 'N/A'}</span>
        <span class="badge">关键词 ${result.keywords ? result.keywords.length : 0}</span>
      `;
    } else {
      document.getElementById('subq-list').innerHTML = '<p class="t3" style="font-size:var(--fs-sm)">该 Chunk 尚未生成增强内容</p>';
      document.getElementById('summary-box').innerHTML = '<p class="t3">该 Chunk 尚未生成增强内容</p>';
      document.getElementById('gen-stats').innerHTML = '';
    }
    
    this.updateGenChunkList();
  },

  async renderStep4(container) {
    const stepStatus = this.steps[3].status;
    container.innerHTML = `
      <div class="glass p6">
        <div class="row between mb4">
          <div class="row" style="gap:var(--sp-3)">
            <span style="font-size:24px">🚀</span>
            <div>
              <h2 class="h-section">Step 4 · 嵌入向量化 & 导入 Milvus</h2>
              <p class="t3 mt2" style="font-size:var(--fs-xs)">生成向量嵌入并写入向量数据库，完成知识库构建</p>
            </div>
          </div>
          <span class="badge ${stepStatus === 'done' ? 'ok' : stepStatus === 'active' ? 'info' : ''}">${stepStatus === 'done' ? '✓ 已完成' : stepStatus === 'active' ? '⚡ 进行中' : '· 等待中'}</span>
        </div>

        <div class="glass p6 center mb4">
          <div style="font-size:48px">✅</div>
          <h2 class="h-title mt4">导入 Milvus 成功！</h2>
          <p class="t2 mt2" style="font-size:var(--fs-sm)">文档 <b>${this.documentData?.filename || '未知文件'}</b> 已完成全部处理流程，知识库已就绪。</p>
        </div>

        <div class="grid stats mb4">
          <div class="glass p4"><div class="label-caps">Chunk 总数</div><b class="num" style="font-size:var(--fs-2xl)" id="stat-chunk-count">—</b></div>
          <div class="glass p4"><div class="label-caps">向量总数</div><b class="num" style="font-size:var(--fs-2xl)" id="stat-vector-count">—</b></div>
          <div class="glass p4"><div class="label-caps">子问题向量</div><b class="num" style="font-size:var(--fs-2xl)" id="stat-subq-count">—</b></div>
          <div class="glass p4"><div class="label-caps">向量维度</div><b class="num" style="font-size:var(--fs-2xl);color:var(--ok)" id="stat-vec-dim">—</b></div>
        </div>

        <div class="glass p5 mb4">
          <div class="label-caps mb4">处理时间线</div>
          <div class="col" style="gap:var(--sp-3)">
            <div class="row between" style="font-size:var(--fs-sm)"><span>📤 PDF 上传 & 解析</span><span class="badge ok">✓</span><span class="num t3" id="tl-upload" style="font-size:var(--fs-xs)">—</span></div>
            <div class="row between" style="font-size:var(--fs-sm)"><span>✂ 文档切割 (<span id="tl-chunk-count">${this.chunks.length || '?'}</span> Chunks)</span><span class="badge ok">✓</span><span class="num t3" id="tl-split" style="font-size:var(--fs-xs)">—</span></div>
            <div class="row between" style="font-size:var(--fs-sm)"><span>🧠 LLM 生成子问题 & 摘要</span><span class="badge ok">✓</span><span class="num t3" id="tl-generate" style="font-size:var(--fs-xs)">—</span></div>
            <div class="row between" style="font-size:var(--fs-sm)"><span>⚡ 嵌入向量 & 写入 Milvus</span><span class="badge ok">✓</span><span class="num t3" id="tl-embed" style="font-size:var(--fs-xs)">—</span></div>
          </div>
        </div>

        <div class="row between" style="border-top:1px solid var(--glass-border);padding-top:var(--sp-4)" id="step4-total-time">
          <span class="t2" style="font-size:var(--fs-sm)">总耗时 <b class="num" style="color:var(--ok)">计算中...</b> · Collection: <b>rag_knowledge_base</b></span>
          <div class="row" style="gap:var(--sp-2)">
            <button class="btn btn-sm btn-ghost" onclick="PipelinePage.previousStep()">← 返回生成</button>
            <button class="btn btn-sm btn-primary" onclick="window.App.navigate('search')">🔍 去检索验证</button>
            <button class="btn btn-sm" onclick="window.App.navigate('documents')">+ 处理下一个文档</button>
          </div>
        </div>
      </div>
    `;

    await this._ensureChunksLoaded();
    await this.loadImportResults();
  },

  async loadImportResults() {
    try {
      const startTime = Date.now();
      
      // 幂等优化：如果文档已完成，直接用已有数据展示，不重复调用 import 接口
      if (this.documentData?.status === 'completed') {
        this.importResults = {
          chunk_count: this.chunks.length || 0,
          vector_count: this.stats.vectorCount || this.chunks.length || 0,
          sub_question_count: Object.keys(this.generationResults).length || 0,
          vector_dim: this.stats.vectorDim || 1024,
        };
        // 时间线使用已有数据
        this._fillImportStats();
        await this.loadStatsOverview();
        
        // 标记步骤完成
        if (this.steps[3] && this.steps[3].status !== 'done') {
          this.steps[3].status = 'done';
        }
        this.refreshProgress();
        return;
      }
      
      // 文档未完成，执行导入
      this.showLoading('正在嵌入入库...');
      const response = await window.DocumentAPI.importToMilvus(this.currentDocId);
      this.hideLoading();
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
          embed: formatTime(this.timings.import),
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
      }
      this.refreshProgress();
    } catch (error) {
      this.hideLoading();
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
    setEl('tl-embed',    tl.embed    || formatTime(this.timings.import));
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
      totalBar.innerHTML = `<span class="t2" style="font-size:var(--fs-sm)">总耗时 <b class="num" style="color:var(--ok)">${totalTime}</b> · Collection: <b>rag_knowledge_base</b></span>`;
    }
  },

  async loadStatsOverview() {
    try {
      const response = await window.DocumentAPI.getStatsOverview();
      // 检查response是否包含data字段
      const stats = response.data || response;
      
      // 更新全局统计信息（圈 2：壳改为 navigate 时整体重渲染，DOM 可能已切换，逐项判空）
      const setStat = (id, v) => {
        const el = document.getElementById(id);
        if (el) el.textContent = v || 0;
      };
      setStat('global-documents', stats.total_documents);
      setStat('global-chunks', stats.total_chunks);
      setStat('global-sub-questions', stats.total_sub_questions);
      setStat('global-summaries', stats.total_summaries);
      
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
      // 标记当前步骤为已完成（步骤1/2/3 的实际处理由各步骤的 loadXxx 方法负责调用后端接口）
      // nextStep 本身只做导航推进，不重复调接口
      if (this.steps[this.currentStep].status !== 'done') {
        this.steps[this.currentStep].status = 'done';
        window.App.showToast('处理完成', 'success');
      }
      
      // 跳转到下一步
      this.currentStep++;
      
      // 更新目标步骤状态
      if (this.currentStep === 3 && this.documentData?.status === 'completed') {
        // 文档已完成，直接标记完成
        this.steps[this.currentStep].status = 'done';
        window.App.showToast('文档已完成全部处理流程', 'info');
      } else {
        this.steps[this.currentStep].status = 'active';
      }
      this.updateStepsUI();
      await this.renderStepContent();
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
    let loadingElement = document.getElementById('pipeline-loading');
    if (!loadingElement) {
      loadingElement = document.createElement('div');
      loadingElement.id = 'pipeline-loading';
      loadingElement.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:var(--sp-4);background:rgba(0,0,0,0.52);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)';
      document.body.appendChild(loadingElement);
    }
    loadingElement.innerHTML = `
      <div class="glass p6" style="text-align:center">
        <div class="progress indeterminate" style="width:120px;margin:0 auto var(--sp-4)"><i></i></div>
        <div class="t2" style="font-size:var(--fs-sm)">${message}</div>
      </div>
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