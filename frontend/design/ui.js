// ui.js — 全局玻璃风弹窗工具（design 体系）
// window.UI.confirm / UI.prompt / UI.alert：替代浏览器原生 confirm/prompt/alert
// 依赖：tokens.css + wireframe.css 的 .modal-overlay/.modal/.btn 样式
(function () {
  'use strict';

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function buildOverlay({ title, bodyHTML, okText = '确定', cancelText = '取消', danger = false, showCancel = true, maxWidth = 420, onOk, onOpen }) {
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'modal-overlay';
      overlay.innerHTML = `
        <div class="modal" style="max-width:${maxWidth}px" role="dialog" aria-modal="true" aria-label="${esc(title)}">
          <div class="modal-header">
            <h3 class="modal-title">${esc(title)}</h3>
            <button type="button" class="modal-close" aria-label="关闭">×</button>
          </div>
          <div class="modal-body">${bodyHTML}</div>
          <div class="modal-footer">
            ${showCancel ? `<button type="button" class="btn btn-ghost" data-act="cancel">${esc(cancelText)}</button>` : ''}
            <button type="button" class="btn ${danger ? 'btn-danger' : 'btn-primary'}" data-act="ok">${esc(okText)}</button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);
      const close = (v) => { overlay.remove(); resolve(v); };
      const ok = () => close(onOk ? onOk(overlay) : 'ok');
      overlay.addEventListener('click', (e) => { if (e.target === overlay) close(null); });
      overlay.querySelector('.modal-close').addEventListener('click', () => close(null));
      const cancelBtn = overlay.querySelector('[data-act="cancel"]');
      if (cancelBtn) cancelBtn.addEventListener('click', () => close(null));
      overlay.querySelector('[data-act="ok"]').addEventListener('click', ok);
      const onKey = (e) => {
        if (e.key === 'Escape') { close(null); document.removeEventListener('keydown', onKey); }
        else if (e.key === 'Enter') { ok(); document.removeEventListener('keydown', onKey); }
      };
      document.addEventListener('keydown', onKey);
      if (onOpen) onOpen(overlay, close);
    });
  }

  window.UI = {
    /** 确认弹窗：Promise<boolean>（true=确定 / false=取消） */
    confirm({ title, message, okText = '确定', cancelText = '取消', danger = false }) {
      const bodyHTML = `<p style="color:var(--text-2);line-height:1.6;margin:0">${esc(message)}</p>`;
      return buildOverlay({ title, bodyHTML, okText, cancelText, danger }).then(v => v === 'ok');
    },

    /** 输入弹窗：Promise<string|null>（字符串=确定并取输入值 / null=取消） */
    prompt({ title, message = '', defaultValue = '', placeholder = '', okText = '确定', cancelText = '取消' }) {
      const bodyHTML = `
        ${message ? `<p class="t2 mb4" style="line-height:1.5">${esc(message)}</p>` : ''}
        <input type="text" class="input" data-prompt-input value="${esc(defaultValue)}" placeholder="${esc(placeholder)}" />`;
      return buildOverlay({
        title, bodyHTML, okText, cancelText, maxWidth: 440,
        onOk: (overlay) => overlay.querySelector('[data-prompt-input]').value,
        onOpen: (overlay, close) => {
          const input = overlay.querySelector('[data-prompt-input]');
          setTimeout(() => { input.focus(); input.select(); }, 30);
          input.addEventListener('keydown', (e) => { if (e.key === 'Enter') close(input.value); });
        }
      });
    },

    /** 提示弹窗（替代 alert）：Promise<void> */
    alert({ title, message, okText = '知道了' }) {
      const bodyHTML = `<p style="color:var(--text-2);line-height:1.6;margin:0">${esc(message)}</p>`;
      return buildOverlay({ title, bodyHTML, okText, showCancel: false }).then(() => {});
    }
  };
})();
