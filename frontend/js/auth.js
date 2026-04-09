/**
 * 认证模块
 */
const Auth = {
  render() {
    const tpl = document.getElementById('tpl-auth');
    const node = tpl.content.cloneNode(true);
    document.getElementById('app').innerHTML = '';
    document.getElementById('app').appendChild(node);
    this.bindEvents();
  },

  bindEvents() {
    // Tab 切换
    document.querySelectorAll('.auth-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const which = tab.dataset.tab;
        document.getElementById('login-form').classList.toggle('hidden', which !== 'login');
        document.getElementById('register-form').classList.toggle('hidden', which !== 'register');
      });
    });

    // 密码显隐
    document.querySelectorAll('.toggle-pwd').forEach(btn => {
      btn.addEventListener('click', () => {
        const inp = document.getElementById(btn.dataset.target);
        inp.type = inp.type === 'password' ? 'text' : 'password';
        btn.textContent = inp.type === 'password' ? '👁' : '🙈';
      });
    });

    // 登录表单
    document.getElementById('login-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      await this.handleLogin();
    });

    // 注册表单
    document.getElementById('register-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      await this.handleRegister();
    });
  },

  async handleLogin() {
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;
    const errEl = document.getElementById('login-error');
    const btn = document.querySelector('#login-form .btn-primary');
    const btnText = btn.querySelector('.btn-text');
    const btnLoading = btn.querySelector('.btn-loading');

    errEl.classList.add('hidden');
    btn.disabled = true;
    btnText.classList.add('hidden');
    btnLoading.classList.remove('hidden');

    try {
      const data = await AuthAPI.login(username, password);
      TokenManager.set(data.access_token);
      UserManager.set({
        id: data.user_id,
        username: data.username,
        role: data.role,
      });
      window.App.navigate('knowledge-bases');
      Toast.show(`欢迎回来，${data.username}！`, 'success');
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove('hidden');
    } finally {
      btn.disabled = false;
      btnText.classList.remove('hidden');
      btnLoading.classList.add('hidden');
    }
  },

  async handleRegister() {
    const username = document.getElementById('reg-username').value.trim();
    const email = document.getElementById('reg-email').value.trim();
    const password = document.getElementById('reg-password').value;
    const errEl = document.getElementById('register-error');
    const sucEl = document.getElementById('register-success');
    const btn = document.querySelector('#register-form .btn-primary');
    const btnText = btn.querySelector('.btn-text');
    const btnLoading = btn.querySelector('.btn-loading');

    errEl.classList.add('hidden');
    sucEl.classList.add('hidden');

    if (username.length < 3) {
      errEl.textContent = '用户名至少需要 3 个字符';
      errEl.classList.remove('hidden');
      return;
    }
    if (password.length < 6) {
      errEl.textContent = '密码至少需要 6 个字符';
      errEl.classList.remove('hidden');
      return;
    }

    btn.disabled = true;
    btnText.classList.add('hidden');
    btnLoading.classList.remove('hidden');

    try {
      await AuthAPI.register(username, email, password);
      sucEl.textContent = '注册成功！请切换到登录标签页登录';
      sucEl.classList.remove('hidden');
      document.getElementById('reg-username').value = '';
      document.getElementById('reg-email').value = '';
      document.getElementById('reg-password').value = '';
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove('hidden');
    } finally {
      btn.disabled = false;
      btnText.classList.remove('hidden');
      btnLoading.classList.add('hidden');
    }
  },
};
