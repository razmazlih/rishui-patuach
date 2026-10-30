import { NextRequest, NextResponse } from 'next/server';
import { pool } from '@/lib/db';
import { dataMode, normalizePlate, sourceState } from '@/lib/input';
import type { Group, Source, DataRow } from '@/lib/report';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
// Bounded process-wide limiter. No persistent or identifiable search logs.
let total = {count:0,until:0};
function permitted() {
  const now = Date.now();
  if (now > total.until) total = {count:0,until:now+60_000};
  return ++total.count <= 120;
}
export async function GET(_request: NextRequest, context: {params: Promise<{plate:string}>}) {
  if (!permitted()) return NextResponse.json({error:'יותר מדי בקשות. נסו שוב בעוד דקה.'},{status:429,headers:{'Retry-After':'60'}});
  const plate = normalizePlate((await context.params).plate);
  if (!plate) return NextResponse.json({error:'יש להזין מספר רישוי בן 7 או 8 ספרות.'},{status:400});
  try {
    const mode = dataMode();
    const client = await pool.connect();
    try {
      await client.query('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY');
      const sources = (await client.query<Source>(`SELECT id,name,kind,coverage,availability,active_run_id,official_url,updated_at FROM ${mode}.sources`)).rows;
      const groups: Record<string,Group> = {};
      for (const kind of ['vehicles','specs','ownership','mileage','statuses','recalls']) {
        let rows = (await client.query<DataRow>(kind === 'specs' ?
          `SELECT n.payload,n.source_id,n.run_id::text,n.source_record_id FROM ${mode}.specs n JOIN ${mode}.sources s ON s.id=n.source_id AND s.active_run_id=n.run_id WHERE n.payload->>'spec_key' IN (SELECT v.payload->>'spec_key' FROM ${mode}.vehicles v JOIN ${mode}.sources vs ON vs.id=v.source_id AND vs.active_run_id=v.run_id WHERE v.plate=$1) LIMIT 501` :
          `SELECT n.payload,n.source_id,n.run_id::text,n.source_record_id FROM ${mode}.${kind} n JOIN ${mode}.sources s ON s.id=n.source_id AND s.active_run_id=n.run_id WHERE n.plate=$1 ORDER BY n.id LIMIT 501`,[plate])).rows;
        const ambiguous = kind === 'specs' && rows.length > 1;
        if (ambiguous) rows = [];
        const withheld_undated_count = kind === 'mileage' ? rows.filter(r => !(r.payload.measured_at || r.payload.measurement_date || r.payload.date)).length : 0;
        if (kind === 'mileage') rows = rows.filter(r => Boolean(r.payload.measured_at || r.payload.measurement_date || r.payload.date));
        const relevant = sources.filter(s=>s.kind===kind).map(s=>({...s,state:sourceState(s,rows.some(r=>r.source_id===s.id))}));
        const state = ambiguous ? 'ambiguous' : relevant.length === 0 ? 'not_loaded' : rows.length ? (relevant.some(s=>s.state==='stale')?'stale':'available') : relevant.some(s=>s.state==='unavailable')?'unavailable':relevant.some(s=>s.state==='not_loaded')?'not_loaded':relevant.every(s=>s.state==='not_covered')?'not_covered':'not_found';
        if (rows.length > 500) throw new Error('Report row limit exceeded');
        groups[kind] = {state,rows,sources:relevant,...(kind === 'mileage' ? {withheld_undated_count} : {})};
      }
      await client.query('COMMIT');
      return NextResponse.json({plate,mode,groups},{headers:{'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
    } catch (error) { await client.query('ROLLBACK'); throw error; }
    finally {client.release();}
  } catch {
    return NextResponse.json({error:'שירות הנתונים אינו זמין כעת. אין מעבר אוטומטי לנתוני הדגמה.'},{status:503});
  }
}
