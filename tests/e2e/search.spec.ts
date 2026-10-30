import { expect, test } from '@playwright/test';

const plate = process.env.E2E_PLATE || '01234567';

test('Hebrew search uses imported PostgreSQL data and has responsive RTL layout', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('form[data-ready="true"]')).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await expect(page.getByRole('heading', { name: 'בדיקת רכב לפי מספר רישוי' })).toBeVisible();
  await expect(page.getByText('מצב הדגמה — נתונים סינתטיים', { exact: true })).toBeVisible();
  const input = page.getByRole('textbox');
  await expect(input).toHaveAttribute('inputmode', 'numeric');
  await input.fill(`${plate.slice(0, 2)}-${plate.slice(2, 5)} ${plate.slice(5)}`);
  const responsePromise = page.waitForResponse(r => r.url().includes('/api/vehicles/') && r.request().method() === 'GET');
  await page.getByRole('button', { name: /חיפוש|בדיקת רכב|חפש/ }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const data = await response.json();
  expect(JSON.stringify(data)).toContain(plate);
  await expect(page.getByRole('heading', { name: `דוח רכב ${plate}` })).toBeVisible();
  expect(data.groups.ownership.rows.length).toBeGreaterThanOrEqual(2);
  expect(data.groups.recalls.rows.length).toBeGreaterThanOrEqual(2);
  expect(data.groups.vehicles.rows.length).toBe(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `data/reports/browser-${test.info().project.name}.png`, fullPage: true });
});

test('invalid and absent records are handled without claiming a clean car', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('form[data-ready="true"]')).toBeVisible();
  await page.getByRole('textbox').fill('123');
  await page.getByRole('button', { name: /חיפוש|בדיקת רכב|חפש/ }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'יש להזין מספר רישוי' })).toBeVisible();
  const response = await page.request.get('/api/vehicles/99999999');
  expect([200, 404]).toContain(response.status());
  const text = await response.text();
  expect(text).not.toContain('הרכב תקין');
  expect(text).not.toContain('אין תאונות');
  const invalid = await page.request.get('/api/vehicles/123');
  expect(invalid.status()).toBe(400);
});
