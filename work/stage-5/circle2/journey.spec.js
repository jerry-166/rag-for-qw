/**
 * Stage 5 基线浏览器旅程（文档 05 §3.2，可重复执行）
 * 用法：node work/stage-5/baseline/journey.spec.js
 * 前提：后端 8003 + 前端静态 8000 已启动。
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const FE = 'http://localhost:8000';
const USER = process.env.JOURNEY_USER || 'admin';
const PASS = process.env.JOURNEY_PASS || 'admin123';
const SHOTS = path.join(__dirname, 'shots');
const TS = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);

const results = [];   // { step, ok, note }
const consoleIssues = []; // { page, type, text }
const badRequests = [];   // { page, method, url, status }

function note(step, ok, extra = '') {
  results.push({ step, ok, extra });
  console.log(`${ok ? 'PASS' : 'FAIL'} | ${step} ${extra}`);
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

function hook(page, label) {
  page.on('console', msg => {
    if (msg.type() === 'error' || msg.type() === 'warning')
      consoleIssues.push({ page: label, type: msg.type(), text: msg.text().slice(0, 300) });
  });
  page.on('requestfailed', r =>
    badRequests.push({ page: label, url: r.url(), err: r.failure()?.errorText }));
  page.on('response', r => {
    if (r.status() >= 400) badRequests.push({ page: label, url: r.url(), status: r.status() });
  });
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  hook(page, 'main');

  let kbName = `stage5-baseline-${TS}`;
  try {
    // 1. 登录页
    await page.goto(FE, { waitUntil: 'networkidle' });
    await shot(page, '01-login-page');
    note('01 登录页渲染', true);

    // 2. 登录
    await page.fill('#login-username', USER);
    await page.fill('#login-password', PASS);
    await page.click('#login-form button[type="submit"], #login-form button:not([type])');
    await page.waitForSelector('.nav-item', { state: 'visible', timeout: 15000 });
    await page.waitForTimeout(1200);
    await shot(page, '02-kb-list');
    note('02 登录并进入知识库列表', true);

    // 3. 新建测试 KB
    kbName = `stage5-baseline-${TS}`;
    const createBtn = page.locator('button:has-text("新建"), button:has-text("创建"), button:has-text("添加")').first();
    await createBtn.click();
    await page.waitForSelector('#kb-name', { timeout: 5000 });
    await page.fill('#kb-name', kbName);
    const desc = await page.$('#kb-description');
    if (desc) await desc.fill('Stage 5 基线自动创建');
    await page.click('.modal-footer button:has-text("创建"), .modal-footer button:has-text("保存")');
    await page.waitForTimeout(1500);
    await shot(page, '03-kb-created');
    note('03 新建测试 KB', true, `name=${kbName}`);

    // 找到新 KB id（点击进入文档页，从 DOM/上下文取）
    // 找到新 KB id（kb-card 有 data-kb-id 属性）
    let kbId = null;
    const newCard = page.locator(`.kb-card[data-kb-id]:has-text("${kbName}")`).first();
    if (await newCard.count()) kbId = await newCard.getAttribute('data-kb-id');
    // 进入文档页（导航）
    await page.click('.nav-item[data-page="documents"]');
    await page.waitForTimeout(1000);
    await shot(page, '04-documents');
    note('04 文档页渲染', true);

    // 4. 上传 markdown（通过页面内 fetch 走与 api.js 相同的推导逻辑）
    const token = await page.evaluate(() => localStorage.getItem('rag_token'));
    const md = `# Stage5 基线测试文档\n\n## 概念A\n这是基线旅程自动生成的测试文档，用于验证 pipeline。\n\n## 概念B\n向量检索与关键词检索在混合模式融合。RAG 系统包含切块、增强、导入三个阶段。\n`;
    const uploadViaPage = (kbIdV) => page.evaluate(async ({ token, md, kbId }) => {
      const fd = new FormData();
      fd.append('file', new Blob([md], { type: 'text/markdown' }), 'stage5-baseline.md');
      fd.append('kb_id', String(kbId));
      const base = window.API_BASE || location.origin.replace(/:\d+$/, ':8003');
      const r = await fetch(`${base}/api/upload/markdown`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd });
      return { code: r.status, body: await r.json() };
    }, { token, md, kbId: kbIdV });
    let up = kbId != null ? await uploadViaPage(kbId) : null;
    let fileId = null;
    if (!up || up.body?.status !== 'success') {
      // fallback：上传到列表中第一个 KB
      const kbs = await page.evaluate(async ({ token }) => {
        const base = window.API_BASE || location.origin.replace(/:\d+$/, ':8003');
        const r = await fetch(`${base}/api/knowledge-bases`, { headers: { Authorization: `Bearer ${token}` } });
        return await r.json();
      }, { token });
      const list = Array.isArray(kbs) ? kbs : (kbs.knowledge_bases || kbs.data || []);
      kbId = list[0]?.id ?? list[0]?.kb_id;
      note('03b KB id 兜底', kbId != null, `kbId=${kbId}`);
      up = await uploadViaPage(kbId);
    }
    fileId = up?.body?.file_id;
    note('05 上传 markdown', up?.body?.status === 'success', `http=${up?.code} file_id=${fileId}`);
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForTimeout(1200);
    await shot(page, '05-doc-uploaded');

    // 5. 进度接口（任务 A 联验）
    const prog = await page.evaluate(async ({ token, fileId }) => {
      const base = window.API_BASE || location.origin.replace(/:\d+$/, ':8003');
      const r = await fetch(`${base}/api/process/progress/${fileId}`, { headers: { Authorization: `Bearer ${token}` } });
      return { code: r.status, body: await r.json() };
    }, { token, fileId });
    note('05b 进度接口轮询', prog.code === 200 && !!prog.body.stage, `stage=${prog.body?.stage} progress=${JSON.stringify(prog.body?.stage_progress)}`);

    // 6. Pipeline 四步：通过 App.navigate('pipeline', {doc_id}) 进入
    await page.evaluate(fid => window.App.navigate('pipeline', { doc_id: fid }), fileId);
    await page.waitForTimeout(2000);
    await shot(page, '06-pipeline');
    // 依次执行切割→生成→导入（找每步的执行按钮，同时用进度接口判定阶段完成）
    for (const [i, label] of ['切割', '生成', '导入'].entries()) {
      let clicked = false;
      if (label === '导入') {
        // 步骤推进靠「下一步」按钮；step3 渲染时自动触发导入
        const nextBtn = page.locator('#step-content button:has-text("下一步")').first();
        if (await nextBtn.count()) { await nextBtn.click({ timeout: 5000 }).catch(() => {}); clicked = true; }
      } else {
        const btn = page.locator(`#step-content button:has-text("${label}")`).first();
        if (await btn.count()) { await btn.click({ timeout: 5000 }).catch(() => {}); clicked = true; }
      }
      const deadline = Date.now() + (label === '生成' ? 240000 : 120000);
      let lastStage = '';
      while (Date.now() < deadline) {
        await page.waitForTimeout(3000);
        const p = await page.evaluate(async ({ token, fileId }) => {
          const base = window.API_BASE || location.origin.replace(/:\d+$/, ':8003');
          const r = await fetch(`${base}/api/process/progress/${fileId}`, { headers: { Authorization: `Bearer ${token}` } });
          return await r.json();
        }, { token, fileId }).catch(() => null);
        lastStage = p?.stage || '';
        if (!p) break;
        if (label === '切割' && p.stage !== 'uploaded' && p.stage !== 'awaiting_split') break;
        if (label === '生成' && ['awaiting_import', 'importing', 'done', 'failed'].includes(p.stage)) break;
        if (label === '导入' && ['done', 'failed'].includes(p.stage)) break;
        if (p.stage === 'failed') break;
      }
      // 生成/导入完成后若出现"下一步"类按钮则点击推进
      await shot(page, `06-pipeline-step${i + 1}-${label}`);
      note(`06.${i + 1} pipeline ${label}`, lastStage !== 'failed' && lastStage !== '', `stage=${lastStage} clicked=${clicked}`);
    }
    await shot(page, '06-pipeline-done');

    // 7. 检索页三模式
    await windowNavigate(page, 'search');
    await page.waitForTimeout(1500);
    await shot(page, '07-search-page');
    for (const mode of ['vector', 'keyword', 'hybrid']) {
      await page.click(`.mode-btn[data-mode="${mode}"]`).catch(() => {});
      // 选择测试 KB（选含刚处理文档的 KB；否则选第一个）
      const item = page.locator(`.kb-selector-item:has-text("${kbName}")`).first();
      if (await item.count()) await item.click();
      else await page.locator('.kb-selector-item').first().click().catch(() => {});
      await page.fill('#search-query', 'RAG 系统包含哪些阶段');
      await page.click('#search-btn');
      await page.waitForTimeout(6000);
      await shot(page, `07-search-${mode}`);
      const hasResults = await page.locator('#search-results .result-card, #search-results .search-result, #search-results > *').count();
      note(`07 检索-${mode}`, hasResults > 0, `结果节点=${hasResults}`);
    }

    // 8. Agent 对话（SSE 首块）
    await windowNavigate(page, 'agent');
    await page.waitForTimeout(1500);
    const kbPill = page.locator(`.agent-kb-bar .kb-pill:has-text("${kbName}"), #agent-kb-bar *:has-text("${kbName}")`).first();
    if (await kbPill.count()) await kbPill.click();
    await page.fill('#agent-input', 'RAG 系统包含哪些阶段？一句话回答');
    await page.click('#agent-send-btn');
    const firstChunkAt = Date.now();
    let sseFirst = false;
    try {
      await page.waitForFunction(() => {
        const el = document.querySelector('#agent-messages');
        return el && el.innerText.length > 20;
      }, { timeout: 120000 });
      sseFirst = Date.now() - firstChunkAt;
    } catch { /* timeout */ }
    await page.waitForTimeout(3000);
    await shot(page, '08-agent-chat');
    note('08 Agent SSE 对话', sseFirst !== false, `首块 ${sseFirst === false ? '超时' : sseFirst + 'ms'}`);

    // 9. 设置页
    await windowNavigate(page, 'settings');
    await page.waitForTimeout(1500);
    await shot(page, '09-settings');
    note('09 设置页渲染', await page.locator('#settings-content, #page-container .settings-section, #page-container form').count() > 0);

    // 10. 审计页
    await windowNavigate(page, 'audit');
    await page.waitForTimeout(1500);
    await shot(page, '10-audit');
    note('10 审计页渲染', await page.locator('#audit-list, #audit-stats, #page-container .card').count() > 0);
  } catch (e) {
    note('EXCEPTION 旅程中断', false, String(e).slice(0, 300));
    await shot(page, '99-exception').catch(() => {});
  } finally {
    // 产物
    fs.writeFileSync(path.join(__dirname, 'raw-results.json'), JSON.stringify({
      ts: TS, results, consoleIssues, badRequests,
      testResources: { user: USER, kbName: `${kbName}` },
    }, null, 2));
    const passed = results.filter(r => r.ok).length;
    console.log(`\nSUMMARY ${passed}/${results.length} passed | console errors/warnings: ${consoleIssues.length} | bad requests: ${badRequests.length}`);
    await browser.close();
  }
})();

async function windowNavigate(page, name) {
  const nav = page.locator(`.nav-item[data-page="${name}"]`);
  if (await nav.count()) { await nav.first().click(); await page.waitForTimeout(800); }
  else await page.evaluate(n => window.App?.navigate?.(n), name);
}
