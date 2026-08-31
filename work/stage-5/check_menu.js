const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('dialog', async d => { console.log('confirm:', d.message()); await d.dismiss(); });
  await page.goto('http://127.0.0.1:8123/frontend/design/page-wireframes/01-shell-kb.html', { waitUntil: 'networkidle' });
  await page.waitForTimeout(300);

  // 1. 点头像开菜单
  await page.click('.sidenav .row.mt4 .avatar'); await page.waitForTimeout(200);
  const m1 = await page.evaluate(() => {
    const m = document.querySelector('.avatar-menu');
    if (!m) return null;
    return {
      exists: true,
      itemCount: m.querySelectorAll('.am-item').length,
      labels: Array.from(m.querySelectorAll('.am-item')).map(b => b.textContent.trim().replace(/^\S+\s*/, '')),
      hasHeader: !!m.querySelector('.am-header'),
      headerUser: (m.querySelector('.am-header b') || {}).textContent
    };
  });
  console.log('1. 菜单:', m1);
  await page.screenshot({ path: 'work/stage-5/menu-open.png' });

  // 2. 点空白关
  await page.mouse.click(700, 500); await page.waitForTimeout(200);
  const m2 = await page.evaluate(() => !document.querySelector('.avatar-menu'));
  console.log('2. 点空白关:', m2 ? 'YES' : 'NO');

  // 3. 点头像开 + 再点头像切关
  await page.click('.sidenav .row.mt4 .avatar'); await page.waitForTimeout(200);
  await page.click('.sidenav .row.mt4 .avatar'); await page.waitForTimeout(200);
  const m3 = await page.evaluate(() => !document.querySelector('.avatar-menu'));
  console.log('3. 再点头像切关:', m3 ? 'YES' : 'NO');

  // 4. Esc 关
  await page.click('.sidenav .row.mt4 .avatar'); await page.waitForTimeout(200);
  await page.keyboard.press('Escape'); await page.waitForTimeout(200);
  const m4 = await page.evaluate(() => !document.querySelector('.avatar-menu'));
  console.log('4. Esc 关:', m4 ? 'YES' : 'NO');

  // 5. 菜单内点击不关菜单的设置项（点设置应仅关菜单）
  await page.click('.sidenav .row.mt4 .avatar'); await page.waitForTimeout(200);
  await page.click('.avatar-menu .am-item[data-act="settings"]'); await page.waitForTimeout(200);
  const m5 = await page.evaluate(() => !document.querySelector('.avatar-menu'));
  console.log('5. 点菜单项后菜单关闭:', m5 ? 'YES' : 'NO');

  // 6. 点退出登录弹 confirm，dismiss（已监听）后菜单应关
  await page.click('.sidenav .row.mt4 .avatar'); await page.waitForTimeout(200);
  await page.click('.avatar-menu .am-item[data-act="logout"]'); await page.waitForTimeout(300);
  const m6 = await page.evaluate(() => !document.querySelector('.avatar-menu'));
  console.log('6. 点退出（取消）后菜单关闭:', m6 ? 'YES' : 'NO');

  console.log(errors.length ? '\nERRORS:\n' + errors.join('\n') : '\nALL CLEAN');
  await browser.close();
})();