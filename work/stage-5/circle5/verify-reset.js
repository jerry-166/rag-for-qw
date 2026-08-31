const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const errs = [];
  page.on('pageerror', e => errs.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await page.goto('http://127.0.0.1:8001/design/index.html', { waitUntil: 'networkidle' });
  await page.evaluate(() => { localStorage.removeItem('rag_token'); localStorage.removeItem('rag_user'); });
  await page.reload({ waitUntil: 'networkidle' });
  await page.fill('#login-username', 'admin');
  await page.fill('#login-password', 'admin123');
  await page.click('#login-form button[type="submit"]');
  await page.waitForTimeout(2500);
  await page.evaluate(() => window.App.navigate('settings'));
  await page.waitForTimeout(2500);
  // 改一个字段触发 dirty
  const r1 = await page.evaluate(() => {
    const t = document.querySelector('#settings-content .cfg-row input[type="number"]:not([readonly])');
    if (!t) return { found: false };
    t.value = String(Number(t.value) + 1);
    t.dispatchEvent(new Event('input', { bubbles: true }));
    t.dispatchEvent(new Event('change', { bubbles: true }));
    return { found: true, newVal: t.value };
  });
  console.log('改字段:', JSON.stringify(r1));
  await page.waitForTimeout(400);
  // 改后状态
  const r2 = await page.evaluate(() => ({
    topSaveDisabled: document.getElementById('btn-save-settings-top').disabled,
    topResetDisabled: document.getElementById('btn-reset-settings-top').disabled,
    groupSaveDisabled: document.querySelector('.settings-group-save').disabled,
    groupResetDisabled: document.querySelector('.settings-group-reset').disabled,
    saveText: document.getElementById('btn-save-settings-top').textContent.trim()
  }));
  console.log('改后:', JSON.stringify(r2));
  await page.screenshot({ path: 'd:\\workspace\\rag-for-qw\\work\\stage-5\\circle5\\shots\\settings-with-reset.png' });
  console.log('ERRORS:', errs.length ? errs : '无');
  await browser.close();
})();
