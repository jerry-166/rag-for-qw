/**
 * 圈 3 冒烟：documents / pipeline / search 三页按线框适配验证
 * 上传 md → 处理中队列卡真实进度 → pipeline 四步真走通 → 三模式检索 + 漏斗
 * 用法：node work/stage-5/circle3/smoke.js
 */
const { chromium } = require('playwright');
const path = require('path');
const SHOTS = path.join(__dirname, 'shots');
const errs = [];
let KB = null, fileId = null, kbId = null;

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

  // ===== documents 页 =====
  await page.click('.nav-item[data-page="documents"]');
  await page.waitForTimeout(1500);
  const dropzone = await page.evaluate(() => {
    const el = document.getElementById('upload-zone');
    if (!el) return null;
    const cs = getComputedStyle(el);
    return { exists: true, border: cs.borderTopStyle, radius: cs.borderRadius, cursor: cs.cursor };
  });
  console.log('DROPZONE:', JSON.stringify(dropzone));
  const tableCols = await page.evaluate(() => Array.from(document.querySelectorAll('#doc-table thead th')).map(th => th.textContent.trim()));
  console.log('TABLE-COLS:', JSON.stringify(tableCols));
  const iconBtns = await page.locator('#doc-table-body .icon-btn.act-delete').count();
  console.log('ICON-BTNS:', iconBtns);
  await page.screenshot({ path: SHOTS + '/01-documents.png', fullPage: true });

  // ===== 建 KB + 上传 md（拖拽逻辑等价路径：直接调页面上传方法） =====
  KB = 'stage5-circle3-' + Date.now().toString().slice(-6);
  {
    const token = await page.evaluate(() => localStorage.getItem('rag_token'));
    const r = await page.evaluate(async ({ token, KB }) => {
      const base = window.API_BASE || location.origin.replace(/:\d+$/, ':8003');
      const resp = await fetch(`${base}/api/knowledge-bases`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ kb_name: KB, description: '圈 3 冒烟', chunk_strategy: 'auto', enhancers: ['sub_question', 'summary'] }),
      });
      return { code: resp.status, body: await resp.json() };
    }, { token, KB });
    kbId = r.body.kb_id || r.body.id || (r.body.knowledge_base && r.body.knowledge_base.id);
    console.log('KB-CREATED:', r.code, 'kbId=', kbId);
  }

  // 通过页面上传（file input 设值；先选中新 KB，上传应落进该 KB）
  const md = `# 圈3冒烟测试文档\n\n## RAG 阶段\nRAG 系统包含切块、增强、导入三个阶段。向量检索与关键词检索在混合模式用 RRF 融合。\n\n## 检索\n混合检索先并行召回，再融合，最后可选精排。\n`;
  await page.waitForTimeout(1000);
  await page.evaluate(kb => { window.DocumentsPage.currentKbId = String(kb); document.getElementById('doc-kb-filter').value = String(kb); }, kbId);
  await page.setInputFiles('#file-input', {
    name: 'circle3-smoke.md', mimeType: 'text/markdown', buffer: Buffer.from(md, 'utf-8'),
  });
  await page.waitForTimeout(3000);
  fileId = await page.evaluate(() => {
    const rows = document.querySelectorAll('#doc-table-body tr[data-file-id]');
    return rows.length ? rows[0].dataset.fileId : null;
  });
  console.log('UPLOADED: file_id=', fileId);
  // 处理中队列卡可见性（chunk_done 状态会入列）
  const procCard = await page.evaluate(() => {
    const c = document.getElementById('processing-card');
    return c ? { visible: c.style.display !== 'none', text: c.innerText.slice(0, 120) } : null;
  });
  console.log('PROC-CARD:', JSON.stringify(procCard));
  await page.screenshot({ path: SHOTS + '/02-documents-uploaded.png', fullPage: true });

  // ===== pipeline 四步 =====
  await page.evaluate(fid => window.App.navigate('pipeline', { doc_id: fid }), fileId);
  await page.waitForTimeout(2500);
  const stepper = await page.evaluate(() => {
    const s = document.querySelector('.stepper-card');
    if (!s) return null;
    return {
      steps: Array.from(s.querySelectorAll('.s-name')).map(e => e.textContent),
      links: Array.from(s.querySelectorAll('.step-link > i')).map(e => e.style.transform),
      detail: (document.getElementById('stepper-detail') || {}).innerText || '',
    };
  });
  console.log('STEPPER:', JSON.stringify(stepper));
  await page.screenshot({ path: SHOTS + '/03-pipeline-step1.png', fullPage: true });

  // 依次：下一步（切割自动触发）→ 生成 → 导入，等待进度接口到 done
  const waitStage = async (targets, timeout = 240000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      await page.waitForTimeout(3000);
      const p = await page.evaluate(async () => {
        const token = localStorage.getItem('rag_token');
        const base = window.API_BASE || location.origin.replace(/:\d+$/, ':8003');
        const fid = window.PipelinePage.currentDocId;
        const r = await fetch(`${base}/api/process/progress/${fid}`, { headers: { Authorization: `Bearer ${token}` } });
        return await r.json();
      }).catch(() => null);
      if (!p) continue;
      if (targets.includes(p.stage)) return p;
    }
    return null;
  };

  // step1 → step2（切割在 loadChunks 自动执行）
  await page.click('#step-content button:has-text("下一步")');
  await waitStage(['generating', 'awaiting_import', 'importing', 'done']);
  const stepperGen = await page.evaluate(() => ({
    detail: (document.getElementById('stepper-detail') || {}).innerText || '',
    subs: Array.from(document.querySelectorAll('.s-sub')).map(e => e.textContent),
  }));
  console.log('STEPPER-AFTER-SPLIT:', JSON.stringify(stepperGen));
  await page.screenshot({ path: SHOTS + '/04-pipeline-step2-split.png', fullPage: true });

  // step2 → step3（生成自动执行，可能耗时）
  await page.click('#step-content button:has-text("下一步")');
  const pGen = await waitStage(['awaiting_import', 'importing', 'done']);
  console.log('GEN-STAGE:', pGen ? pGen.stage : 'TIMEOUT');
  const genShots = await page.evaluate(() => ({
    detail: (document.getElementById('stepper-detail') || {}).innerText || '',
    banner: (document.getElementById('missing-banner') || {}).style?.display,
  }));
  console.log('AFTER-GEN:', JSON.stringify(genShots));
  await page.screenshot({ path: SHOTS + '/05-pipeline-step3-generate.png', fullPage: true });

  // step3 → step4（导入自动执行）
  await page.click('#step-content button:has-text("下一步")');
  const pDone = await waitStage(['done', 'failed']);
  console.log('IMPORT-STAGE:', pDone ? pDone.stage : 'TIMEOUT');
  await page.waitForTimeout(2000);
  const timeline = await page.evaluate(() => ({
    upload: document.getElementById('tl-upload')?.textContent,
    split: document.getElementById('tl-split')?.textContent,
    generate: document.getElementById('tl-generate')?.textContent,
    embed: document.getElementById('tl-embed')?.textContent,
  }));
  console.log('TIMELINE:', JSON.stringify(timeline));
  await page.screenshot({ path: SHOTS + '/06-pipeline-step4-done.png', fullPage: true });

  // ===== 断点恢复：重进 pipeline 应直接显示完成态 =====
  await page.evaluate(() => window.App.navigate('documents'));
  await page.waitForTimeout(1200);
  await page.evaluate(fid => window.App.navigate('pipeline', { doc_id: fid }), fileId);
  await page.waitForTimeout(3000);
  const resume = await page.evaluate(() => ({
    detail: (document.getElementById('stepper-detail') || {}).innerText || '',
    orbs: Array.from(document.querySelectorAll('.stepper .orb')).map(e => e.textContent),
  }));
  console.log('RESUME:', JSON.stringify(resume));
  await page.screenshot({ path: SHOTS + '/07-pipeline-resume.png', fullPage: true });

  // ===== search 三模式 + 漏斗 =====
  await page.evaluate(() => window.App.navigate('search'));
  await page.waitForTimeout(2000);
  await page.selectOption('#kb-select', String(kbId));
  const hero = await page.evaluate(() => ({
    seg: document.querySelectorAll('.seg .mode-btn').length,
    strategy: !!document.getElementById('vector-strategy'),
    rerank: !!document.getElementById('toggle-rerank'),
    topk: !!document.getElementById('search-limit'),
  }));
  console.log('SEARCH-HERO:', JSON.stringify(hero));
  await page.screenshot({ path: SHOTS + '/08-search-hero.png', fullPage: true });

  for (const mode of ['vector', 'keyword', 'hybrid']) {
    await page.click(`.mode-btn[data-mode="${mode}"]`);
    await page.fill('#search-query', 'RAG 系统包含哪些阶段');
    await page.click('#search-btn');
    await page.waitForTimeout(6000);
    const funnel = await page.evaluate(() => {
      const f = document.getElementById('funnel-card');
      if (!f || f.style.display === 'none') return null;
      return {
        layers: Array.from(f.querySelectorAll('.funnel-layer .badge')).map(b => b.textContent.trim()),
        counts: Array.from(f.querySelectorAll('.fl-count')).map(e => e.textContent.trim()),
        stats: (document.getElementById('funnel-stats') || {}).innerText || '',
      };
    });
    const resultCount = await page.locator('#search-results .result-card').count();
    const srcBadges = await page.locator('#search-results .result-card .badge-sm').allTextContents();
    console.log(`SEARCH-${mode}:`, JSON.stringify({ funnel, resultCount, srcBadges: srcBadges.slice(0, 3) }));
    await page.screenshot({ path: SHOTS + `/09-search-${mode}.png`, fullPage: true });
  }

  // 最近搜索 chips
  const chips = await page.locator('#history-chips .src-chip').count();
  console.log('HISTORY-CHIPS:', chips);

  console.log('CONSOLE-ERRORS:', errs.length, errs.slice(0, 5));
  await browser.close();
})();
