/**
 * 主应用逻辑
 */
class App {
  constructor() {
    this.currentPage = null;
    this.isAuthenticated = false;
    this.user = null;
    // 不在构造函数中立即调用init，而是在DOM加载完成后调用
  }

  async init() {
    try {
      // 初始化主题
      this.initTheme();
      
      // 检查登录状态
      const token = sessionStorage.getItem('rag_token');
      const user = sessionStorage.getItem('rag_user');
      
      if (token && user) {
        this.isAuthenticated = true;
        this.user = JSON.parse(user);
        this.navigate('knowledge-bases');
      } else {
        this.navigate('auth');
      }
    } catch (error) {
      console.error('初始化失败:', error);
      this.navigate('auth');
    } finally {
      // 隐藏加载屏（auth 页可能无此元素，null 检查避免阻断初始化）
      const ls = document.getElementById('loading-screen');
      if (ls) ls.classList.add('hidden');
    }
  }

  initTheme() {
    // 读取存储的主题设置
    const savedTheme = localStorage.getItem('rag_theme');
    const isLightMode = savedTheme === 'light';
    
    // 应用主题
    if (isLightMode) {
      document.body.classList.add('light-mode');
    }
  }

  initThemeToggle() {
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
      // 更新图标
      this.updateThemeIcon();
      
      // 添加点击事件
      themeToggle.addEventListener('click', () => {
        document.body.classList.toggle('light-mode');
        const isLightMode = document.body.classList.contains('light-mode');
        
        // 保存设置
        localStorage.setItem('rag_theme', isLightMode ? 'light' : 'dark');
        
        // 更新图标
        this.updateThemeIcon();
      });
    }
  }

  updateThemeIcon() {
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
      const isLightMode = document.body.classList.contains('light-mode');
      themeToggle.classList.toggle('is-light', isLightMode);
      themeToggle.title = isLightMode ? '切换到黑夜模式' : '切换到白天模式';
    }
  }

  async navigate(page, params = {}) {
    this.currentPage = page;
    const appElement = document.getElementById('app');
    
    switch (page) {
      case 'auth':
        this.renderAuthPage();
        break;
      case 'knowledge-bases':
        if (this.isAuthenticated) {
          await this.renderAppLayout('知识库', async () => {
            if (window.KnowledgeBasesPage) {
              await window.KnowledgeBasesPage.render();
            }
          });
        } else {
          this.navigate('auth');
        }
        break;
      case 'documents':
        if (this.isAuthenticated) {
          await this.renderAppLayout('文档管理', async () => {
            if (window.DocumentsPage) {
              await window.DocumentsPage.render(params);
            }
          });
        } else {
          this.navigate('auth');
        }
        break;
      case 'pipeline':
        if (this.isAuthenticated) {
          await this.renderAppLayout('文档处理流水线', async () => {
            if (window.PipelinePage) {
              await window.PipelinePage.render(params);
            }
          });
        } else {
          this.navigate('auth');
        }
        break;
      case 'search':
        if (this.isAuthenticated) {
          await this.renderAppLayout('知识检索', async () => {
            if (window.SearchPage) {
              await window.SearchPage.render();
            }
          });
        } else {
          this.navigate('auth');
        }
        break;
      case 'agent':
        if (this.isAuthenticated) {
          await this.renderAppLayout('AI Agent', async () => {
            if (window.AgentPage) {
              await window.AgentPage.render();
            }
          });
        } else {
          this.navigate('auth');
        }
        break;
      case 'faq':
        if (this.isAuthenticated) {
          await this.renderAppLayout('知识记忆', async () => {
            if (window.FAQPage) {
              await window.FAQPage.render();
            }
          });
        } else {
          this.navigate('auth');
        }
        break;
      case 'settings':
        if (this.isAuthenticated) {
          await this.renderAppLayout('系统设置', async () => {
            if (window.SettingsPage) {
              await window.SettingsPage.render();
            }
          });
        } else {
          this.navigate('auth');
        }
        break;
      case 'audit':
        if (this.isAuthenticated) {
          await this.renderAppLayout('审计中心', async () => {
            if (window.AuditPage) {
              await window.AuditPage.render();
            }
          });
        } else {
          this.navigate('auth');
        }
        break;
      case 'cache':
        // 缓存中心（文档 08）— 仅管理员可见
        if (this.isAuthenticated) {
          const isAdmin = (window.UserManager && UserManager.get() && UserManager.get().role === 'admin');
          await this.renderAppLayout('缓存中心', async () => {
            if (!isAdmin) {
              const c = document.getElementById('page-container');
              c.innerHTML = '<div class="glass"><div class="state"><div class="glyph" style="color:var(--danger)">✕</div><div class="title">无权限</div><p class="desc">缓存中心仅管理员可访问</p></div></div>';
              return;
            }
            if (window.CachePage) {
              await window.CachePage.render();
            }
          });
        } else {
          this.navigate('auth');
        }
        break;
      default:
        this.navigate('knowledge-bases');
    }
  }

  renderAuthPage() {
    const authTemplate = document.getElementById('tpl-auth');
    const authContent = authTemplate.content.cloneNode(true);
    document.getElementById('app').innerHTML = '';
    document.getElementById('app').appendChild(authContent);
    this.initAuthEvents();
  }

  async renderAppLayout(title, contentCallback) {
    const appTemplate = document.getElementById('tpl-app');
    const appContent = appTemplate.content.cloneNode(true);
    document.getElementById('app').innerHTML = '';
    document.getElementById('app').appendChild(appContent);
    
    // 更新标题
    document.getElementById('topbar-breadcrumb').textContent = title;
    
    // 更新用户信息
    this.updateUserInfo();
    
    // 初始化侧边栏
    this.initSidebarEvents();
    
    // 初始化主题切换
    this.initThemeToggle();

    // 根据当前页面高亮导航项（每次重渲染布局后恢复）
    document.querySelectorAll('.nav-item').forEach(nav => {
      nav.classList.toggle('active', nav.dataset.page === this.currentPage);
    });
    
    // 并行加载统计数据和页面内容
    const pageContainer = document.getElementById('page-container');
    pageContainer.innerHTML = '';
    
    // 先渲染布局，再加载数据（避免竞态）
    await contentCallback();
    await this.loadStatsData(); // 加载统计数据
    
    // 初始化统计预览（在数据加载后）
    this.initStatsPreview();
  }

  updateUserInfo() {
    if (this.user) {
      const username = this.user.username || '用户';
      const role = this.user.role === 'admin' ? '管理员' : (this.user.role || '普通用户');
      const avatarText = username.charAt(0).toUpperCase();

      // 侧边栏用户信息
      document.getElementById('sidebar-username').textContent = username;
      document.getElementById('sidebar-role').textContent = role;
      document.getElementById('user-avatar').textContent = avatarText;

      // 顶部栏头像
      document.getElementById('topbar-avatar').textContent = avatarText;
    }
  }

  initStatsPreview() {
    // 圈 2：统计概览已改为常显 2×2 数字带，无展开/收起交互
  }

  /* ===== 圈 2：头像弹菜单（线框 01 / sidebar.js 蓝本，含退出登录） ===== */
  initAvatarMenu() {
    const trigger = document.getElementById('user-info-sidebar') || document.getElementById('user-trigger');
    const triggerTop = document.getElementById('topbar-avatar-btn') || document.getElementById('topbar-avatar');
    if (!trigger || trigger.dataset.menuInit === '1') return;
    trigger.dataset.menuInit = '1';

    const closeMenu = () => {
      this._avatarMenu?.remove();
      this._avatarMenu = null;
      trigger.setAttribute('aria-expanded', 'false');
      triggerTop?.setAttribute('aria-expanded', 'false');
      document.removeEventListener('click', this._avatarMenuDocClick, false);
      document.removeEventListener('keydown', this._avatarMenuKey, false);
    };
    this._avatarMenuDocClick = (e) => {
      if (this._avatarMenu && !this._avatarMenu.contains(e.target) && !trigger.contains(e.target) && !triggerTop?.contains(e.target)) closeMenu();
    };
    this._avatarMenuKey = (e) => { if (e.key === 'Escape') closeMenu(); };

    const openMenu = (anchor) => {
      if (this._avatarMenu) { closeMenu(); return; }
      const username = this.user?.username || '用户';
      const role = this.user?.role === 'admin' ? '管理员' : (this.user?.role || '普通用户');

      const menu = document.createElement('div');
      menu.className = 'avatar-menu';
      menu.setAttribute('role', 'menu');
      menu.innerHTML = `
        <div class="am-header">
          <div class="am-avatar">${username.charAt(0).toUpperCase()}</div>
          <div class="am-user"><b></b><div class="t3"></div></div>
        </div>
        <div class="am-divider"></div>
        <button type="button" class="am-item" role="menuitem" data-act="switch">
          <span class="am-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 3h5v5M21 3l-7 7M8 21H3v-5M3 21l7-7M21 16v5h-5M14 14l7 7M3 8V3h5M10 10 3 3"/></svg></span>切换账户
        </button>
        <button type="button" class="am-item danger" role="menuitem" data-act="logout">
          <span class="am-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/></svg></span>退出登录
        </button>`;
      menu.querySelector('.am-user b').textContent = username;
      menu.querySelector('.am-user .t3').textContent = role;
      document.body.appendChild(menu);

      // 视口坐标定位：默认贴锚点上方 8px 水平居中，上空间不足改向下，四边 8px 边界保护
      const r = anchor.getBoundingClientRect();
      const mw = menu.offsetWidth, mh = menu.offsetHeight;
      const vw = window.innerWidth, vh = window.innerHeight, gap = 8;
      let left = r.left + r.width / 2 - mw / 2;
      left = Math.max(gap, Math.min(left, vw - mw - gap));
      let top = r.top - mh - gap;
      if (top < gap) top = r.bottom + gap;
      if (top + mh > vh - gap) top = Math.max(gap, vh - mh - gap);
      menu.style.left = left + 'px';
      menu.style.top = top + 'px';

      trigger.setAttribute('aria-expanded', 'true');
      triggerTop?.setAttribute('aria-expanded', 'true');
      this._avatarMenu = menu;

      menu.querySelector('[data-act="logout"]').addEventListener('click', () => {
        closeMenu();
        this.logout();
      });
      menu.querySelector('[data-act="switch"]').addEventListener('click', () => {
        closeMenu();
        this.logout();
      });
      setTimeout(() => {
        document.addEventListener('click', this._avatarMenuDocClick, false);
        document.addEventListener('keydown', this._avatarMenuKey, false);
      }, 0);
    };

    trigger.addEventListener('click', (e) => { e.stopPropagation(); openMenu(trigger); });
    trigger.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openMenu(trigger); }
    });
    triggerTop?.addEventListener('click', (e) => { e.stopPropagation(); openMenu(triggerTop); });
  }

  logout() {
    sessionStorage.removeItem('rag_token');
    sessionStorage.removeItem('rag_user');
    this.isAuthenticated = false;
    this.user = null;
    this.navigate('auth');
  }

  async loadStatsData() {
    try {
      // 兼容性检查
      if (!window.DocumentAPI || typeof window.DocumentAPI.getStatsOverview !== 'function') {
        console.warn('DocumentAPI.getStatsOverview 未就绪，跳过统计数据加载');
        return;
      }
      const response = await window.DocumentAPI.getStatsOverview();
      
      // 确保 response 存在
      if (!response) {
        throw new Error('Empty response');
      }
      
      // 后端返回格式: { status: "success", data: { total_documents, ... } }
      const stats = response.data || response;
      
      // 确保 stats 是对象
      if (!stats || typeof stats !== 'object') {
        console.warn('统计数据格式异常:', stats);
        throw new Error('Invalid stats data');
      }
      
      // 更新统计数据
      if (document.getElementById('stats-documents')) {
        document.getElementById('stats-documents').textContent = stats.total_documents ?? 0;
      }
      if (document.getElementById('stats-chunks')) {
        document.getElementById('stats-chunks').textContent = stats.total_chunks ?? 0;
      }
      if (document.getElementById('stats-sub-questions')) {
        document.getElementById('stats-sub-questions').textContent = stats.total_sub_questions ?? 0;
      }
      if (document.getElementById('stats-summaries')) {
        document.getElementById('stats-summaries').textContent = stats.total_summaries ?? 0;
      }
      
      // 如果是admin用户，添加用户统计
      if (stats.is_admin && this.user && this.user.role === 'admin') {
        const statsContent = document.getElementById('sidebar-stats-content');
        if (statsContent) {
          // 检查是否已存在用户统计项
          if (!document.getElementById('stats-users')) {
            const userStatsItem = document.createElement('div');
            userStatsItem.className = 'stats-cell';
            userStatsItem.innerHTML = `
              <span class="stats-item-value" id="stats-users">${stats.total_users ?? 0}</span>
              <span class="stats-item-label">用户</span>
            `;
            statsContent.appendChild(userStatsItem);
          } else if (document.getElementById('stats-users')) {
            document.getElementById('stats-users').textContent = stats.total_users ?? 0;
          }
        }
      }
    } catch (error) {
      console.error('加载统计数据失败:', error);
      // 加载失败时不显示错误，保持默认值
    }
  }

  initSidebarEvents() {
    // 侧边栏切换（状态持久化）
    const sidebar = document.getElementById('sidebar');
    const sidebarToggle = document.getElementById('sidebar-toggle');
    if (localStorage.getItem('rag_sidebar_collapsed') === '1') {
      sidebar.classList.add('collapsed');
    }
    const syncToggleTitle = () => {
      sidebarToggle.title = sidebar.classList.contains('collapsed') ? '展开侧边栏' : '折叠侧边栏';
      sidebarToggle.setAttribute('aria-label', sidebarToggle.title);
    };
    syncToggleTitle();
    sidebarToggle.addEventListener('click', () => {
      sidebar.classList.toggle('collapsed');
      localStorage.setItem('rag_sidebar_collapsed', sidebar.classList.contains('collapsed') ? '1' : '0');
      syncToggleTitle();
    });

    // 头像弹菜单（含退出登录，线框 01 sidebar.js 蓝本）
    this.initAvatarMenu();

    // 圈 2：768-1023 折叠为 68px 图标轨（沿用已有折叠态）；>=1024 恢复用户偏好
    const mqMid = window.matchMedia('(min-width: 768px) and (max-width: 1023px)');
    const syncResponsive = () => {
      const sidebar = document.getElementById('sidebar');
      if (!sidebar) return;
      if (mqMid.matches) {
        sidebar.classList.add('collapsed');
      } else if (window.innerWidth >= 1024) {
        sidebar.classList.toggle('collapsed', localStorage.getItem('rag_sidebar_collapsed') === '1');
      }
    };
    mqMid.addEventListener('change', syncResponsive);
    syncResponsive();

    // 移动端菜单（<768 overlay 抽屉）
    document.getElementById('mobile-menu-btn').addEventListener('click', () => {
      sidebar.classList.toggle('mobile-open');

      // 添加遮罩
      if (sidebar.classList.contains('mobile-open')) {
        const overlay = document.createElement('div');
        overlay.className = 'sidebar-overlay';
        overlay.addEventListener('click', () => {
          sidebar.classList.remove('mobile-open');
          overlay.remove();
        });
        document.body.appendChild(overlay);
      } else {
        const overlay = document.querySelector('.sidebar-overlay');
        if (overlay) overlay.remove();
      }
    });

    // 导航项点击
    document.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const page = item.dataset.page;
        this.navigate(page);

        // 更新激活状态
        document.querySelectorAll('.nav-item').forEach(nav => nav.classList.remove('active'));
        item.classList.add('active');

        // 关闭移动端侧边栏
        const sidebar = document.getElementById('sidebar');
        if (sidebar.classList.contains('mobile-open')) {
          sidebar.classList.remove('mobile-open');
          const overlay = document.querySelector('.sidebar-overlay');
          if (overlay) overlay.remove();
        }
      });
    });
  }

  initAuthEvents() {
    // Tab 切换
    document.querySelectorAll('.auth-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        const target = tab.dataset.tab;
        
        // 更新 tab 状态
        document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        
        // 显示对应的表单
        document.getElementById('login-form').classList.toggle('hidden', target !== 'login');
        document.getElementById('register-form').classList.toggle('hidden', target !== 'register');
      });
    });
    
    // 密码切换
    document.querySelectorAll('.toggle-pwd').forEach(btn => {
      btn.addEventListener('click', () => {
        const targetId = btn.dataset.target;
        const input = document.getElementById(targetId);
        const type = input.type === 'password' ? 'text' : 'password';
        input.type = type;
        btn.textContent = type === 'password' ? '👁' : '🔒';
      });
    });
    
    // 登录表单
    document.getElementById('login-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const username = document.getElementById('login-username').value.trim();
      const password = document.getElementById('login-password').value;
      const errorEl = document.getElementById('login-error');
      const btn = e.submitter;
      const btnText = btn.querySelector('.btn-text');
      const btnLoading = btn.querySelector('.btn-loading');
      
      if (!username || !password) {
        errorEl.textContent = '请输入用户名和密码';
        errorEl.classList.remove('hidden');
        return;
      }
      
      try {
        errorEl.classList.add('hidden');
        btnText.classList.add('hidden');
        btnLoading.classList.remove('hidden');
        
        const data = await window.AuthAPI.login(username, password);
        sessionStorage.setItem('rag_token', data.access_token);
        sessionStorage.setItem('rag_user', JSON.stringify({
          username: data.username,
          user_id: data.user_id,
          role: data.role
        }));
        
        this.isAuthenticated = true;
        this.user = {
          username: data.username,
          user_id: data.user_id,
          role: data.role
        };
        
        this.showToast('登录成功', 'success');
        this.navigate('knowledge-bases');
        
        // 登录后重新加载统计数据
        setTimeout(() => {
          this.loadStatsData();
        }, 500);
      } catch (error) {
        errorEl.textContent = error.message || '登录失败';
        errorEl.classList.remove('hidden');
      } finally {
        btnText.classList.remove('hidden');
        btnLoading.classList.add('hidden');
      }
    });
    
    // 注册表单
    document.getElementById('register-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const username = document.getElementById('reg-username').value.trim();
      const email = document.getElementById('reg-email').value.trim();
      const password = document.getElementById('reg-password').value;
      const errorEl = document.getElementById('register-error');
      const successEl = document.getElementById('register-success');
      const btn = e.submitter;
      const btnText = btn.querySelector('.btn-text');
      const btnLoading = btn.querySelector('.btn-loading');
      
      if (!username || !email || !password) {
        errorEl.textContent = '请填写所有字段';
        errorEl.classList.remove('hidden');
        return;
      }
      
      if (password.length < 6) {
        errorEl.textContent = '密码长度至少6位';
        errorEl.classList.remove('hidden');
        return;
      }
      
      try {
        errorEl.classList.add('hidden');
        successEl.classList.add('hidden');
        btnText.classList.add('hidden');
        btnLoading.classList.remove('hidden');
        
        await window.AuthAPI.register(username, email, password);
        
        successEl.textContent = '注册成功，请登录';
        successEl.classList.remove('hidden');
        
        // 切换到登录表单
        document.querySelector('.auth-tab[data-tab="login"]').click();
        document.getElementById('login-username').value = username;
      } catch (error) {
        errorEl.textContent = error.message || '注册失败';
        errorEl.classList.remove('hidden');
      } finally {
        btnText.classList.remove('hidden');
        btnLoading.classList.add('hidden');
      }
    });
  }

  showToast(message, type = 'info') {
    const toastContainer = document.getElementById('toast-container') || this.createToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    // 动态内容（文件名/用户名/后端 detail）统一转义，防止注入 HTML
    const safeMsg = String(message ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    toast.innerHTML = `
      <span class="toast-icon">${this.getToastIcon(type)}</span>
      <span class="toast-message">${safeMsg}</span>
      <button class="toast-close" aria-label="关闭提示">×</button>
    `;

    toastContainer.appendChild(toast);

    // 关闭按钮
    toast.querySelector('.toast-close').addEventListener('click', () => {
      this.removeToast(toast);
    });

    // 自动关闭：成功/信息 3s；错误/警告 6s（失败原因需要时间阅读）
    const duration = (type === 'error' || type === 'warning') ? 6000 : 3000;
    setTimeout(() => {
      this.removeToast(toast);
    }, duration);
  }

  createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
    return container;
  }

  // 全局全屏 loading 遮罩：用于长耗时操作（克隆/删除等），持续可见 + 阻断重复点击
  // 教训（BUG-015/016）：瞬时 toast 3s 消失，长操作必须用持续遮罩，否则用户"以为没反应"
  showLoading(message = '处理中…') {
    let overlay = document.getElementById('app-loading');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'app-loading';
      // z-index 998：低于 toast-container(9999)，保证完成/失败提示可见
      overlay.style.cssText = 'position:fixed;inset:0;z-index:998;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:var(--sp-4);background:rgba(10,12,20,0.55);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)';
      overlay.innerHTML = `
        <div class="spinner" style="width:40px;height:40px;border:3px solid rgba(255,255,255,0.25);border-top-color:#fff;border-radius:50%;animation:spin 0.8s linear infinite"></div>
        <p style="color:#fff;font-size:14px;margin:0">${String(message ?? '').replace(/[&<>"']/g, c =>
          ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))}</p>`;
      document.body.appendChild(overlay);
    } else {
      overlay.style.display = 'flex';
      overlay.querySelector('p').textContent = message;
    }
    if (!document.querySelector('#app-loading style.spin-rule')) {
      const style = document.createElement('style');
      style.className = 'spin-rule';
      style.textContent = '@keyframes spin { to { transform: rotate(360deg); } }';
      document.head.appendChild(style);
    }
  }

  hideLoading() {
    const overlay = document.getElementById('app-loading');
    if (overlay) overlay.remove();
  }

  removeToast(toast) {
    toast.classList.add('removing');
    setTimeout(() => {
      toast.remove();
    }, 300);
  }

  getToastIcon(type) {
    switch (type) {
      case 'success': return '✅';
      case 'error': return '❌';
      case 'warning': return '⚠️';
      default: return 'ℹ️';
    }
  }
}

/** 按钮加载态工具：禁用按钮 + 保存原文案，返回恢复函数 */
function btnLoading(btn, loadingText = '处理中…') {
  if (!btn) return () => {};
  const orig = btn.textContent;
  const origDisabled = btn.disabled;
  btn.disabled = true;
  btn.textContent = loadingText;
  return () => { btn.disabled = origDisabled; btn.textContent = orig; };
}

// 当DOM加载完成后初始化应用
document.addEventListener('DOMContentLoaded', function() {
  // 先暴露API（必须在 init() 之前，否则异步 navigate 时 API 尚未挂载）
  window.TokenManager = TokenManager;
  window.UserManager = UserManager;
  window.AuthAPI = AuthAPI;
  window.KnowledgeBaseAPI = KnowledgeBaseAPI;
  window.DocumentAPI = DocumentAPI;
  window.SearchAPI = SearchAPI;
  window.AgentAPI = AgentAPI;
  window.SettingsAPI = SettingsAPI;
  window.AuditAPI = AuditAPI;
  window.CacheAPI = CacheAPI;

  // 初始化应用
  window.App = new App();
window.btnLoading = btnLoading;
  // 调用init方法
  window.App.init();
});