/** Capture the real local UI with the repository's synthetic demo only. */
import { chromium } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const base = new URL(process.env.SCREENSHOT_BASE_URL || 'http://127.0.0.1:3000');
if (!['localhost', '127.0.0.1', '[::1]'].includes(base.hostname)) {
  throw new Error('Documentation captures must use a local demo server.');
}
const output = fileURLToPath(new URL('../docs/screenshots/', import.meta.url));
const browser = await chromium.launch(process.env.SCREENSHOT_CHROMIUM_PATH
  ? { executablePath: process.env.SCREENSHOT_CHROMIUM_PATH }
  : {});

try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 1,
    reducedMotion: 'reduce',
  });
  // Check the data mode before saving any image. Never capture a live report.
  const probe = await page.request.get(new URL('/api/vehicles/01234567', base).href);
  const demo = await probe.json();
  if (probe.status() !== 200 || demo.mode !== 'demo' || demo.plate !== '01234567'
      || demo.groups?.vehicles?.rows?.length !== 1) {
    throw new Error('Load the synthetic fixtures in DATA_MODE=demo before capturing.');
  }
  await page.goto(base.href);
  await page.locator('form[data-ready="true"]').waitFor();
  await page.getByText('מצב הדגמה — נתונים סינתטיים', { exact: true }).waitFor();
  await page.evaluate(() => document.fonts.ready);
  await mkdir(output, { recursive: true });
  await page.screenshot({ path: output + '01-search.png' });

  await page.getByRole('button', { name: '01234567', exact: true }).click();
  const responsePromise = page.waitForResponse(r => r.url().includes('/api/vehicles/'));
  await page.getByRole('button', { name: 'בדיקת רכב' }).click();
  const response = await responsePromise;
  const report = await response.json();
  if (response.status() !== 200 || report.mode !== 'demo' || report.plate !== '01234567') {
    throw new Error('The search did not return the expected synthetic report.');
  }
  await page.getByRole('heading', { name: 'דוח רכב 01234567' }).waitFor();
  await page.locator('.vehicle-explorer').waitFor();
  await page.locator('.report-overview').scrollIntoViewIfNeeded();
  const reportClip = await page.evaluate(() => {
    const report = document.querySelector('.report').getBoundingClientRect();
    const explorer = document.querySelector('.vehicle-explorer').getBoundingClientRect();
    return { x: report.x + scrollX, y: report.y + scrollY,
      width: report.width, height: explorer.bottom - report.y + 20 };
  });
  await page.screenshot({ path: output + '02-report.png', clip: reportClip, fullPage: true });
  await page.locator('#report-ownership').screenshot({ path: output + '03-ownership.png' });

  const sources = page.locator('details.report-support');
  await sources.locator(':scope > summary').click();
  await sources.locator('.record-source').first().locator('summary').click();
  const sourceClip = await sources.evaluate(element => {
    const all = element.getBoundingClientRect();
    const first = element.querySelector(':scope > div').getBoundingClientRect();
    return { x: all.x + scrollX, y: all.y + scrollY,
      width: all.width, height: first.bottom - all.y + 24 };
  });
  await page.screenshot({ path: output + '04-sources.png', clip: sourceClip, fullPage: true });
  console.log('Saved four local synthetic-demo screenshots in docs/screenshots/.');
} finally {
  await browser.close();
}
