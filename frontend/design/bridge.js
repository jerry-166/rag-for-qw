// design-bridge.js：让现有 App 实例适配设计稿新结构
// 拦截 window.App 赋值（app.js 末尾 new App() 实例），patch 实例方法
(function () {
  var _App;
  Object.defineProperty(window, 'App', {
    configurable: true,
    get: function () { return _App; },
    set: function (v) {
      _App = v;
      if (v && typeof v === 'object') patchInstance(v);
    }
  });

  function patchInstance(inst) {
    if (inst.__patched) return;
    inst.__patched = true;

    inst.updateUserInfo = function () {
      if (!this.user) return;
      var username = this.user.username || '用户';
      var role = this.user.role || '普通用户';
      var avatarText = username.charAt(0).toUpperCase();
      var setText = function (id, text) { var el = document.getElementById(id); if (el) el.textContent = text; };
      setText('sidebar-username', username);
      setText('sidebar-role', role);
      setText('user-avatar', avatarText);
      setText('topbar-username', username);
      setText('topbar-avatar', avatarText);
    };

    inst.initSidebarEvents = function () {
      var sidebar = document.getElementById('sidebar');
      var mobileBtn = document.getElementById('mobile-menu-btn');
      if (mobileBtn && sidebar) {
        mobileBtn.addEventListener('click', function () {
          sidebar.classList.toggle('mobile-open');
          if (sidebar.classList.contains('mobile-open')) {
            var overlay = document.createElement('div');
            overlay.className = 'sidebar-overlay';
            overlay.addEventListener('click', function () {
              sidebar.classList.remove('mobile-open');
              overlay.remove();
            });
            document.body.appendChild(overlay);
          } else {
            var ov = document.querySelector('.sidebar-overlay');
            if (ov) ov.remove();
          }
        });
      }
      var self = this;
      document.querySelectorAll('.nav-item').forEach(function (item) {
        item.addEventListener('click', function (e) {
          e.preventDefault();
          var page = item.dataset.page;
          self.navigate(page);
          document.querySelectorAll('.nav-item').forEach(function (n) { n.classList.remove('on'); });
          item.classList.add('on');
        });
      });
      self.initAvatarMenu();
    };

    inst.updateThemeIcon = function () {
      var tt = document.getElementById('theme-toggle');
      if (!tt) return;
      var isLight = document.body.classList.contains('light-mode');
      tt.textContent = isLight ? '☀' : '☾';
      tt.title = isLight ? '切换到暗色' : '切换到亮色';
    };

    inst.initStatsPreview = function () {};
    inst.loadStatsData = function () { return Promise.resolve(); };
    console.log('[bridge] App 实例已 patch');
  }

  // auth tab 切换用 .on 而非 .active
  function bindAuthTabs() {
    document.querySelectorAll('.auth-tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        var target = tab.dataset.tab;
        document.querySelectorAll('.auth-tab').forEach(function (t) { t.classList.remove('on'); });
        tab.classList.add('on');
        var lf = document.getElementById('login-form');
        var rf = document.getElementById('register-form');
        if (lf) lf.classList.toggle('hidden', target !== 'login');
        if (rf) rf.classList.toggle('hidden', target !== 'register');
      });
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindAuthTabs);
  } else {
    bindAuthTabs();
  }
})();
