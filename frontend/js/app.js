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
      // 检查登录状态
      const token = localStorage.getItem('rag_token');
      const user = localStorage.getItem('rag_user');
      
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
      // 隐藏加载屏
      document.getElementById('loading-screen').classList.add('hidden');
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
    
    // 渲染页面内容
    const pageContainer = document.getElementById('page-container');
    pageContainer.innerHTML = '';
    await contentCallback();
  }

  updateUserInfo() {
    if (this.user) {
      const username = this.user.username || '用户';
      const role = this.user.role || '普通用户';
      const avatarText = username.charAt(0).toUpperCase();
      
      // 侧边栏用户信息
      document.getElementById('sidebar-username').textContent = username;
      document.getElementById('sidebar-role').textContent = role;
      document.getElementById('user-avatar').textContent = avatarText;
      
      // 顶部栏用户信息
      document.getElementById('topbar-username').textContent = username;
      document.getElementById('topbar-avatar').textContent = avatarText;
    }
  }

  initSidebarEvents() {
    // 侧边栏切换
    document.getElementById('sidebar-toggle').addEventListener('click', () => {
      document.getElementById('sidebar').classList.toggle('collapsed');
    });
    
    // 移动端菜单
    document.getElementById('mobile-menu-btn').addEventListener('click', () => {
      const sidebar = document.getElementById('sidebar');
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
    
    // 退出登录
    document.getElementById('logout-btn').addEventListener('click', () => {
      localStorage.removeItem('rag_token');
      localStorage.removeItem('rag_user');
      this.isAuthenticated = false;
      this.user = null;
      this.navigate('auth');
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
        localStorage.setItem('rag_token', data.access_token);
        localStorage.setItem('rag_user', JSON.stringify({
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
    toast.innerHTML = `
      <span class="toast-icon">${this.getToastIcon(type)}</span>
      <span class="toast-message">${message}</span>
      <button class="toast-close">×</button>
    `;
    
    toastContainer.appendChild(toast);
    
    // 关闭按钮
    toast.querySelector('.toast-close').addEventListener('click', () => {
      this.removeToast(toast);
    });
    
    // 自动关闭
    setTimeout(() => {
      this.removeToast(toast);
    }, 3000);
  }

  createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
    return container;
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

// 当DOM加载完成后初始化应用
document.addEventListener('DOMContentLoaded', function() {
  // 初始化应用
  window.App = new App();
  // 调用init方法
  window.App.init();

  // 暴露API
  window.TokenManager = TokenManager;
  window.UserManager = UserManager;
  window.AuthAPI = AuthAPI;
  window.KnowledgeBaseAPI = KnowledgeBaseAPI;
  window.DocumentAPI = DocumentAPI;
  window.SearchAPI = SearchAPI;
});