import {NextRequest,NextResponse} from 'next/server';
import {paddedLookup,emptyGroupState} from '@/lib/lookup';
import {pool} from '@/lib/db';
import {dataMode,normalizePlate,sourceState} from '@/lib/input';
import type {Group,Source,DataRow} from '@/lib/report';
export const runtime='nodejs';
export const dynamic='force-dynamic';
let total={count:0,until:0};
function permitted(){const now=Date.now();if(now>total.until)total={count:0,until:now+60_000};return ++total.count<=120}
export async function GET(_request:NextRequest,context:{params:Promise<{plate:string}>}){
 if(!permitted())return NextResponse.json({error:'יותר מדי בקשות. נסו שוב בעוד דקה.'},{status:429,headers:{'Retry-After':'60'}});
 const plate=normalizePlate((await context.params).plate);
 if(!plate)return NextResponse.json({error:'יש להזין מספר רישוי בן 7 או 8 ספרות.'},{status:400});
 try{
  const mode=dataMode();const client=await pool.connect();
  try{
   await client.query('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY');
   const sources=(await client.query<Source>(`SELECT id,name,kind,coverage,availability,active_run_id,official_url,updated_at FROM ${mode}.sources`)).rows;
   const plateKinds=['vehicles','statuses','recalls','mileage','ownership'];
   const resolve=async(value:string,alias:boolean)=>{
    const sql=plateKinds.map(kind=>`SELECT n.plate FROM ${mode}.${kind} n JOIN ${mode}.sources s ON s.id=n.source_id AND s.active_run_id=n.run_id WHERE n.plate=$1 AND (NOT $2::boolean OR(s.coverage->>'plate_lookup_format'='zero_padded_8' AND s.coverage->>'plate_lookup_run_id'=s.active_run_id::text))`).join(' UNION ALL ');
    return(await client.query<{plate:string}>(`SELECT plate FROM(${sql}) matches LIMIT 1`,[value,alias])).rows[0]?.plate;
   };
   let matched=await resolve(plate,false);
   let lookupKind:'exact'|'zero_padded_8'|'not_found'=matched?'exact':'not_found';
   const padded=paddedLookup(plate,mode);
   if(!matched&&padded){matched=await resolve(padded,true);if(matched)lookupKind='zero_padded_8'}
   const queryPlate=matched??plate;
   const groups:Record<string,Group>={};
   for(const kind of ['vehicles','specs','ownership','mileage','statuses','recalls',...(mode==='live'?['model_counts']:[])]){
    let rows:DataRow[];
    if(mode==='live'&&(kind==='specs'||kind==='model_counts')){
     const spec=kind==='specs';const links=spec?'spec_links':'model_count_links';
     const targetId=spec?'spec_id':'model_count_id';const targetRun=spec?'spec_run_id':'model_count_run_id';
     const details=spec?`LEFT JOIN ${mode}.record_details d ON d.source_id=n.source_id AND d.run_id=n.run_id AND d.source_record_id=n.source_record_id`:'';
     // EXISTS avoids multiplying one model by multiple vehicle profiles.
     rows=(await client.query<DataRow>(`SELECT n.id::text,n.payload,n.source_id,n.run_id::text,n.source_record_id ${spec?',d.details':''} FROM ${mode}.${kind} n JOIN ${mode}.sources ns ON ns.id=n.source_id AND ns.active_run_id=n.run_id ${details} WHERE EXISTS(SELECT 1 FROM ${mode}.${links} l JOIN ${mode}.vehicles v ON v.id=l.vehicle_id AND v.run_id=l.vehicle_run_id JOIN ${mode}.sources vs ON vs.id=v.source_id AND vs.active_run_id=v.run_id WHERE l.${targetId}=n.id AND l.${targetRun}=n.run_id AND v.plate=$1) ORDER BY n.id LIMIT 501`,[queryPlate])).rows;
    }else if(kind==='specs'){
     rows=(await client.query<DataRow>(`SELECT n.id::text,n.payload,n.source_id,n.run_id::text,n.source_record_id FROM ${mode}.specs n JOIN ${mode}.sources s ON s.id=n.source_id AND s.active_run_id=n.run_id WHERE n.payload->>'spec_key' IN(SELECT v.payload->>'spec_key' FROM ${mode}.vehicles v JOIN ${mode}.sources vs ON vs.id=v.source_id AND vs.active_run_id=v.run_id WHERE v.plate=$1) LIMIT 501`,[queryPlate])).rows;
    }else{
     rows=(await client.query<DataRow>(`SELECT n.id::text,n.payload,n.source_id,n.run_id::text,n.source_record_id FROM ${mode}.${kind} n JOIN ${mode}.sources s ON s.id=n.source_id AND s.active_run_id=n.run_id WHERE n.plate=$1 ORDER BY n.id LIMIT 501`,[queryPlate])).rows;
    }
    if(rows.length>500)throw new Error('Report row limit exceeded');
    const rawCount=rows.length;
    const withheld=kind==='mileage'?rows.filter(r=>!(r.payload.measured_at||r.payload.measurement_date||r.payload.date)).length:0;
    if(kind==='mileage')rows=rows.filter(r=>Boolean(r.payload.measured_at||r.payload.measurement_date||r.payload.date));
    // These are reported quarter markers. A later report is not an exact ownership end date.
    if(kind==='ownership'){
     rows.sort((a,b)=>String(a.payload.ownership_period??a.payload.start_date??'').localeCompare(String(b.payload.ownership_period??b.payload.start_date??'')));
     const periods=[...new Set(rows.map(r=>String(r.payload.ownership_period??'')).filter(Boolean))].sort();
     rows=rows.map(r=>{const p=String(r.payload.ownership_period??'');const next=periods.find(q=>q>p);return next?{...r,payload:{...r.payload,next_reported_period:next}}:r});
    }
    const relevant=sources.filter(s=>s.kind===kind).map(s=>({...s,state:sourceState(s,rows.some(r=>r.source_id===s.id))}));
    const ambiguous=kind==='specs'&&rows.length>1;
    if(ambiguous)rows=[];
    const state=ambiguous?'ambiguous':kind==='vehicles'&&rows.length>1?'multiple_sources':rows.length?(relevant.some(s=>s.state==='stale')?'stale':'available'):kind==='mileage'&&rawCount?'undated':emptyGroupState(relevant);
    groups[kind]={state,rows,sources:relevant,...(kind==='mileage'?{withheld_undated_count:withheld}:{})};
   }
   if(mode==='live'){
    // Same imported row, a separate projection of its reported status flags. No measurement date is inferred.
    const projected=(await client.query<DataRow>(`SELECT n.payload,n.source_id,n.run_id::text,n.source_record_id FROM ${mode}.mileage n JOIN ${mode}.sources s ON s.id=n.source_id AND s.active_run_id=n.run_id WHERE n.plate=$1 ORDER BY n.id LIMIT 501`,[queryPlate])).rows;
    if(projected.length>500)throw new Error('Projection row limit exceeded');
    const statusKeys=['original_usage_description','first_registration_date_raw','source_flag_gapam_ind','source_flag_shinui_mivne_ind','source_flag_shinui_zmig_ind','source_flag_shnui_zeva_ind'];
    const extra=projected.map(r=>({...r,payload:Object.fromEntries(statusKeys.filter(k=>r.payload[k]!==null&&r.payload[k]!==undefined&&r.payload[k]!=='').map(k=>[k,r.payload[k]])),projection:'reported_status_flags'})).filter(r=>Object.keys(r.payload).length>0);
    if(extra.length){
     groups.statuses.rows.push(...extra);
     const additional=sources.filter(s=>extra.some(r=>r.source_id===s.id)).map(s=>({...s,state:sourceState(s,true)}));
     groups.statuses.sources.push(...additional.filter(s=>!groups.statuses.sources.some(existing=>existing.id===s.id)));
     groups.statuses.state='available';
    }
    const recallIds=[...new Set(groups.recalls.rows.map(r=>r.payload.recall_id).filter((id):id is string=>typeof id==='string'))];
    if(recallIds.length){
     const catalog=(await client.query<DataRow>(`SELECT n.payload,n.source_id,n.run_id::text,n.source_record_id FROM ${mode}.recall_catalog n JOIN ${mode}.sources s ON s.id=n.source_id AND s.active_run_id=n.run_id WHERE n.payload->>'recall_id'=ANY($1::text[]) LIMIT 501`,[recallIds])).rows;
     if(catalog.length>500)throw new Error('Catalog row limit exceeded');
     groups.recalls.rows=groups.recalls.rows.map(r=>{const matches=catalog.filter(c=>c.payload.recall_id===r.payload.recall_id);return{...r,catalog:matches.length===1?matches[0]:undefined,catalog_state:matches.length===1?'matched':matches.length?'ambiguous':'not_found'}});
     for(const s of sources.filter(s=>catalog.some(c=>c.source_id===s.id))){if(!groups.recalls.sources.some(existing=>existing.id===s.id))groups.recalls.sources.push({...s,state:sourceState(s,true)})}
    }
   }
   await client.query('COMMIT');
   return NextResponse.json({plate,mode,lookup:{kind:lookupKind,...(matched?{matched_plate:matched}:{})},groups},{headers:{'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
  }catch(error){await client.query('ROLLBACK');throw error}finally{client.release()}
 }catch{return NextResponse.json({error:'שירות הנתונים אינו זמין כעת. אין מעבר אוטומטי לנתוני הדגמה.'},{status:503})}
}
