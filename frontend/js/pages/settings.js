/**
 * 设置页面 — 查看和修改运行时配置
 *
 * 可写配置分为八组（检索 / 文档切分 / LLM参数 / 会话与记忆 / 文档处理 / 模型与LLM / 系统 / API Keys），
 * 全部支持运行时热改，无需重启；API Key 用密码框输入，留空表示不修改。
 */
const SettingsPage = {
  _configs: null,    // 缓存 GET 返回的完整配置
  _dirty: false,     // 是否有未保存的修改

  async render() {
    const container = document.getElementById('page-container');
    container.innerHTML = `
      <div class="settings-layout">
        <div class="settings-header">
          <h2>系统设置</h2>
          <p class="settings-desc">大部分配置修改后立即生效，无需重启服务；敏感项留空表示不修改</p>
        </div>
        <div class="settings-loading" id="settings-loading">
          <div class="loading-spinner"></div>
          <span>加载配置中...</span>
        </div>
        <div class="settings-content hidden" id="settings-content"></div>
      </div>
    `;
    await this.loadSettings();
  },

  async loadSettings() {
    try {
      const resp = await window.SettingsAPI.get();
      this._configs = resp;
      this._dirty = false;
      this.renderSettings(resp);
    } catch (err) {
      document.getElementById('settings-loading').innerHTML = `
        <span class="text-red">加载配置失败: ${err.message}</span>
      `;
    }
  },

  renderSettings(data) {
    const loading = document.getElementById('settings-loading');
    const content = document.getElementById('settings-content');
    loading.classList.add('hidden');
    content.classList.remove('hidden');

    const groups = data.groups || {};
    const groupOrder = ['retrieval', 'chunking', 'llm', 'session', 'processing', 'model', 'system', 'api_keys'];
    const grouped = {};
    for (const [key, meta] of Object.entries(data.writable || {})) {
      const g = meta.group || 'retrieval';
      (grouped[g] = grouped[g] || []).push([key, meta]);
    }

    let html = '';

    // ── 可写配置区（按分组渲染） ──────────────────────────
    for (const g of groupOrder) {
      const items = grouped[g];
      if (!items || !items.length) continue;
      html += `<div class="settings-section"><div class="settings-section-header">`;
      html += `<h3>${groups[g] || g}</h3>`;
      html += `<span class="settings-badge badge-writable">运行时生效</span>`;
      html += `</div><div class="settings-section-desc">修改后立即生效，无需重启</div>`;
      for (const [key, meta] of items) {
        html += this._renderField(key, meta);
      }
      html += '</div>';
    }

    // ── 只读配置区（重启生效） ────────────────────────────
    const readonlyItems = Object.entries(data.readonly || {});
    if (readonlyItems.length) {
      html += '<div class="settings-section"><div class="settings-section-header">';
      html += '<h3>需重启的配置</h3>';
      html += '<span class="settings-badge badge-readonly">只读</span>';
      html += '</div><div class="settings-section-desc">修改需编辑 .env 文件并重启服务</div>';

      for (const [key, meta] of readonlyItems) {
        html += this._renderField(key, meta);
      }
      html += '</div>';
    }

    // ── 保存按钮 ────────────────────────────────────────────
    html += `
      <div class="settings-actions">
        <button class="btn btn-primary btn-lg" id="btn-save-settings" disabled>
          保存设置
        </button>
        <button class="btn btn-ghost btn-lg" id="btn-reset-settings" disabled>
          重置
        </button>
      </div>
    `;

    content.innerHTML = html;
    this.initEvents();
  },

  _renderField(key, meta) {
    const current = meta.current ?? '';
    const label = meta.label || key;
    const isWritable = meta.writable;
    const restartRequired = meta.restart_required;
    const fieldId = `setting-${key}`;
    let inputHtml = '';

    if (!isWritable) {
      // 只读：纯文本展示
      inputHtml = `
        <div class="settings-field-readonly">
          <code>${this._escape(String(current))}</code>
          ${restartRequired ? '<span class="settings-badge badge-restart">需重启</span>' : '<span class="settings-badge badge-readonly">只读</span>'}
        </div>
      `;
    } else if (meta.sensitive) {
      // 敏感项：密码框，留空不修改
      const state = meta.has_value
        ? '<span class="settings-secret-state has">已设置</span><button type="button" class="btn-link settings-secret-clear" data-clear-key="' + key + '">清除</button>'
        : '<span class="settings-secret-state">未设置</span>';
      inputHtml = `
        <div class="settings-password-group">
          <input type="password" class="settings-input" id="${fieldId}" data-key="${key}"
            placeholder="${meta.has_value ? '留空则不修改' : '请输入密钥'}" autocomplete="new-password" />
          ${state}
        </div>
      `;
    } else if (meta.type === 'enum') {
      const options = (meta.enum || []).map(v =>
        `<option value="${v}" ${String(v) === String(current) ? 'selected' : ''}>${v}</option>`
      ).join('');
      inputHtml = `<select class="settings-input" id="${fieldId}" data-key="${key}">${options}</select>`;
    } else if (meta.type === 'csv') {
      // 文档 03：逗号分隔多值（checkbox 组）；全部未选 = 空串 = 全关
      const selectedSet = new Set(String(current || '').split(',').map(s => s.trim()).filter(Boolean));
      const boxes = (meta.enum || []).map(v => `
        <label class="settings-csv-item">
          <input type="checkbox" class="settings-csv-box" data-key="${key}" value="${v}"
            ${selectedSet.has(String(v)) ? 'checked' : ''}> ${v}
        </label>
      `).join('');
      // 隐藏 input 承载聚合值（走统一收集逻辑），checkbox 组仅做 UI
      inputHtml = `
        <div class="settings-csv-group" id="${fieldId}-group">${boxes}</div>
        <input type="hidden" class="settings-input" id="${fieldId}" data-key="${key}" value="${this._escape(String(current || ''))}">
      `;
    } else if (meta.type === 'float') {
      inputHtml = `
        <div class="settings-range-group">
          <input type="range" class="settings-range" id="${fieldId}-range"
            min="${meta.min}" max="${meta.max}" step="0.05" value="${current}"
            data-key="${key}" data-linked="${fieldId}">
          <input type="number" class="settings-number" id="${fieldId}"
            min="${meta.min}" max="${meta.max}" step="0.05" value="${current}"
            data-key="${key}" data-linked="${fieldId}-range">
        </div>
      `;
    } else if (meta.type === 'int') {
      inputHtml = `
        <input type="number" class="settings-input" id="${fieldId}"
          min="${meta.min}" max="${meta.max}" step="1" value="${current}"
          data-key="${key}">
      `;
    } else {
      inputHtml = `
        <input type="text" class="settings-input" id="${fieldId}" value="${this._escape(String(current))}"
          data-key="${key}">
      `;
    }

    return `
      <div class="settings-field" data-key="${key}">
        <div class="settings-field-label">
          <span class="settings-field-name">${label}</span>
          <span class="settings-field-key">${key}</span>
          ${meta.description ? `<span class="settings-field-desc">${meta.description}</span>` : ''}
        </div>
        <div class="settings-field-control">
          ${inputHtml}
        </div>
      </div>
    `;
  },

  initEvents() {
    document.querySelectorAll('.settings-input, .settings-range, .settings-number').forEach(el => {
      el.addEventListener('input', () => this._markDirty());
      el.addEventListener('change', () => this._markDirty());
    });

    // range 和 number 双向同步
    document.querySelectorAll('.settings-range').forEach(range => {
      range.addEventListener('input', () => {
        const linked = document.getElementById(range.dataset.linked);
        if (linked) linked.value = range.value;
      });
    });
    document.querySelectorAll('.settings-number[data-linked]').forEach(num => {
      num.addEventListener('change', () => {
        const linked = document.getElementById(num.dataset.linked);
        if (linked) linked.value = num.value;
      });
    });

    // csv 多选组（文档 03）：勾选变化 → 聚合同步到承载 hidden input（去重保序）
    document.querySelectorAll('.settings-csv-box').forEach(box => {
      box.addEventListener('change', () => {
        const key = box.dataset.key;
        const checked = [...document.querySelectorAll(`.settings-csv-box[data-key="${key}"]:checked`)]
          .map(b => b.value);
        const carrier = document.getElementById(`setting-${key}`);
        if (carrier) carrier.value = checked.join(',');
      });
    });

    // 清除敏感项（提交 null 表示恢复 .env/默认值）
    document.querySelectorAll('.settings-secret-clear').forEach(btn => {
      btn.addEventListener('click', () => {
        btn.dataset.cleared = '1';
        btn.textContent = '待清除';
        this._markDirty();
      });
    });

    document.getElementById('btn-save-settings').addEventListener('click', () => this.saveSettings());

    document.getElementById('btn-reset-settings').addEventListener('click', () => {
      this.renderSettings(this._configs);
      this._dirty = false;
      document.getElementById('btn-save-settings').disabled = true;
      document.getElementById('btn-reset-settings').disabled = true;
    });
  },

  _markDirty() {
    this._dirty = true;
    document.getElementById('btn-save-settings').disabled = false;
    document.getElementById('btn-reset-settings').disabled = false;
  },

  async saveSettings() {
    const btn = document.getElementById('btn-save-settings');
    btn.disabled = true;
    btn.textContent = '保存中...';

    // 收集被标记清除的敏感项
    const clearKeys = new Set();
    document.querySelectorAll('.settings-secret-clear').forEach(btn => {
      if (btn.dataset.cleared) clearKeys.add(btn.dataset.clearKey);
    });

    const configs = [];
    document.querySelectorAll('.settings-input, .settings-number').forEach(el => {
      const key = el.dataset.key;
      if (!key) return;
      if (el.type === 'password') {
        if (el.value !== '') {
          // 输入了新值 → 以新值为准，取消清除标记
          clearKeys.delete(key);
          configs.push({ key, value: el.value });
        } else if (clearKeys.has(key)) {
          configs.push({ key, value: null });
        }
        // 留空且未标记清除 = 不修改
        return;
      }
      configs.push({ key, value: el.value });
    });
    // range 通过 number 联动已包含，避免重复
    const seen = new Set();
    const deduped = configs.filter(c => {
      if (seen.has(c.key)) return false;
      seen.add(c.key);
      return true;
    });

    if (!deduped.length) {
      window.App.showToast('没有需要保存的修改', 'info');
      btn.disabled = false;
      btn.textContent = '保存设置';
      return;
    }

    try {
      const resp = await window.SettingsAPI.update(deduped);
      if (resp.status === 'ok' || resp.status === 'partial_error') {
        const okCount = Object.keys(resp.updated).length;
        const errCount = Object.keys(resp.errors || {}).length;
        const msg = errCount > 0
          ? `已更新 ${okCount} 项，${errCount} 项失败（已回滚）`
          : `已保存 ${okCount} 项设置`;
        window.App.showToast(msg, errCount > 0 ? 'warning' : 'success');
        await this.loadSettings();
      }
    } catch (err) {
      window.App.showToast(`保存失败: ${err.message}`, 'error');
      btn.disabled = false;
      btn.textContent = '保存设置';
    }
  },

  _escape(str) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  },
};

// 挂载到 window，供 app.js 的 navigate('settings') 检测并调用
// （其他页面均在文件末尾显式导出，此处缺失会导致设置页空白）
window.SettingsPage = SettingsPage;
