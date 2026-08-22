/**
 * 设置页面 — 查看和修改运行时配置
 *
 * 可写配置分为八组（检索 / 文档切分 / LLM参数 / 会话与记忆 / 文档处理 / 模型与LLM / 系统 / API Keys），
 * 全部支持运行时热改，无需重启；API Key 用密码框输入，留空表示不修改。
 *
 * 05a 批次 2：
 * - dirty-only 提交：只提交真正修改过的 key（与加载值比对，敏感项留空=不提交）
 * - 分组保存：每组头部「保存本组」按钮（带 dirty 数徽标），底部保留「全部保存」
 * - partial_error 按组内联标红
 */
const SettingsPage = {
  _configs: null,          // 缓存 GET 返回的完整配置
  _dirtyKeys: new Set(),   // 有修改的 key 集合
  _groupKeys: {},          // groupKey -> [configKey]（保存时过滤用）

  async render() {
    const container = document.getElementById('page-container');
    container.innerHTML = `
      <div class="settings-layout settings-layout-v2">
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
      this._dirtyKeys = new Set();
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
    this._groupKeys = {};
    this._groupTitles = groups;
    for (const [key, meta] of Object.entries(data.writable || {})) {
      const g = meta.group || 'retrieval';
      (grouped[g] = grouped[g] || []).push([key, meta]);
      (this._groupKeys[g] = this._groupKeys[g] || []).push(key);
    }
    const presentGroups = groupOrder.filter(g => grouped[g] && grouped[g].length);
    this._presentGroups = presentGroups;
    this._activeGroup = presentGroups[0] || null;

    let html = `<div class="settings-nav glass-card" id="settings-nav">
      <div class="settings-nav-title label-caps">配置组</div>
      ${presentGroups.map(g => `
        <div class="settings-grp ${g === this._activeGroup ? 'on' : ''}" data-nav-group="${g}">
          <span>${groups[g] || g}</span><i class="dirty-dot" data-nav-dirty="${g}"></i>
        </div>`).join('')}
    </div>`;

    html += '<div class="settings-panels">';

    // ── 可写配置区（按分组渲染，每组带保存按钮） ───────────
    for (const g of presentGroups) {
      const items = grouped[g];
      html += `<div class="settings-section glass-card" data-group="${g}" ${g !== this._activeGroup ? 'hidden' : ''}><div class="settings-section-header">`;
      html += `<h3>${groups[g] || g}</h3>`;
      html += `<span class="badge badge-green">运行时生效</span>`;
      html += `<button class="btn btn-sm btn-primary settings-group-save" data-group="${g}" disabled>保存本组</button>`;
      html += `</div><div class="settings-section-desc">修改后立即生效，无需重启</div>`;
      html += `<div class="settings-group-errors" data-group-errors="${g}"></div>`;
      for (const [key, meta] of items) {
        html += this._renderField(key, meta);
      }
      html += '</div>';
    }

    // ── 只读配置区（重启生效） ────────────────────────────
    const readonlyItems = Object.entries(data.readonly || {});
    if (readonlyItems.length) {
      html += '<div class="settings-section glass-card settings-readonly" data-group="__readonly__"><div class="settings-section-header">';
      html += '<h3>只读配置（需重启）</h3>';
      html += '<span class="badge badge-gray">编辑 .env 后重启服务</span>';
      html += '</div>';
      for (const [key, meta] of readonlyItems) {
        html += this._renderField(key, meta);
      }
      html += '</div>';
    }

    // ── 底部操作 ────────────────────────────────────────────
    html += `
      <div class="settings-actions">
        <button class="btn btn-primary btn-lg" id="btn-save-settings" disabled>
          保存设置
        </button>
        <button class="btn btn-ghost btn-lg" id="btn-reset-settings" disabled>
          重置
        </button>
      </div>
    </div>`;

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
      <div class="settings-field" data-key="${key}" data-original="${this._escape(String(current ?? ''))}">
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
      el.addEventListener('input', () => this._checkDirty(el));
      el.addEventListener('change', () => this._checkDirty(el));
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
        this._checkDirty(carrier);
      });
    });

    // 清除敏感项（提交 null 表示恢复 .env/默认值）
    document.querySelectorAll('.settings-secret-clear').forEach(btn => {
      btn.addEventListener('click', () => {
        btn.dataset.cleared = '1';
        btn.textContent = '待清除';
        this._addDirty(btn.dataset.clearKey);
      });
    });

    // 分组导航切换（圈 4：线框 07 左侧配置组导航，一次只显示一个组面板）
    document.querySelectorAll('.settings-grp').forEach(item => {
      item.addEventListener('click', () => {
        const g = item.dataset.navGroup;
        this._activeGroup = g;
        document.querySelectorAll('.settings-grp').forEach(i =>
          i.classList.toggle('on', i.dataset.navGroup === g));
        document.querySelectorAll('.settings-section[data-group]').forEach(sec => {
          sec.hidden = sec.dataset.group !== g;
        });
      });
    });

    // 分组保存 + 全部保存 + 重置
    document.querySelectorAll('.settings-group-save').forEach(btn => {
      btn.addEventListener('click', () => this.saveSettings(btn.dataset.group));
    });
    document.getElementById('btn-save-settings').addEventListener('click', () => this.saveSettings());

    document.getElementById('btn-reset-settings').addEventListener('click', () => {
      this.renderSettings(this._configs);
    });
  },

  _fieldGroup(configKey) {
    for (const [g, keys] of Object.entries(this._groupKeys)) {
      if (keys.includes(configKey)) return g;
    }
    return null;
  },

  _checkDirty(el) {
    // 与初始值比对：回到原值时撤销 dirty（避免提交无意义修改）
    const key = el.dataset.key;
    if (!key) return;
    if (el.type === 'password') {
      if (el.value !== '') this._addDirty(key); else this._removeDirty(key);
      return;
    }
    const field = el.closest('.settings-field');
    const original = field ? field.dataset.original : undefined;
    if (String(el.value) === String(original ?? '')) this._removeDirty(key);
    else this._addDirty(key);
  },

  _addDirty(key) {
    this._dirtyKeys.add(key);
    this._refreshDirtyUI();
  },

  _removeDirty(key) {
    this._dirtyKeys.delete(key);
    this._refreshDirtyUI();
  },

  _groupDirtyCount(groupKey) {
    const keys = this._groupKeys[groupKey] || [];
    return keys.filter(k => this._dirtyKeys.has(k)).length;
  },

  _refreshDirtyUI() {
    // 各组按钮：显示本组 dirty 数，无改动禁用
    document.querySelectorAll('.settings-group-save').forEach(btn => {
      const n = this._groupDirtyCount(btn.dataset.group);
      btn.textContent = n > 0 ? `保存本组 (${n})` : '保存本组';
      btn.disabled = n === 0;
    });
    // 导航 dirty 点（圈 4：线框 07 dirty-dot）
    document.querySelectorAll('[data-nav-dirty]').forEach(dot => {
      const dirty = this._groupDirtyCount(dot.dataset.navDirty) > 0;
      dot.style.display = dirty ? 'inline-block' : 'none';
    });
    // 底部按钮
    const hasDirty = this._dirtyKeys.size > 0;
    const saveBtn = document.getElementById('btn-save-settings');
    const resetBtn = document.getElementById('btn-reset-settings');
    if (saveBtn) {
      saveBtn.disabled = !hasDirty;
      saveBtn.textContent = hasDirty ? `保存设置 (${this._dirtyKeys.size})` : '保存设置（无改动）';
    }
    if (resetBtn) resetBtn.disabled = !hasDirty;
    // 字段高亮
    document.querySelectorAll('.settings-field[data-key]').forEach(f => {
      f.classList.toggle('field-dirty', this._dirtyKeys.has(f.dataset.key));
    });
  },

  /** 收集 dirty 项（groupKey 非空时按组过滤）。敏感项规则不变：留空=不提交，标记清除=提交 null。 */
  collectDirtyConfigs(groupKey = null) {
    const clearKeys = new Set();
    document.querySelectorAll('.settings-secret-clear').forEach(btn => {
      if (btn.dataset.cleared) clearKeys.add(btn.dataset.clearKey);
    });

    const configs = [];
    document.querySelectorAll('.settings-input, .settings-number').forEach(el => {
      const key = el.dataset.key;
      if (!key || !this._dirtyKeys.has(key)) return;          // dirty-only
      if (groupKey && this._fieldGroup(key) !== groupKey) return; // 组过滤
      if (el.type === 'password') {
        if (el.value !== '') {
          clearKeys.delete(key);
          configs.push({ key, value: el.value });
        } else if (clearKeys.has(key)) {
          configs.push({ key, value: null });
        }
        return;
      }
      configs.push({ key, value: el.value });
    });
    // range 通过 number 联动已包含，去重
    const seen = new Set();
    return configs.filter(c => {
      if (seen.has(c.key)) return false;
      seen.add(c.key);
      return true;
    });
  },

  _showGroupErrors(errors) {
    // partial_error：按 key → 组映射，组内联标红（比 toast 更可定位）
    document.querySelectorAll('.settings-group-errors').forEach(el => (el.innerHTML = ''));
    document.querySelectorAll('.settings-field').forEach(f => f.classList.remove('field-error'));
    for (const [key, msg] of Object.entries(errors || {})) {
      const field = document.querySelector(`.settings-field[data-key="${key}"]`);
      if (field) field.classList.add('field-error');
      const g = this._fieldGroup(key);
      const box = g && document.querySelector(`[data-group-errors="${g}"]`);
      if (box) {
        box.innerHTML += `<div class="settings-error-inline text-red">${key}: ${this._escape(String(msg))}</div>`;
      }
    }
  },

  async saveSettings(groupKey = null) {
    const btn = groupKey
      ? document.querySelector(`.settings-group-save[data-group="${groupKey}"]`)
      : document.getElementById('btn-save-settings');
    const deduped = this.collectDirtyConfigs(groupKey);

    if (!deduped.length) {
      window.App.showToast('没有需要保存的修改', 'info');
      return;
    }

    if (btn) { btn.disabled = true; btn.textContent = '保存中...'; }

    try {
      const resp = await window.SettingsAPI.update(deduped);
      if (resp.status === 'ok' || resp.status === 'partial_error') {
        const okCount = Object.keys(resp.updated).length;
        const errCount = Object.keys(resp.errors || {}).length;
        const msg = errCount > 0
          ? `已更新 ${okCount} 项，${errCount} 项失败（已回滚）`
          : `已保存 ${okCount} 项设置`;
        window.App.showToast(msg, errCount > 0 ? 'warning' : 'success');
        if (errCount > 0) {
          this._showGroupErrors(resp.errors);
        } else {
          await this.loadSettings();
        }
      }
    } catch (err) {
      window.App.showToast(`保存失败: ${err.message}`, 'error');
    } finally {
      if (btn) { btn.disabled = false; }
      this._refreshDirtyUI();
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
