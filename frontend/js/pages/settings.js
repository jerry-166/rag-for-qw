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
      <div class="row between mb6">
        <div>
          <h1 class="h-title">系统设置</h1>
          <p class="t2 mt2" style="font-size:var(--fs-sm)">大部分配置修改后立即生效，无需重启服务；敏感项留空表示不修改</p>
        </div>
        <div class="row" style="gap:var(--sp-2)">
          <button class="btn btn-ghost" id="btn-reset-settings-top" disabled>重置</button>
          <button class="btn btn-primary" id="btn-save-settings-top" disabled>保存设置（无改动）</button>
        </div>
      </div>
      <div id="settings-loading">
        <div class="skeleton" style="height:200px"></div>
      </div>
      <div class="hidden" id="settings-content"></div>
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
        <div class="glass"><div class="state"><div class="glyph" style="color:var(--danger)">✕</div><div class="title">加载配置失败</div><p class="desc">${this._escape(err.message)}</p></div></div>
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

    let html = `<div class="grid" style="grid-template-columns:230px 1fr;align-items:start;gap:var(--sp-4)">
      <div class="glass p4 col" id="settings-nav" style="gap:2px;position:sticky;top:calc(var(--topbar-h) + var(--sp-8))">
        <div class="label-caps mb4" style="padding:0 var(--sp-2)">配置组</div>
        ${presentGroups.map(g => `
          <div class="settings-grp ${g === this._activeGroup ? 'on' : ''}" data-nav-group="${g}">
            <span>${groups[g] || g}</span><i class="dirty-dot" data-nav-dirty="${g}"></i>
          </div>`).join('')}
      </div>
      <div class="col">`;

    // ── 可写配置区（按分组渲染，每组带保存按钮） ───────────
    for (const g of presentGroups) {
      const items = grouped[g];
      html += `<div class="glass p6 settings-section" data-group="${g}" ${g !== this._activeGroup ? 'hidden' : ''}>
        <div class="row between mb4">
          <div><h2 class="h-section">${groups[g] || g}</h2><p class="t3 mt2" style="font-size:var(--fs-xs)">修改后立即生效，无需重启</p></div>
          <div class="row" style="gap:var(--sp-2)">
            <span class="badge ok">运行时生效</span>
            <button class="btn btn-sm btn-ghost settings-group-reset" data-group="${g}" disabled>重置本组</button>
            <button class="btn btn-sm btn-primary settings-group-save" data-group="${g}" disabled>保存本组</button>
          </div>
        </div>
        <div class="settings-group-errors" data-group-errors="${g}"></div>`;
      for (const [key, meta] of items) {
        html += this._renderField(key, meta);
      }
      html += '</div>';
    }

    // ── 只读配置区（重启生效） ────────────────────────────
    const readonlyItems = Object.entries(data.readonly || {});
    if (readonlyItems.length) {
      html += '<div class="glass p6 settings-section" data-group="__readonly__" style="opacity:.78">';
      html += '<div class="row between mb4"><h2 class="h-section">只读配置（需重启）</h2><span class="badge">编辑 .env 后重启服务</span></div>';
      for (const [key, meta] of readonlyItems) {
        html += this._renderField(key, meta);
      }
      html += '</div>';
    }

    // ── 底部操作 ────────────────────────────────────────────
    html += `
      <div class="row mt6" style="gap:var(--sp-3)">
        <button class="btn btn-ghost" id="btn-reset-settings" disabled>全部重置</button>
        <button class="btn btn-primary" id="btn-save-settings" disabled>保存设置（无改动）</button>
      </div>
    </div></div>`;

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
        <div class="row" style="gap:var(--sp-2);align-items:center">
          <code class="mono t2" style="font-size:var(--fs-sm)">${this._escape(String(current))}</code>
          ${restartRequired ? '<span class="badge warn">需重启</span>' : '<span class="badge">只读</span>'}
        </div>
      `;
    } else if (meta.sensitive) {
      // 敏感项：密码框，留空不修改
      const state = meta.has_value
        ? '<span class="badge ok">已设置</span><button type="button" class="btn btn-sm btn-ghost settings-secret-clear" data-clear-key="' + key + '">清除</button>'
        : '<span class="badge">未设置</span>';
      inputHtml = `
        <div class="row" style="gap:var(--sp-2);align-items:center">
          <input type="password" class="input settings-input" id="${fieldId}" data-key="${key}" style="flex:1"
            placeholder="${meta.has_value ? '留空则不修改' : '请输入密钥'}" autocomplete="new-password" />
          ${state}
        </div>
      `;
    } else if (meta.type === 'enum') {
      const options = (meta.enum || []).map(v =>
        `<option value="${v}" ${String(v) === String(current) ? 'selected' : ''}>${v}</option>`
      ).join('');
      inputHtml = `<select class="select settings-input" id="${fieldId}" data-key="${key}">${options}</select>`;
    } else if (meta.type === 'csv') {
      // 文档 03：逗号分隔多值（checkbox 组）；全部未选 = 空串 = 全关
      const selectedSet = new Set(String(current || '').split(',').map(s => s.trim()).filter(Boolean));
      const boxes = (meta.enum || []).map(v => `
        <label class="row" style="gap:6px;font-size:var(--fs-sm);color:var(--text-2)">
          <input type="checkbox" class="settings-csv-box" data-key="${key}" value="${v}"
            ${selectedSet.has(String(v)) ? 'checked' : ''}> ${v}
        </label>
      `).join('');
      inputHtml = `
        <div class="row wrap" id="${fieldId}-group" style="gap:var(--sp-4)">${boxes}</div>
        <input type="hidden" class="settings-input" id="${fieldId}" data-key="${key}" value="${this._escape(String(current || ''))}">
      `;
    } else if (meta.type === 'float') {
      inputHtml = `
        <div class="row" style="gap:var(--sp-3);align-items:center">
          <input type="range" class="range settings-range" id="${fieldId}-range" style="flex:1"
            min="${meta.min}" max="${meta.max}" step="0.05" value="${current}"
            data-key="${key}" data-linked="${fieldId}">
          <input type="number" class="input settings-number" id="${fieldId}" style="width:80px"
            min="${meta.min}" max="${meta.max}" step="0.05" value="${current}"
            data-key="${key}" data-linked="${fieldId}-range">
        </div>
      `;
    } else if (meta.type === 'int') {
      inputHtml = `
        <input type="number" class="input settings-input" id="${fieldId}" style="max-width:200px"
          min="${meta.min}" max="${meta.max}" step="1" value="${current}"
          data-key="${key}">
      `;
    } else {
      inputHtml = `
        <input type="text" class="input settings-input" id="${fieldId}" value="${this._escape(String(current))}"
          data-key="${key}">
      `;
    }

    return `
      <div class="cfg-row settings-field" data-key="${key}" data-original="${this._escape(String(current ?? ''))}" style="display:grid;grid-template-columns:220px 1fr auto;gap:var(--sp-4);align-items:center;padding:var(--sp-4) 0;border-bottom:1px solid var(--glass-border)">
        <div class="col" style="gap:2px">
          <span style="font-size:var(--fs-sm);font-weight:560;color:var(--text-2)">${label}</span>
          <span class="mono t3" style="font-size:var(--fs-xs)">${key}</span>
          ${meta.description ? `<span class="t3" style="font-size:var(--fs-xs)">${meta.description}</span>` : ''}
        </div>
        <div>${inputHtml}</div>
        <span class="badge" style="visibility:hidden" data-dirty-marker></span>
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
    const saveBtnTop = document.getElementById('btn-save-settings-top');
    if (saveBtnTop) saveBtnTop.addEventListener('click', () => this.saveSettings());

    document.getElementById('btn-reset-settings').addEventListener('click', () => {
      this._resetAll();
    });
    const resetBtnTop = document.getElementById('btn-reset-settings-top');
    if (resetBtnTop) resetBtnTop.addEventListener('click', () => {
      this._resetAll();
    });

    // 本组重置：清除该组所有 dirty key + 重新加载该组字段为原始值
    document.querySelectorAll('.settings-group-reset').forEach(btn => {
      btn.addEventListener('click', () => this._resetGroup(btn.dataset.group));
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

  /** 本组重置：清除该组所有 dirty key + 把字段控件值恢复为原始值 */
  _resetGroup(groupKey) {
    const keys = this._groupKeys[groupKey] || [];
    keys.forEach(k => {
      this._dirtyKeys.delete(k);
      this._restoreFieldValue(k);
    });
    this._refreshDirtyUI();
    window.App.showToast(`已重置「${this._groupTitles?.[groupKey] || groupKey}」的本地修改`, 'success');
  },

  /** 全部重置：清空所有 dirty + 恢复全部字段原值（不复用 renderSettings，避免 _dirtyKeys 残留） */
  _resetAll() {
    Object.values(this._groupKeys).forEach(keys => {
      keys.forEach(k => {
        this._dirtyKeys.delete(k);
        this._restoreFieldValue(k);
      });
    });
    this._refreshDirtyUI();
    window.App.showToast('已重置所有本地修改', 'success');
  },

  /** 把单个字段的所有控件（input/range/number/csv/密码清除标记）恢复为原始值 */
  _restoreFieldValue(k) {
    // 匹配该 key 的所有可编辑控件（含 float 的 range+number、csv 的 hidden input）
    const els = document.querySelectorAll(`.settings-input[data-key="${k}"], .settings-range[data-key="${k}"], .settings-number[data-key="${k}"]`);
    let original;
    for (const el of els) {
      const field = el.closest('.settings-field');
      original = field ? field.dataset.original : undefined;
      if (original != null) el.value = String(original);
      // 双向联动：number↔range
      const linked = el.dataset.linked ? document.getElementById(el.dataset.linked) : null;
      if (linked) linked.value = String(original);
    }
    // csv checkbox 勾选同步
    const boxes = document.querySelectorAll(`.settings-csv-box[data-key="${k}"]`);
    if (boxes.length) {
      const field = boxes[0].closest('.settings-field');
      original = field ? field.dataset.original : undefined;
      const sel = new Set(String(original || '').split(',').map(s => s.trim()).filter(Boolean));
      boxes.forEach(b => { b.checked = sel.has(b.value); });
    }
    // 密码框清除「待清除」标记
    const clearBtn = document.querySelector(`.settings-secret-clear[data-clear-key="${k}"]`);
    if (clearBtn) { clearBtn.dataset.cleared = ''; clearBtn.textContent = '清除'; }
  },

  _refreshDirtyUI() {
    // 各组按钮：显示本组 dirty 数，无改动禁用
    document.querySelectorAll('.settings-group-save').forEach(btn => {
      const n = this._groupDirtyCount(btn.dataset.group);
      btn.textContent = n > 0 ? `保存本组 (${n})` : '保存本组';
      btn.disabled = n === 0;
    });
    // 本组重置按钮：只要本组有 dirty 就启用
    document.querySelectorAll('.settings-group-reset').forEach(btn => {
      btn.disabled = this._groupDirtyCount(btn.dataset.group) === 0;
    });
    // 导航 dirty 点（圈 4：线框 07 dirty-dot）
    document.querySelectorAll('[data-nav-dirty]').forEach(dot => {
      const dirty = this._groupDirtyCount(dot.dataset.navDirty) > 0;
      dot.style.display = dirty ? 'inline-block' : 'none';
    });
    // 底部按钮 + 顶部按钮
    const hasDirty = this._dirtyKeys.size > 0;
    const saveBtn = document.getElementById('btn-save-settings');
    const saveBtnTop = document.getElementById('btn-save-settings-top');
    const resetBtn = document.getElementById('btn-reset-settings');
    const resetBtnTop = document.getElementById('btn-reset-settings-top');
    const saveText = hasDirty ? `保存设置 (${this._dirtyKeys.size})` : '保存设置（无改动）';
    if (saveBtn) { saveBtn.disabled = !hasDirty; saveBtn.textContent = saveText; }
    if (saveBtnTop) { saveBtnTop.disabled = !hasDirty; saveBtnTop.textContent = saveText; }
    if (resetBtn) resetBtn.disabled = !hasDirty;
    if (resetBtnTop) resetBtnTop.disabled = !hasDirty;
    // 字段高亮：dirty 时显示「已改」金色徽章（替代 field-dirty class 边框）
    document.querySelectorAll('.settings-field[data-key]').forEach(f => {
      const marker = f.querySelector('[data-dirty-marker]');
      if (marker) {
        const dirty = this._dirtyKeys.has(f.dataset.key);
        marker.textContent = dirty ? '已改' : '';
        marker.classList.toggle('accent', dirty);
        marker.style.visibility = dirty ? 'visible' : 'hidden';
      }
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
    // partial_error：按 key → 组映射，组内联标红
    document.querySelectorAll('.settings-group-errors').forEach(el => (el.innerHTML = ''));
    document.querySelectorAll('.settings-field').forEach(f => {
      f.classList.remove('field-error');
      f.style.removeProperty('border');
    });
    for (const [key, msg] of Object.entries(errors || {})) {
      const field = document.querySelector(`.settings-field[data-key="${key}"]`);
      if (field) {
        field.classList.add('field-error');
        field.style.border = '1px solid var(--danger)';
        field.style.borderRadius = 'var(--r-sm)';
        field.style.padding = 'var(--sp-4)';
      }
      const g = this._fieldGroup(key);
      const box = g && document.querySelector(`[data-group-errors="${g}"]`);
      if (box) {
        box.innerHTML += `<div class="t3" style="color:var(--danger);font-size:var(--fs-xs);margin-top:var(--sp-2)">✕ ${key}: ${this._escape(String(msg))}</div>`;
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
    } catch (err) { /* request() 已自动 toast */
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
