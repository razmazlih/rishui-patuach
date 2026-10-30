import {expect,test} from '@playwright/test';
import {Pool} from 'pg';
test.skip(process.env.E2E_LIVE !== '1','Explicit live verification only');
let plate='';
let paddedPlate='';
test.beforeAll(async()=>{
 const db=new Pool({connectionString:process.env.DATABASE_URL,max:1});
 try {
  const rows=await db.query("SELECT v.plate FROM live.vehicles v JOIN live.sources s ON s.id=v.source_id AND s.active_run_id=v.run_id WHERE s.id='mot-053cea08-09bc-40ec-8f7a-156f0677aff3' AND EXISTS (SELECT 1 FROM live.recalls r JOIN live.sources rs ON rs.id=r.source_id AND rs.active_run_id=r.run_id WHERE r.plate=v.plate) LIMIT 1");
  if(!rows.rowCount)throw new Error('No verified live vehicle with recall available for E2E');
  plate=rows.rows[0].plate;
  const padded=await db.query("SELECT v.plate FROM live.vehicles v JOIN live.sources s ON s.id=v.source_id AND s.active_run_id=v.run_id WHERE s.id='mot-053cea08-09bc-40ec-8f7a-156f0677aff3' AND v.plate LIKE '0_______' AND substring(v.plate,2,1)<>'0' LIMIT 1");
  if(!padded.rowCount)throw new Error('No existing padded registration available for lookup regression');
  paddedPlate=padded.rows[0].plate;
 }finally{await db.end()}
});
test('live imported vehicle search is correct, isolated and responsive',async({page})=>{
 await page.goto('/');
 await expect(page.locator('html')).toHaveAttribute('dir','rtl');
 await expect(page.locator('form[data-ready="true"]')).toBeVisible();
 await expect(page.getByText('מצב הדגמה — נתונים סינתטיים',{exact:true})).toHaveCount(0);
 await page.getByRole('textbox').fill(plate);
 const responsePromise=page.waitForResponse(r=>r.url().includes('/api/vehicles/'));
 await page.getByRole('button',{name:/בדיקת רכב/}).click();
 const response=await responsePromise;
 expect(response.status()).toBe(200);
 const body=await response.json();
 expect(body.mode).toBe('live');
 expect(body.groups.vehicles.rows.length).toBeGreaterThan(0);
 expect(body.groups.recalls.rows.length).toBeGreaterThan(0);
 expect(Object.values(body.groups).every((g:any)=>g.rows.every((r:any)=>r.source_id.startsWith('mot-')))).toBe(true);
 expect(body.groups.specs.rows).toHaveLength(0);
 expect(body.groups.ownership.rows).toHaveLength(0);
 expect(body.groups.mileage.rows).toHaveLength(0);
 await expect(page.getByRole('heading',{name:`דוח רכב ${plate}`})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 await page.screenshot({path:`data/reports/live-browser-${test.info().project.name}.png`,fullPage:true});
});


test('live seven-digit search matches its verified eight-digit storage representation',async({page})=>{
 const seven=paddedPlate.slice(1);
 const full=await page.request.get(`/api/vehicles/${paddedPlate}`);
 const shortened=await page.request.get(`/api/vehicles/${seven}`);
 expect(full.status()).toBe(200);
 expect(shortened.status()).toBe(200);
 const fullBody=await full.json();
 const shortBody=await shortened.json();
 const identity=(body:any)=>body.groups.vehicles.rows.map((r:any)=>`${r.source_id}:${r.run_id}:${r.source_record_id}`).sort();
 expect(identity(fullBody).length>0).toBe(true);
 expect(JSON.stringify(identity(fullBody))===JSON.stringify(identity(shortBody))).toBe(true);
 expect(shortBody.lookup.kind).toBe('zero_padded_8');
 expect(shortBody.lookup.matched_plate===paddedPlate).toBe(true);
 await page.goto('/');
 await expect(page.locator('form[data-ready="true"]')).toBeVisible();
 await page.getByRole('textbox').fill(`${seven.slice(0,2)}-${seven.slice(2,5)} ${seven.slice(5)}`);
 const responsePromise=page.waitForResponse(r=>r.url().includes('/api/vehicles/'));
 await page.getByRole('button',{name:/בדיקת רכב/}).click();
 const response=await responsePromise;
 expect(response.status()).toBe(200);
 const body=await response.json();
 expect(body.lookup.kind).toBe('zero_padded_8');
 expect(body.groups.vehicles.rows.length>0).toBe(true);
 await expect(page.locator('.report')).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});
