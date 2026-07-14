// Kiểm tra M4.5 trên UI thật (Chromium headless, engine fake).
const { chromium } = require('playwright-core');

const EP = process.argv[2];  // đường dẫn ep-dir đã import (server chạy VO_STUDIO_ENGINE=fake)
let passed = 0;
function check(cond, label) {
  if (!cond) { console.log('  FAIL:', label); process.exit(1); }
  passed++; console.log('  ok:', label);
}

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
    args: ['--autoplay-policy=no-user-gesture-required', '--no-sandbox'],
  });
  const page = await browser.newPage();
  const errors = [];
  let lastDialog = null;
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  page.on('dialog', (d) => { lastDialog = d.message(); d.dismiss(); });

  await page.goto('http://127.0.0.1:8000/');
  await page.fill('#ep-input', EP);
  await page.click('#btn-open');
  await page.waitForSelector('.line-item');
  check((await page.$$('.line-item')).length === 2, 'rail có 2 line');
  check((await page.$$('.fragment')).length === 2, 'line 1 có 2 fragment');

  // generate cả line -> badge gen per-fragment rồi take xuất hiện
  await page.click('text=↻ Gen fragment thiếu');
  await page.waitForFunction(() => document.querySelectorAll('.take').length >= 2, null, { timeout: 15000 });
  check(true, 'generate xong — take hiện ra');

  // phím tắt: ↓ focus fragment đầu
  await page.keyboard.press('ArrowDown');
  check(await page.$('.fragment.focused'), '↓ tạo focus fragment');
  const fid1 = await page.$eval('.fragment.focused', (e) => e.dataset.fid);

  // M: đánh dấu fragment focus -> badge + nút gen đánh dấu
  await page.keyboard.press('m');
  check(await page.$('.fragment.marked'), 'M đánh dấu fragment');
  check(await page.$eval('#btn-gen-marked', (e) => !e.classList.contains('hidden') && e.textContent.includes('(1)')),
    'nút "Gen đánh dấu (1)" hiện');
  await page.keyboard.press('m');
  check(!(await page.$('.fragment.marked')), 'M lần 2 bỏ đánh dấu');

  // 1/2: chọn take theo phím (cần 2 take -> gen thêm 1 lần cho fragment focus)
  await page.keyboard.press('Enter');
  await page.waitForFunction((fid) =>
    document.querySelectorAll(`.fragment[data-fid="${fid}"] .take`).length === 2, fid1, { timeout: 15000 });
  await page.keyboard.press('1');
  await page.waitForFunction((fid) => {
    const takes = document.querySelectorAll(`.fragment[data-fid="${fid}"] .take`);
    return takes[0]?.classList.contains('selected');
  }, fid1, { timeout: 5000 });
  check(true, 'phím 1 chọn take thứ nhất');
  await page.keyboard.press('2');
  await page.waitForFunction((fid) => {
    const takes = document.querySelectorAll(`.fragment[data-fid="${fid}"] .take`);
    return takes[1]?.classList.contains('selected');
  }, fid1, { timeout: 5000 });
  check(true, 'phím 2 chọn take thứ hai');

  // M5 — A/B toggle: nút hiện khi đủ 2 take, phím A phát và highlight take
  check(await page.$(`.fragment[data-fid="${fid1}"] button:has-text("A/B")`), 'nút A/B hiện khi có 2 take');
  await page.keyboard.press('a');
  await page.waitForSelector('.take.ab-playing', { timeout: 5000 });
  check(true, 'phím A phát A/B — take được highlight');
  await page.waitForFunction(() => !document.querySelector('.take.ab-playing'), null, { timeout: 15000 });
  check(true, 'A/B phát xong tự tắt highlight');

  // M5 — confirm phá hủy: Gộp dưới khi có take -> dialog, dismiss -> không đổi
  lastDialog = null;
  await page.click(`.fragment[data-fid="${fid1}"] button:has-text("Gộp dưới")`);
  check(lastDialog && lastDialog.includes('XÓA'), 'gộp fragment có take -> hỏi confirm');
  check((await page.$$('.fragment')).length === 2, 'dismiss confirm -> không gộp');

  // M5 — gen stale: sửa text -> nút topbar "Gen stale (n)" hiện
  await page.fill(`.fragment[data-fid="${fid1}"] .frag-text`, 'Text hoàn toàn mới.');
  await page.click('h2'); // blur -> save
  await page.waitForFunction(() =>
    !document.getElementById('btn-gen-stale').classList.contains('hidden'), null, { timeout: 5000 });
  check(await page.$eval('#btn-gen-stale', (e) => e.textContent.includes('(1)')), 'nút Gen stale (1) hiện sau sửa text');
  check(await page.$eval('#btn-reimport', (e) => !e.disabled), 'nút Re-import bật khi có project');

  // nghe cả line: playing class + nút đổi nhãn, Space pause
  await page.click('#btn-play-line');
  await page.waitForSelector('.fragment.playing', { timeout: 5000 });
  check(true, 'nghe line — có fragment.playing');
  check(await page.$eval('#btn-play-line', (e) => e.textContent.includes('Dừng')), 'nút đổi thành Dừng');
  await page.keyboard.press(' ');
  check(await page.$eval('#btn-play-line', (e) => e.textContent.includes('Nghe line')), 'Space tạm dừng — nhãn về Nghe line');
  await page.keyboard.press(' ');   // resume
  // chờ playlist phát hết 2 fragment (fake wav ngắn) -> tự dừng
  await page.waitForFunction(() => !document.querySelector('.fragment.playing'), null, { timeout: 20000 });
  check(true, 'playlist phát hết rồi tự dừng');

  // →: chuyển line 2
  await page.keyboard.press('ArrowRight');
  await page.waitForFunction(() =>
    document.querySelector('.line-item.active')?.textContent.includes('Line 2'), null, { timeout: 5000 });
  check(true, '→ chuyển sang line 2');
  check((await page.$$('.fragment')).length === 3, 'line 2 có 3 fragment');

  check(errors.length === 0, 'không có lỗi JS trên trang' + (errors.length ? ' — ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(`\n[m45_check] PASS — ${passed} kiểm tra`);
})().catch((e) => { console.error('FAIL:', e.message); process.exit(1); });
