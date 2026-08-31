/**
 * 文档管理页面 — 圈 3 按线框 02 重构
 * 上传统一拖拽 dropzone + 处理中队列卡（轮询 /api/process/{id}/progress）+ 列表 icon-btn
 */
const DocumentsPage = {
  currentKbId: null,
  selectedFiles: [],
  documents: [],
  kbs: [],
  _page: 1,
  _pageSize: 20,
  _total: 0,
  // 处理中文件：{ file_id, filename } → 轮询进度渲染队列卡
  progressFiles: [],
  _progressTimer: null,
  _progressStart: {}, // file_id -> 首次进入队列的时间戳（兜底耗时）

  async render(params = {}) {
    this.currentKbId = params.kb_id || null;
    this.selectedFiles = [];
    this.documents = [];
    this.progressFiles = [];

    const container = document.getElementById('page-container');
    container.innerHTML = `
      <div class="row between mb6">
        <div>
          <h1 class="h-title">文档管理</h1>
          <p class="t2 mt2" style="font-size:var(--fs-sm)">上传和管理您的文档 · 上传后自动进入处理流水线</p>
        </div>
        <div class="row" style="gap:var(--sp-2)">
          <select id="doc-kb-filter" class="select" style="width:200px;height:34px">
            <option value="">全部知识库</option>
          </select>
          <button class="icon-btn" id="refresh-docs-btn" title="刷新">↻</button>
        </div>
      </div>

      <!-- 上传区：拖放 + 点击（线框 02 dropzone） -->
      <div class="glass" id="upload-zone" style="border:1.5px dashed var(--glass-border-strong);border-radius:var(--r-lg);padding:var(--sp-8);text-align:center;color:var(--text-2);cursor:pointer;transition:all var(--dur-2) var(--ease-out)">
        <input type="file" id="file-input" accept=".pdf,.md,.markdown" multiple style="display:none" />
        <div style="font-size:30px">⇪</div>
        <p style="font-weight:600;color:var(--text-1)">拖放文件到此处，或点击选择</p>
        <p class="t3 mt2" style="font-size:var(--fs-xs)">支持 PDF / Markdown · 单个文件不超过 50MB</p>
      </div>

      <!-- 处理中队列卡（真实进度，3s 轮询 GET /api/process/{id}/progress） -->
      <div class="glass p5 mb4" id="processing-card" style="display:none">
        <div class="row between mb4">
          <span class="h-section" style="font-size:var(--fs-md)">处理中（<span id="processing-count">0</span>）</span>
          <span class="t3 mono" style="font-size:var(--fs-xs)">progress API · 3s 轮询</span>
        </div>
        <div id="processing-list" class="col" style="gap:var(--sp-4)"></div>
      </div>

      <!-- 文档列表（线框 02 表格结构） -->
      <div class="glass">
        <div class="row between p5" style="padding-bottom:var(--sp-3)">
          <h2 class="h-section" style="font-size:var(--fs-md)">全部文档</h2>
          <input type="search" class="input" id="doc-search" style="width:220px;height:32px" placeholder="搜索文件名…" />
        </div>
        <table class="table" id="doc-table">
          <thead>
            <tr><th>文件</th><th>知识库</th><th>状态</th><th class="num">大小</th><th>上传时间</th><th style="text-align:right">操作</th></tr>
          </thead>
          <tbody id="doc-table-body">
            <tr><td colspan="5"><div class="skeleton" style="height:40px"></div></td></tr>
          </tbody>
        </table>
      </div>
      <div class="row between p4" id="doc-pagination"></div>
    `;

    this.initEvents();
    await Promise.all([this.loadKbOptions(), this.loadDocuments()]);
    this._startProgressPolling();
  },

  initEvents() {
    const uploadZone = document.getElementById('upload-zone');
    const fileInput = document.getElementById('file-input');

    uploadZone.addEventListener('click', () => fileInput.click());
    uploadZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      uploadZone.style.borderColor = 'var(--accent)';
      uploadZone.style.background = 'var(--accent-soft)';
      uploadZone.style.color = 'var(--text-1)';
    });
    uploadZone.addEventListener('dragleave', () => {
      uploadZone.style.borderColor = '';
      uploadZone.style.background = '';
      uploadZone.style.color = '';
    });
    uploadZone.addEventListener('drop', (e) => {
      e.preventDefault();
      uploadZone.style.borderColor = '';
      uploadZone.style.background = '';
      uploadZone.style.color = '';
      if (e.dataTransfer.files.length) this.handleFiles(e.dataTransfer.files);
    });
    fileInput.addEventListener('change', (e) => {
      if (e.target.files.length) this.handleFiles(e.target.files);
      fileInput.value = '';
    });

    document.getElementById('refresh-docs-btn').addEventListener('click', () => this.loadDocuments());
    document.getElementById('doc-search').addEventListener('input', () => this.filterDocuments());
    document.getElementById('doc-kb-filter').addEventListener('change', (e) => {
      this.currentKbId = e.target.value || null;
      this._page = 1;
      this.loadDocuments();
    });
  },

  /** 页面卸载钩子（app.js navigate 时调用，若存在） */
  destroy() {
    this._stopProgressPolling();
  },

  handleFiles(files) {
    const valid = Array.from(files).filter(f =>
      f.type === 'application/pdf' || /\.(md|markdown)$/i.test(f.name || ''));
    if (!valid.length) {
      window.App.showToast('仅支持 PDF / Markdown 文件', 'warning');
      return;
    }
    // 前端大小校验（与提示文案一致，避免上传超限后才被后端拒绝）
    const MAX_SIZE = 50 * 1024 * 1024;
    const tooLarge = valid.filter(f => f.size > MAX_SIZE);
    if (tooLarge.length) {
      window.App.showToast(`「${tooLarge.map(f => f.name).join('、')}」超过 50MB 上限，已跳过`, 'warning');
    }
    const accepted = valid.filter(f => f.size <= MAX_SIZE);
    if (!accepted.length) return;
    this.uploadFiles(accepted);
  },

  /** 上传/解析阶段 loading：dropzone 显示 spinner + 文件名，用户能感知"没卡住" */
  _setUploading(names) {
    const zone = document.getElementById('upload-zone');
    if (!zone) return;
    zone.innerHTML = `
      <div class="spinner" style="width:28px;height:28px;border:3px solid var(--glass-border-strong);border-top-color:var(--accent);border-radius:50%;margin:0 auto;animation:spin .8s linear infinite"></div>
      <p style="font-weight:600;color:var(--text-1);margin-top:12px">上传中 · MinerU 解析中…</p>
      <p class="t3 mt2" style="font-size:var(--fs-xs);color:var(--text-2)">${names}</p>
      <p class="t3 mt2" style="font-size:var(--fs-xs)">解析较慢，请耐心等待，不要关闭页面</p>
    `;
    zone.style.pointerEvents = 'none';
    zone.style.opacity = '0.7';
  },

  _resetUploadZone() {
    const zone = document.getElementById('upload-zone');
    if (!zone) return;
    zone.innerHTML = `
      <div style="font-size:30px">⇪</div>
      <p style="font-weight:600;color:var(--text-1)">拖放文件到此处，或点击选择</p>
      <p class="t3 mt2" style="font-size:var(--fs-xs)">支持 PDF / Markdown · 单个文件不超过 50MB</p>
    `;
    zone.style.pointerEvents = '';
    zone.style.opacity = '';
  },

  async uploadFiles(files) {
    // KB 目标：页面上有 KB 下拉时以选中值为准
    const kbSel = document.getElementById('doc-kb-filter');
    if (kbSel && kbSel.value) this.currentKbId = kbSel.value;
    this._setUploading(files.map(f => f.name).join('、'));
    for (const file of files) {
      try {
        const resp = await window.DocumentAPI.upload(file, this.currentKbId);
        window.App.showToast(`文件 ${file.name} 上传成功，进入处理队列`, 'success');
        const fid = resp.file_id || resp.fileId;
        if (fid) {
          this.progressFiles.push({ file_id: String(fid), filename: file.name });
          this._progressStart[String(fid)] = Date.now();
        }
      } catch (error) { /* request() 已自动 toast */ }
    }
    this._resetUploadZone();
    this._renderProcessingList();
    this._startProgressPolling();
    await this.loadDocuments();
  },

  // ============ 处理中队列卡（真实进度轮询） ============

  _startProgressPolling() {
    this._stopProgressPolling();
    if (!this.progressFiles.length) return;
    this._progressTimer = setInterval(() => this._pollProgress(), 3000);
    this._pollProgress();
  },

  _stopProgressPolling() {
    if (this._progressTimer) { clearInterval(this._progressTimer); this._progressTimer = null; }
  },

  async _pollProgress() {
    const card = document.getElementById('processing-card');
    if (!card) { this._stopProgressPolling(); return; }

    const finished = [];
    const failed = [];
    for (const pf of this.progressFiles) {
      try {
        const p = await window.DocumentAPI.getProgress(pf.file_id);
        pf.progress = p;
        if (p.stage === 'done') finished.push(pf);
        else if (p.stage === 'failed') failed.push(pf);
      } catch { /* 单文件失败静默，下轮再试 */ }
    }
    if (finished.length) {
      this.progressFiles = this.progressFiles.filter(pf => !finished.includes(pf));
      window.App.showToast(`${finished.map(f => f.filename).join('、')} 处理完成`, 'success');
      await this.loadDocuments();
    }
    // 处理失败：移出队列并明确告知用户（否则会无限轮询等不到 done）
    if (failed.length) {
      this.progressFiles = this.progressFiles.filter(pf => !failed.includes(pf));
      const reason = failed.map(f => f.progress?.last_error?.message).find(Boolean);
      window.App.showToast(
        `${failed.map(f => f.filename).join('、')} 处理失败${reason ? '：' + reason : '，可到流水线页查看详情并重试'}`,
        'error');
      await this.loadDocuments();
    }
    this._renderProcessingList();
    if (!this.progressFiles.length) this._stopProgressPolling();
  },

  _fmtMs(ms) {
    if (ms == null) return '';
    return ms < 1000 ? Math.round(ms) + 'ms' : (ms / 1000).toFixed(1) + 's';
  },

  /** 预计剩余：timing_ms 历史耗时 × 未完成比例外推；无历史则按已运行速度估计 */
  _etaText(p) {
    const sp = p.stage_progress || {};
    if (!sp.total || sp.total <= 0) return '';
    const ratio = Math.min(sp.done / sp.total, 1);
    const hist = p.timing_ms || {};
    if (p.stage === 'generating' && hist.generate_time && ratio > 0.05) {
      const rem = hist.generate_time * (1 - ratio) / ratio / 1000;
      return `预计剩余 ~${Math.max(rem, 1).toFixed(0)}s`;
    }
    if (p.stage === 'importing' && hist.import_time) {
      return `预计剩余 ~${(hist.import_time / 1000).toFixed(0)}s`;
    }
    const start = this._progressStart[p.file_id];
    if (start && ratio > 0.1) {
      const elapsed = (Date.now() - start) / 1000;
      return `预计剩余 ~${Math.max(elapsed * (1 - ratio) / ratio, 1).toFixed(0)}s`;
    }
    return '';
  },

  _renderProcessingList() {
    const card = document.getElementById('processing-card');
    const list = document.getElementById('processing-list');
    const count = document.getElementById('processing-count');
    if (!card || !list) return;
    card.style.display = this.progressFiles.length ? '' : 'none';
    if (count) count.textContent = this.progressFiles.length;

    list.innerHTML = this.progressFiles.map(pf => {
      const p = pf.progress;
      if (!p) {
        return `<div class="row" style="gap:var(--sp-3)"><span style="font-size:22px">📄</span>
          <div class="grow"><div class="row between"><b>${this._esc(pf.filename)}</b><span class="t3 mono" style="font-size:var(--fs-xs)">等待进度…</span></div>
          <div class="progress mt2"><i style="width:0%"></i></div></div></div>`;
      }
      const sp = p.stage_progress || { done: 0, total: 0 };
      const pct = sp.total ? Math.round(sp.done / sp.total * 100) : (p.stage === 'done' ? 100 : 0);
      const stageLabel = {
        awaiting_split: '待切割', generating: '生成增强', awaiting_import: '待入库',
        importing: '嵌入入库', done: '完成', failed: '失败',
      }[p.stage] || p.stage;
      const eta = this._etaText(p);
      const timing = p.timing_ms || {};
      const badges = [];
      if (timing.split_time != null) badges.push(`<span class="badge ok">切割 ✓ ${this._fmtMs(timing.split_time)}</span>`);
      if (p.stage === 'generating') badges.push(`<span class="badge warn"><i class="dot"></i>生成中</span>`);
      else if (timing.generate_time != null) badges.push(`<span class="badge ok">生成 ✓ ${this._fmtMs(timing.generate_time)}</span>`);
      if (p.stage === 'importing') badges.push(`<span class="badge warn"><i class="dot"></i>导入中</span>`);
      else if (p.stage === 'done') badges.push(`<span class="badge ok">导入 ✓ ${this._fmtMs(timing.import_time)}</span>`);
      if (p.stage === 'awaiting_import') badges.push(`<span class="badge">导入 · 待执行</span>`);
      if (p.stage === 'awaiting_split') badges.push(`<span class="badge">切割 · 待执行</span>`);

      return `<div class="row" style="gap:var(--sp-3)">
        <span style="font-size:22px">📄</span>
        <div class="grow">
          <div class="row between"><b>${this._esc(pf.filename)}</b>
            <span class="t2 num" style="font-size:var(--fs-xs)">${stageLabel} ${sp.done}/${sp.total}${eta ? ' · ' + eta : ''}</span></div>
          <div class="progress mt2"><i style="width:${pct}%"></i></div>
          <div class="row wrap mt2" style="gap:6px">${badges.join('')}</div>
        </div>
      </div>`;
    }).join('');
  },

  // ============ 文档列表 ============

  async loadKbOptions() {
    try {
      const resp = await window.KnowledgeBaseAPI.list();
      this.kbs = resp.knowledge_bases || [];
      const sel = document.getElementById('doc-kb-filter');
      if (sel) {
        this.kbs.forEach(kb => {
          const opt = document.createElement('option');
          opt.value = kb.id; opt.textContent = kb.kb_name;
          sel.appendChild(opt);
        });
        if (this.currentKbId) sel.value = String(this.currentKbId);
      }
    } catch { /* KB 下拉失败不阻断文档列表 */ }
  },

  async loadDocuments() {
    const tableBody = document.getElementById('doc-table-body');
    if (!tableBody) return;
    try {
      const response = await window.DocumentAPI.list(this.currentKbId, this._page, this._pageSize);
      this.documents = response.documents || [];
      this._total = response.total || 0;

      if (this.documents.length === 0 && this._total === 0) {
        tableBody.innerHTML = `<tr><td colspan="6">
          <div class="state"><div class="glyph">📄</div>
          <div class="title">暂无文档</div>
          <div class="desc">拖放文件到上方上传区添加文档</div></div></td></tr>`;
        this._renderPagination();
        return;
      }

      tableBody.innerHTML = this.documents.map(doc => this._renderRow(doc)).join('');
      this._bindRowEvents();
      this._renderPagination();

      // 重进页面时，把仍在处理中的文档重新纳入进度队列（断点可见性）
      const known = new Set(this.progressFiles.map(pf => String(pf.file_id)));
      this.documents.forEach(doc => {
        const fid = String(doc.file_id);
        if (!known.has(fid) && (doc.status === 'chunk_done' || doc.status === 'importing' || doc.status === 'processing')) {
          this.progressFiles.push({ file_id: fid, filename: doc.filename });
          this._progressStart[fid] = Date.now();
        }
      });
      if (this.progressFiles.length) { this._renderProcessingList(); this._startProgressPolling(); }
    } catch (error) {
      tableBody.innerHTML = `<tr><td colspan="6">
        <div class="state"><div class="glyph" style="color:var(--danger)">✕</div>
        <div class="title">加载失败</div>
        <div class="desc">${this._esc(error.message || '无法加载文档列表')}</div>
        <button class="btn btn-sm mt4" id="doc-retry-load">重新加载</button></div></td></tr>`;
      const retry = document.getElementById('doc-retry-load');
      if (retry) retry.addEventListener('click', () => this.loadDocuments());
    }
  },

  _statusMeta(status) {
    const map = {
      uploaded:    { text: '已上传',  cls: '' },
      chunk_done:  { text: '生成中',  cls: 'warn' },
      generated:   { text: '待入库',  cls: 'info' },
      importing:   { text: '入库中',  cls: 'warn' },
      completed:   { text: '已完成',  cls: 'ok' },
      failed:      { text: '失败',    cls: 'danger' },
      processing:  { text: '处理中',  cls: 'warn' },
    };
    return map[status] || { text: status, cls: '' };
  },

  _renderRow(doc) {
    const meta = this._statusMeta(doc.status);
    const kb = this.kbs.find(k => String(k.id) === String(doc.knowledge_base_id || doc.kb_id));
    const kbName = kb ? kb.kb_name : (doc.kb_name || '—');
    const isFailed = doc.status === 'failed';
    const isFresh = doc.status === 'uploaded' || doc.status === 'processing';
    const actionBtn = isFailed
      ? `<button class="btn btn-sm btn-primary act-pipeline" data-file-id="${doc.file_id}">重试</button>`
      : isFresh
        ? `<button class="btn btn-sm btn-primary act-pipeline" data-file-id="${doc.file_id}">开始处理</button>`
        : `<button class="btn btn-sm act-pipeline" data-file-id="${doc.file_id}">流水线</button>`;

    const size = doc.file_size != null ? (doc.file_size > 1048576 ? (doc.file_size / 1048576).toFixed(1) + ' MB' : (doc.file_size / 1024).toFixed(0) + ' KB') : '—';
    return `<tr data-file-id="${doc.file_id}" data-name="${this._esc(doc.filename)}" data-status="${doc.status}">
      <td><b style="color:var(--text-1)">${this._esc(doc.filename)}</b></td>
      <td>${this._esc(kbName)}</td>
      <td><span class="badge ${meta.cls}">${meta.text}</span></td>
      <td class="num">${size}</td>
      <td>${new Date(doc.created_at).toLocaleDateString()}</td>
      <td style="text-align:right;white-space:nowrap">
        ${actionBtn}
        <button class="icon-btn act-delete" data-file-id="${doc.file_id}" title="删除" aria-label="删除">🗑</button>
      </td>
    </tr>`;
  },

  _bindRowEvents() {
    document.querySelectorAll('#doc-table-body .act-pipeline').forEach(btn => {
      btn.addEventListener('click', () => {
        this._stopProgressPolling();
        window.App.navigate('pipeline', { doc_id: btn.dataset.fileId });
      });
    });
    document.querySelectorAll('#doc-table-body .act-delete').forEach(btn => {
      btn.addEventListener('click', () => this.deleteDocument(btn.dataset.fileId));
    });
  },

  async deleteDocument(docId) {
    const ok = await window.UI.confirm({
      title: '删除文档',
      message: '确定要删除这个文档吗？该操作不可恢复。',
      okText: '删除',
      danger: true
    });
    if (!ok) return;
    // 行内按钮 loading 态（确认弹窗关闭后表格按钮仍在）
    const btn = document.querySelector(`#doc-table-body .act-delete[data-file-id="${docId}"]`);
    const done = window.btnLoading(btn, '删除中…');
    try {
      await window.DocumentAPI.delete(docId);
      window.App.showToast('文档删除成功', 'success');
      await this.loadDocuments();
    } catch (error) { /* request() 已自动 toast */ }
    finally { done(); }
  },

  filterDocuments() {
    const term = (document.getElementById('doc-search')?.value || '').toLowerCase();
    let visible = 0;
    document.querySelectorAll('#doc-table-body tr[data-file-id]').forEach(row => {
      const match = !term || (row.dataset.name || '').toLowerCase().includes(term);
      row.style.display = match ? '' : 'none';
      if (match) visible++;
    });
    // 无匹配时补一条提示行（有数据行的场景）
    const body = document.getElementById('doc-table-body');
    let noMatch = document.getElementById('doc-no-match');
    if (visible === 0 && body.querySelector('tr[data-file-id]')) {
      if (!noMatch) {
        noMatch = document.createElement('tr');
        noMatch.id = 'doc-no-match';
        noMatch.innerHTML = `<td colspan="5"><div class="state">
          <div class="glyph">◎</div><div class="title">没有找到匹配的文档</div>
          <div class="desc">尝试调整搜索关键词</div></div></td>`;
        body.appendChild(noMatch);
      }
    } else if (noMatch) noMatch.remove();
  },

  _renderPagination() {
    const el = document.getElementById('doc-pagination');
    if (!el) return;
    const pages = Math.max(1, Math.ceil(this._total / this._pageSize));
    el.innerHTML = `
      <span class="t3">共 ${this._total} 条</span>
      <span class="num t3">${this._page} / ${pages}</span>
      <button class="btn btn-sm" id="doc-pg-prev" ${this._page <= 1 ? 'disabled' : ''}>← 上一页</button>
      <button class="btn btn-sm" id="doc-pg-next" ${this._page >= pages ? 'disabled' : ''}>下一页 →</button>
    `;
    const prev = document.getElementById('doc-pg-prev');
    const next = document.getElementById('doc-pg-next');
    if (prev && !prev.disabled) prev.addEventListener('click', () => { this._page--; this.loadDocuments(); });
    if (next && !next.disabled) next.addEventListener('click', () => { this._page++; this.loadDocuments(); });
  },

  _esc(str) {
    if (str == null) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  },
};

window.DocumentsPage = DocumentsPage;
