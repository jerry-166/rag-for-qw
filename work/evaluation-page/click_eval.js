async page => {
  await page.getByRole("link", { name: "☑ 测试集" }).click();
  await page.waitForTimeout(2500);
  await page.getByText("all_sessions_20260901").click();
  await page.waitForTimeout(3500);
  await page.screenshot({ path: "work/evaluation-page/design-scroll-20.png" });
}
