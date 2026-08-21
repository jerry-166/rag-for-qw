const { chromium } = require('playwright');
const path = require('path');
const SHOTS = path.join(__dirname, 'shots');
const errs = [];
(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', e => errs.push('PAGEERROR: ' + e.message));

  // 登录
  await page.goto('http://localhost:8000', { waitUntil: 'networkidle' });
  await page.fill('#login-username', 'admin');
  await page.fill('#login-password', 'admin123');
  await page.click('#login-form button[type="submit"]');
  await page.waitForSelector('.nav-item', { timeout: 15000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: SHOTS + '/01-shell-kb.png', fullPage: true });

  // 壳计算样式核验
  const styles = await page.evaluate(() => {
    const cs = el => el ? getComputedStyle(el) : null;
    const sb = cs(document.querySelector('.sidebar'));
    const tb = cs(document.querySelector('.topbar'));
    const stat = cs(document.querySelector('.stats-item-value'));
    const nav = cs(document.querySelector('.nav-item.active .nav-icon svg'));
    return {
      sidebar: { pos: sb.position, top: sb.top, bg: sb.backgroundColor, blur: sb.backdropFilter, radius: sb.borderRadius },
      topbar: { pos: tb.position, radius: tb.borderRadius, bg: tb.backgroundColor, blur: tb.backdropFilter },
      statNum: stat ? { fontVariant: stat.fontVariantNumeric, size: stat.fontSize } : null,
      navSvg: nav ? String(nav).slice(0,60) : null,
      accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
    };
  });
  console.log('STYLES', JSON.stringify(styles, null, 1));

  const KB = 'stage5-circle2-冒烟-' + Date.now().toString().slice(-6);
  // 建 KB（含策略字段）
  await page.click('#create-kb-btn');
  await page.waitForSelector('#kb-name');
  await page.fill('#kb-name', KB);
  await page.fill('#kb-description', '圈 2 壳重构冒烟');
  await page.selectOption('#kb-chunk-strategy', 'auto');
  await page.click('.modal-footer button:has-text("创建")');
  await page.waitForTimeout(1500);
  // 验证策略徽章
  {
  const cards2 = page.locator('.kb-card[data-kb-id]');
  const n2 = await cards2.count();
  let t2 = null;
  for (let i = 0; i < n2; i++) {
    const c = cards2.nth(i);
    if (((await c.locator('.kb-name').innerText())).trim() === KB) { t2 = await c.locator('.kb-badges').innerText(); break; }
  }
  badgeText = t2 || 'NO-BADGE';
}
  console.log('BADGES:', badgeText);
  await page.screenshot({ path: SHOTS + '/02-kb-created.png', fullPage: true });

  // 编辑 KB
  {
  const cards = page.locator('.kb-card[data-kb-id]');
  const n = await cards.count();
  let target = null;
  for (let i = 0; i < n; i++) {
    const c = cards.nth(i);
    const t = (await c.locator('.kb-name').innerText()).trim();
    if (t === KB) { target = c; break; }
  }
  await target.locator('.kb-actions .icon-btn[title="编辑"]').click();
}
  await page.waitForSelector('#kb-name');
  await page.fill('#kb-name', KB + '-改');
  await page.click('.modal-footer button:has-text("保存")');
  await page.waitForTimeout(1200);
  const edited = await page.locator('.kb-card[data-kb-id]:has-text("stage5-circle2-冒烟-改")').count();
  console.log('EDIT-OK:', edited > 0);
  await page.screenshot({ path: SHOTS + '/03-kb-edited.png', fullPage: true });

  // 折叠侧栏
  await page.click('#sidebar-toggle');
  await page.waitForTimeout(600);
  const collapsed = await page.evaluate(() => ({
    w: document.getElementById('sidebar').getBoundingClientRect().width,
    cls: document.getElementById('sidebar').classList.contains('collapsed'),
    grid: getComputedStyle(document.getElementById('app-shell')).gridTemplateColumns,
  }));
  console.log('COLLAPSED:', JSON.stringify(collapsed));
  await page.screenshot({ path: SHOTS + '/04-sidebar-collapsed.png' });

  // 头像弹菜单 + 退出登录
  await page.click('#sidebar-toggle'); // 展开
  await page.waitForTimeout(400);
  await page.click('#user-info-sidebar');
  await page.waitForTimeout(400);
  const menuVisible = await page.locator('.avatar-menu').count();
  console.log('AVATAR-MENU:', menuVisible);
  await page.screenshot({ path: SHOTS + '/05-avatar-menu.png' });
  await page.locator('.avatar-menu .am-item[data-act="logout"]').click();
  await page.waitForTimeout(1000);
  const loggedOut = await page.locator('#login-form').count();
  console.log('LOGOUT-OK:', loggedOut > 0);

  // 重新登录 → 亮色截图
  await page.fill('#login-username', 'admin');
  await page.fill('#login-password', 'admin123');
  await page.click('#login-form button[type="submit"]');
  await page.waitForSelector('.nav-item', { timeout: 15000 });
  await page.click('#theme-toggle');
  await page.waitForTimeout(800);
  const lightBg = await page.evaluate(() => getComputedStyle(document.body).className || '');
  await page.screenshot({ path: SHOTS + '/06-light-mode.png', fullPage: true });
  const isLight = await page.evaluate(() => document.body.classList.contains('light-mode'));
  console.log('LIGHT:', isLight);

  // 中屏 768-1023 图标轨
  await page.setViewportSize({ width: 900, height: 800 });
  await page.waitForTimeout(600);
  const mid = await page.evaluate(() => ({
    w: document.getElementById('sidebar').getBoundingClientRect().width,
    collapsed: document.getElementById('sidebar').classList.contains('collapsed'),
  }));
  console.log('MID-RANGE:', JSON.stringify(mid));
  await page.screenshot({ path: SHOTS + '/07-midrange-rail.png' });

  // <768 overlay 抽屉
  await page.setViewportSize({ width: 480, height: 800 });
  await page.waitForTimeout(600);
  await page.click('#mobile-menu-btn');
  await page.waitForTimeout(500);
  const drawer = await page.evaluate(() => {
    const sb = document.getElementById('sidebar');
    const r = sb.getBoundingClientRect();
    return { open: sb.classList.contains('mobile-open'), leftVisible: r.left >= 0, width: r.width };
  });
  console.log('DRAWER:', JSON.stringify(drawer));
  await page.screenshot({ path: SHOTS + '/08-mobile-drawer.png' });

  console.log('CONSOLE-ERRORS:', errs.length, errs.slice(0, 5));
  await browser.close();
})();
