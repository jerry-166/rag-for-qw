// 侧栏：user-trigger 头像点击弹出菜单（豆包结构：头 + 切换账户 + 退出登录）
// 模板是 navigate 时才克隆的，需 MutationObserver 监听首次出现
function initAvatarMenu() {
  var sidenav = document.querySelector('.sidenav');
  if (!sidenav) return false;
  var trigger = sidenav.querySelector('.user-trigger');
  if (!trigger) return false;
  if (trigger.dataset.menuInit === '1') return true;
  trigger.dataset.menuInit = '1';

  var menu = null;

  function closeMenu() {
    if (!menu) return;
    menu.remove();
    menu = null;
    trigger.setAttribute('aria-expanded', 'false');
    document.removeEventListener('click', onDocClick, false);
    document.removeEventListener('keydown', onKey, false);
  }
  function onDocClick(e) {
    if (menu && menu.contains(e.target)) return;
    closeMenu();
  }
  function onKey(e) { if (e.key === 'Escape') closeMenu(); }

  function openMenu() {
    if (menu) { closeMenu(); return; }
    var name = (trigger.querySelector('.u-name') || {}).textContent || '用户';
    var role = (trigger.querySelector('.u-role') || {}).textContent || '';
    trigger.setAttribute('aria-expanded', 'true');

    menu = document.createElement('div');
    menu.className = 'avatar-menu';
    menu.setAttribute('role', 'menu');
    menu.innerHTML =
      '<div class="am-header">' +
        '<div class="am-avatar">' + (name.charAt(0).toUpperCase()) + '</div>' +
        '<div class="am-user"><b>' + name + '</b><div class="t3">' + role + '</div></div>' +
      '</div>' +
      '<div class="am-divider"></div>' +
      '<button type="button" class="am-item" role="menuitem" data-act="switch"><span class="am-ico">⇄</span>切换账户</button>' +
      '<button type="button" class="am-item danger" role="menuitem" data-act="logout"><span class="am-ico">⎋</span>退出登录</button>';
    document.body.appendChild(menu);

    var r = trigger.getBoundingClientRect();
    var mw = menu.offsetWidth, mh = menu.offsetHeight;
    var vw = window.innerWidth, vh = window.innerHeight;
    var gap = 8;
    var left = r.left + r.width / 2 - mw / 2;
    left = Math.max(gap, Math.min(left, vw - mw - gap));
    var top = r.top - mh - gap;
    if (top < gap) top = r.bottom + gap;
    if (top + mh > vh - gap) top = Math.max(gap, vh - mh - gap);
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';

    menu.querySelectorAll('.am-item').forEach(function (b) {
      b.addEventListener('click', function () {
        var act = b.getAttribute('data-act');
        if (act === 'logout') {
          closeMenu();
          window.UI.confirm({
            title: '退出登录',
            message: '确定退出登录吗？',
            okText: '退出',
            danger: true
          }).then(function (ok) {
            if (ok) {
              try { localStorage.removeItem('rag_token'); localStorage.removeItem('rag_user'); } catch (e) {}
            }
          });
        } else {
          closeMenu();
        }
      });
    });

    setTimeout(function () {
      document.addEventListener('click', onDocClick, false);
      document.addEventListener('keydown', onKey, false);
    }, 0);
  }

  trigger.addEventListener('click', function (e) {
    e.stopPropagation();
    openMenu();
  });
  trigger.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openMenu(); }
  });
  return true;
}

function tryInit() {
  if (initAvatarMenu()) return;
  var obs = new MutationObserver(function () {
    if (initAvatarMenu()) obs.disconnect();
  });
  obs.observe(document.body, { childList: true, subtree: true });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', tryInit);
} else {
  tryInit();
}