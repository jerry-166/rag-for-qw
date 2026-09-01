async page => {
  await page.waitForSelector('input[type="password"]', { timeout: 10000 });
  await page.getByRole('textbox', { name: '输入用户名' }).fill('admin');
  await page.getByRole('textbox', { name: '输入密码' }).fill('admin');
  await page.getByRole('button', { name: '登 录' }).click();
  await page.waitForTimeout(2500);
  await page.getByRole('link', { name: '☑ 测试集' }).click();
  await page.waitForTimeout(2500);
  await page.getByText('all_sessions_20260901').click();
  await page.waitForTimeout(3500);
  await page.screenshot({ path: 'work/evaluation-page/design-only-review.png' });
}