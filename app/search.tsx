'use client';
import ReportExplorer from './report-explorer';
import { useState, useRef, useEffect, useId, type CSSProperties } from 'react';
import {reportLabels,technicalLabel,technicalCategory} from '@/lib/source-labels';
import {formatReportedPeriod} from '@/lib/presentation';
import {normalizePlate} from '@/lib/input';
import {groupNames,stateLabels,type Report,type DataRow,type Group} from '@/lib/report';
const hidden=new Set(['record_id','plate','plate_original','spec_key','source_record_id','verified','match_verified','match_method','date_precision','ownership_date_raw','source_date','source_date_precision']);
function visibleEntries(payload:Record<string,unknown>){return Object.entries(payload).filter(([key])=>!hidden.has(key)&&!key.endsWith('_precision')&&!key.endsWith('_original'))}
function hasValue(value:unknown):boolean{if(value==null)return false;if(typeof value==='string')return value.trim().length>0;if(Array.isArray(value))return value.some(hasValue);if(typeof value==='object')return Object.values(value).some(hasValue);return true}
function hasInformation(row:DataRow){return visibleEntries(row.payload).some(([,value])=>hasValue(value))||Boolean(row.details&&visibleEntries(row.details).some(([,value])=>hasValue(value)))||Boolean(row.catalog&&visibleEntries(row.catalog.payload).some(([,value])=>hasValue(value)))}
type IconName='car'|'calendar'|'fuel'|'engine'|'palette'|'users'|'gauge'|'shield'|'activity'|'layers'|'tag'|'info';
const iconPaths:Record<IconName,string>={
 car:'M5 17H3v-6l2-6h14l2 6v6h-2M5 17h14M5 17v3M19 17v3M3 11h18M7 14h.01M17 14h.01',
 calendar:'M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14H3V6a2 2 0 0 1 2-2M7 14h3M14 14h3',
 fuel:'M3 21V4h10v17M2 21h12M5 7h6M13 12h2a2 2 0 0 1 2 2v3a2 2 0 0 0 4 0V8l-4-4M18 5v4h3',
 engine:'M7 7h10v3h3v8H7l-4-4v-4h4V7M10 3h5M12 3v4M3 10H1M1 8v8',
 palette:'M12 3a9 9 0 1 0 0 18h1a2 2 0 0 0 0-4h-1a2 2 0 0 1 0-4h5a4 4 0 0 0 4-4c0-4-5-6-9-6M7 8h.01M12 6h.01M17 8h.01M6 13h.01',
 users:'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-4M17 3a4 4 0 0 1 0 8',
 gauge:'M4 19a10 10 0 1 1 16 0M12 13l5-5M7 9l1 1M5 14h2M12 4v2M17 14h2M10 17h4',
 shield:'M12 2l9 4v6c0 5-9 10-9 10S3 17 3 12V6l9-4M12 8v5M12 17h.01',
 activity:'M2 12h5l3-8 4 16 3-8h5',
 layers:'M12 3l10 5-10 5L2 8l10-5M2 12l10 5 10-5M2 16l10 5 10-5',
 tag:'M3 3h8l10 10-8 8L3 11V3M7 7h.01',
 info:'M12 8h.01M12 11v6M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0'
};
function Icon({name}:{name:IconName}){return <svg className="report-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={iconPaths[name]}/></svg>}
const groupIcons:Record<string,IconName>={vehicles:'car',specs:'engine',ownership:'users',mileage:'gauge',statuses:'activity',recalls:'shield',model_counts:'layers'};
const groupTitles:Record<string,string>={vehicles:'פרטי הרכב',specs:'מנוע, ביצועים ואבזור',ownership:'היסטוריית בעלות',mileage:'נסועה מתועדת',statuses:'רישומים ושינויים',recalls:'קריאות לתיקון',model_counts:'עוד על הדגם'};
const groupOrder=['vehicles','specs','ownership','mileage','statuses','recalls','model_counts'];
const fieldOrder=['manufacturer','commercial_name','model','year','manufacture_year','trim','vehicle_type','color','fuel','fuel_type','license_valid_until','test_valid_until','last_test','test_date','registration_date','first_registration_date_raw','current_ownership_type','ownership_type','owner_type','engine_cc','engine_volume_raw','power_hp','power_kw','transmission','automatic_transmission_flag_raw','drive_type','seats','doors'];
function fieldIcon(key:string):IconName{
 if(/date|until|year|period|announced|last_test/.test(key))return 'calendar';
 if(/fuel|delek|gapam/.test(key))return 'fuel';
 if(/color|zeva/.test(key))return 'palette';
 if(/ownership|owner/.test(key))return 'users';
 if(/kilometer|odometer|^km$|measurement/.test(key))return 'gauge';
 if(/engine|power|transmission|drive|gearbox|manoa|koah|hanaa/.test(key))return 'engine';
 if(/recall|fault|resolved|safety|betih|blim/.test(key))return 'shield';
 if(/manufacturer|commercial_name|model|trim|vehicle_type/.test(key))return 'car';
 if(/code|^type$/.test(key))return 'tag';
 if(/count/.test(key))return 'layers';
 return 'info';
}
function display(value:unknown){if(value==null||value==='')return 'לא נמסר';if(typeof value==='boolean')return value?'כן':'לא';if(typeof value==='object')return JSON.stringify(value);return String(value)}
const repeatedIdentity=new Set(['manufacturer','commercial_name','model','year','manufacture_year','trim','fuel','fuel_type']);
function internalField(key:string){return key.endsWith('_code')||key==='model_type'}
function Fields({payload,technical=false,includeInternal=false}:{payload:Record<string,unknown>;technical?:boolean;includeInternal?:boolean}){
 const entries=visibleEntries(payload).filter(([key,value])=>hasValue(value)&&(includeInternal||!internalField(key))).sort(([a],[b])=>{const ia=fieldOrder.indexOf(a),ib=fieldOrder.indexOf(b);return (ia<0?100:ia)-(ib<0?100:ib)});
 return <dl className="report-fields">{entries.map(([key,value],index)=><div className="report-field" key={key} style={{'--field-index':Math.min(index,12)} as CSSProperties}><dt><span className="field-icon"><Icon name={fieldIcon(key)}/></span><span className="field-content">{technical?technicalLabel(key):reportLabels[key]??`נתון מקור: ${key}`}</span></dt><dd dir="auto">{key==='ownership_period'||key==='next_reported_period'?formatReportedPeriod(value):display(value)}</dd></div>)}</dl>;
}
function FullSpecification({details}:{details:Record<string,unknown>}){
 const categories:Record<string,Record<string,unknown>>={};
 const order=['מנוע, הנעה, מידות ומבנה','בטיחות ואבזור','פליטות ונתוני סביבה','זיהוי דגם ופרטים נוספים'];
 for(const [key,value] of visibleEntries(details)){const category=technicalCategory(key);(categories[category]??={})[key]=value}
 return <div className="full-spec"><p className="small-note">מפרט הגרסה הותאם לפי קודי תוצר ודגם, סוג דגם ושנה. החיוויים הם ערכי המקור; מידע חסר אינו מעיד שאביזר אינו קיים.</p>{Object.entries(categories).filter(([,fields])=>Object.values(fields).some(hasValue)).sort(([a],[b])=>order.indexOf(a)-order.indexOf(b)).map(([title,fields])=><details className="sources" key={title}><summary>{title}</summary><Fields payload={fields} technical/></details>)}</div>;
}
function Row({row,kind,sourceName,multipleProfiles=false,vehicleRows=[]}:{row:DataRow;kind:string;sourceName?:string;multipleProfiles?:boolean;vehicleRows?:DataRow[]}){
 const quarter=kind==='ownership'&&typeof row.payload.ownership_period==='string';
 const payload=Object.fromEntries(Object.entries(row.payload).filter(([key,value])=>{
  if(quarter&&(key==='ownership_period'||key==='next_reported_period'))return false;
  if((kind==='specs'||kind==='model_counts')&&repeatedIdentity.has(key)&&hasValue(value)){
   const identities=vehicleRows.map(vehicle=>vehicle.payload[key]).filter(hasValue);
   if(identities.length>0&&identities.every(identity=>Object.is(identity,value)))return false;
  }
  return true;
 }));
 return <div className={kind==='ownership'?'timeline-row':kind==='vehicles'?'data-row report-profile':'data-row'}>
  {multipleProfiles&&<h4 className="profile-source">{sourceName??'רשומת זיהוי במקור'}</h4>}
  {quarter&&<div className="ownership-marker"><strong>{formatReportedPeriod(row.payload.ownership_period)}</strong></div>}
  <Fields payload={payload}/>
  {quarter&&<p className="small-note">{row.payload.next_reported_period?`דיווח מאוחר יותר: ${formatReportedPeriod(row.payload.next_reported_period)}. מועדי הדיווח אינם תאריכי מעבר בעלות מדויקים.`:'מועד הדיווח ברמת רבעון. אין דיווח מאוחר יותר במקור ואין בכך אישור לבעלות כיום.'}</p>}
  {row.projection==='reported_status_flags'&&<p className="small-note">חיוויים כפי שנמסרו במקור. מועד הרישום הראשון אינו מועד המדידה או השינוי.</p>}
  {kind==='specs'&&row.details&&<FullSpecification details={row.details}/>}
  {row.catalog&&<details className="sources"><summary>פרטי קריאת היצרן ואופן התיקון</summary><Fields payload={row.catalog.payload}/></details>}
  {kind==='recalls'&&row.catalog_state==='not_found'&&<p className="small-note">לא נמצאה הרחבה יחידה לרשומת הריקול בקטלוג היצרן.</p>}
 </div>;
}
function OwnershipTimeline({group}:{group:Group}){
 const [selected,setSelected]=useState(0);
 const stops=useRef<(HTMLButtonElement|null)[]>([]);
 const detailId=useId();
 const selectedIndex=Math.min(selected,Math.max(0,group.rows.length-1));
 const current=group.rows[selectedIndex];
 if(!current)return null;
 function select(index:number,focus=false){
  setSelected(index);
  const stop=stops.current[index];
  if(focus)stop?.focus({preventScroll:true});
  stop?.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'nearest',inline:'nearest'});
 }
 function ownerLabel(row:DataRow){return display(row.payload.ownership_type??row.payload.owner_type??row.payload.current_ownership_type??'סוג בעלות לא נמסר')}
 return <div className="ownership-explorer">
  <p className="ownership-instruction">בחרו דיווח כדי לגלות מה נרשם על הבעלות באותו מועד.</p>
  <div className="ownership-track" role="group" aria-label="בחירת דיווח בעלות" style={{'--ownership-progress':`${group.rows.length>1?selectedIndex/(group.rows.length-1)*100:0}%`} as CSSProperties}>
   {group.rows.map((row,index)=><button type="button" key={`${row.source_id}-${row.run_id}-${row.source_record_id}-${index}`} ref={element=>{stops.current[index]=element}} className={`ownership-stop${index===selectedIndex?' is-selected':''}`} aria-pressed={index===selectedIndex} aria-controls={detailId} onClick={()=>select(index)} onKeyDown={event=>{
    let target:number|undefined;
    if(event.key==='ArrowLeft')target=Math.min(index+1,group.rows.length-1);
    if(event.key==='ArrowRight')target=Math.max(index-1,0);
    if(event.key==='Home')target=0;
    if(event.key==='End')target=group.rows.length-1;
    if(target!==undefined){event.preventDefault();select(target,true)}
   }}>
    <span className="ownership-stop-dot" aria-hidden="true"><Icon name="users"/></span>
    <strong>{hasValue(row.payload.ownership_period)?formatReportedPeriod(row.payload.ownership_period):'מועד לא נמסר'}</strong>
    <span>{ownerLabel(row)}</span>
    <small>דיווח {index+1}</small>
   </button>)}
  </div>
  <div className="ownership-detail" id={detailId} role="region" aria-label={`פרטי דיווח בעלות ${selectedIndex+1}`}>
   <p className="ownership-selection" role="status">דיווח {selectedIndex+1} מתוך {group.rows.length} · {ownerLabel(current)}</p>
   <Row row={current} kind="ownership" sourceName={group.sources.find(source=>source.id===current.source_id)?.name}/>
   <p className="small-note">מקור הדיווח: {group.sources.find(source=>source.id===current.source_id)?.name??current.source_id}</p>
  </div>
 </div>;
}
function Section({kind,group,vehicleRows,index}:{kind:string;group:Group;vehicleRows:DataRow[];index:number}){
 return <section className={`report-part report-part-${kind}`} style={{'--report-index':index} as CSSProperties} id={`report-${kind}`} aria-labelledby={`heading-${kind}`}><div className="report-part-heading"><h3 id={`heading-${kind}`}><Icon name={groupIcons[kind]??'info'}/>{groupTitles[kind]??groupNames[kind]}</h3></div>
  {kind==='model_counts'&&<p className="small-note">ספירות מצרפיות של כלי רכב מאותו דגם במקור; אינן מידע על בעלי הרכב או על היסטוריית הרכב המסוים.</p>}
  {group.state==='multiple_sources'&&<p className="small-note">נמצאו כמה רשומות זיהוי. כל אחת מוצגת עם המקור שלה כדי לשמור על ההבדלים בדיווח.</p>}
  {group.state!=='available'&&group.state!=='multiple_sources'&&<p className="small-note">{stateLabels[group.state]??group.state}</p>}
  {kind==='ownership'?<OwnershipTimeline group={group}/>:<div>{group.rows.map((row,i)=><Row key={`${row.source_id}-${row.run_id}-${row.source_record_id}-${i}`} row={row} kind={kind} vehicleRows={vehicleRows} multipleProfiles={kind==='vehicles'&&group.rows.length>1} sourceName={group.sources.find(s=>s.id===row.source_id)?.name}/>)}</div>}
  {kind==='mileage'&&Boolean(group.withheld_undated_count)&&<p className="small-note">{group.withheld_undated_count} רשומות ללא מועד מדידה ידוע אינן מוצגות כמדידה מתוארכת.</p>}
  {kind==='ownership'&&<p className="small-note">רישומים חוזרים נשמרו. מספר הרישומים אינו מספר ה״ידיים״.</p>}
  {kind==='recalls'&&<p className="small-note">רק התאמות מאומתות למספר הרכב מוצגות. היעדר רשומה אינו אישור שאין ריקול.</p>}
 </section>;
}
function SourceNotes({groups}:{groups:[string,Group][]}){
 return <details className="report-support sources"><summary><Icon name="info"/>מקורות המידע, כיסוי ופרטי הדיווח</summary>{groups.map(([kind,group])=><div key={kind}><h4>{groupNames[kind]}</h4>{group.sources.map(s=><div key={s.id}><strong>{s.name}</strong><p>{stateLabels[s.state]} · עדכון מערכת: <bdi>{new Date(s.updated_at).toLocaleDateString('he-IL')}</bdi></p><p className="small-note">כיסוי: {display(s.coverage.description??s.coverage.scope??'לא פורט')} · מועד הנתונים במקור: {display(s.coverage.as_of)}</p>{Boolean(s.coverage.quarantine_note)&&<p className="small-note">{display(s.coverage.quarantine_note)}</p>}{Boolean(s.coverage.import_note)&&<p className="small-note">{display(s.coverage.import_note)}</p>}{s.official_url&&<a href={s.official_url} rel="noreferrer" target="_blank">מקור רשמי</a>}</div>)}{group.rows.map((row,i)=><div className="lineage" key={`${row.source_id}-${i}`}>מקור: {row.source_id} · ריצה {row.run_id} · רשומה {row.source_record_id}{row.catalog&&<> · קטלוג: {row.catalog.source_id} · ריצה {row.catalog.run_id} · רשומה {row.catalog.source_record_id}</>}<details className="record-source"><summary>כל פרטי הרשומה במקור</summary><Fields payload={row.payload} includeInternal/>{row.details&&<Fields payload={row.details} technical includeInternal/>}{row.catalog&&<Fields payload={row.catalog.payload} includeInternal/>}</details>{visibleEntries(row.payload).some(([,value])=>!hasValue(value))&&<p>שדות שלא נמסרו: {visibleEntries(row.payload).filter(([,value])=>!hasValue(value)).map(([key])=>reportLabels[key]??key).join('، ')}</p>}</div>)}</div>)}</details>;
}
function CoverageSummary({groups}:{groups:[string,Group][]}){
 if(!groups.length)return null;
 return <details className="coverage-summary"><summary>מידע שלא מוצג בדוח · {groups.length} תחומים</summary><p className="small-note">מוצגים בדוח רק הנתונים שנמצאו במקורות הזמינים. היעדר מידע אינו מעיד על מצב הרכב.</p><ul className="coverage-list">{groups.map(([kind,group])=><li key={kind}><strong>{groupNames[kind]}</strong><span>{stateLabels[group.state]}</span>{Boolean(group.withheld_undated_count)&&<span>{group.withheld_undated_count} רשומות ללא מועד מדידה ידוע</span>}{group.sources.map(source=><span key={source.id}>{source.name} · {stateLabels[source.state]}{source.coverage.quarantine_note?` · ${display(source.coverage.quarantine_note)}`:''}{source.coverage.import_note?` · ${display(source.coverage.import_note)}`:''}</span>)}</li>)}</ul></details>
}
export default function Search({mode}:{mode:'demo'|'live'}){
 const [ready,setReady]=useState(false);
 useEffect(()=>setReady(true),[]);
 const [input,setInput]=useState('');
 const [loading,setLoading]=useState(false);
 const [error,setError]=useState('');
 const [report,setReport]=useState<Report|null>(null);
 const result=useRef<HTMLDivElement>(null);
 useEffect(()=>{if(!report)return;const frame=requestAnimationFrame(()=>{result.current?.focus({preventScroll:true});result.current?.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'})});return()=>cancelAnimationFrame(frame)},[report]);
 const groups=report?Object.entries(report.groups).map(([kind,group])=>[kind,{...group,rows:group.rows.filter(hasInformation)}] as [string,Group]).sort(([a],[b])=>{const ia=groupOrder.indexOf(a),ib=groupOrder.indexOf(b);return (ia<0?100:ia)-(ib<0?100:ib)}):[];
 const available=groups.filter(([,group])=>group.rows.length>0);
 const unavailable=groups.filter(([,group])=>!group.rows.length);
 async function submit(e:React.FormEvent){
  e.preventDefault();if(loading)return;const plate=normalizePlate(input);setError('');setReport(null);
  if(!plate){setError('יש להזין מספר רישוי בן 7 או 8 ספרות. אפשר לכלול רווחים ומקפים.');return}
  setLoading(true);
  try{const response=await fetch(`/api/vehicles/${encodeURIComponent(plate)}`,{cache:'no-store'});const data=await response.json();if(!response.ok)throw new Error(data.error||'לא ניתן להשלים את החיפוש כרגע.');if(data.mode!==mode)throw new Error('מצב הנתונים השתנה. יש לרענן את העמוד.');setReport(data)}catch(err){setError(err instanceof Error?err.message:'תקלה בחיבור לשירות. נסו שוב.')}finally{setLoading(false)}
 }
 return <>
  <form className="search-box" data-ready={ready} onSubmit={submit} aria-busy={loading}>
   <div className="search-label-row"><label htmlFor="plate">מתחילים עם מספר הרכב</label><span className="search-security">ללא הרשמה · ללא תשלום</span></div>
   <div className="search-controls"><div className="plate-input"><span className="plate-strip" aria-hidden="true">IL</span><input id="plate" name="plate" aria-label="מספר רישוי" disabled={!ready} aria-invalid={Boolean(error)} aria-describedby={error?'input-help search-error':'input-help'} inputMode="numeric" autoComplete="off" maxLength={32} placeholder="מספר הרכב שלך" value={input} onChange={e=>{setInput(e.target.value);if(error)setError('')}} dir="ltr"/></div><button type="submit" disabled={loading||!ready}>{loading?'מחפשים…':'בדיקת רכב'}<span aria-hidden="true">{loading?'◌':'←'}</span></button></div>
   <p id="input-help">7 או 8 ספרות · אפשר להקליד עם רווחים או מקפים</p>
   {mode==='demo'&&<p className="demo-hint">רוצים לנסות? <button type="button" className="example" disabled={loading} onClick={()=>{setInput('01234567');document.getElementById('plate')?.focus()}}>01234567</button> — מספר סינתטי לדוגמה</p>}
   <div aria-live="polite">{loading&&<p className="loading">מחפשים את המידע הזמין על הרכב…</p>}{error&&<p id="search-error" className="error" role="alert">{error}</p>}</div>
  </form>
  {report&&<div className="report" ref={result} tabIndex={-1} aria-label={`תוצאות בדיקת רכב ${report.plate}`}>
   <div className="report-overview"><div className="report-heading"><div><span className="eyebrow">המידע שמאחורי המספר</span><h2>דוח רכב <bdi>{report.plate}</bdi></h2></div><span className="report-mode">{report.mode==='demo'?'נתונים סינתטיים':'נתונים מהמאגר המקומי'}</span></div>
   <p className="report-note">כל המידע שנמצא על הרכב, במקום אחד. פרטי המקורות ומידע שאינו זמין מופיעים בסוף הדוח.</p>
   </div>
   {available.length>0?<div className="report-flow"><ReportExplorer key={report.plate} report={report}/>{available.map(([kind,group],index)=><Section index={index} key={kind} kind={kind} group={group} vehicleRows={report.groups.vehicles?.rows??[]}/>)}</div>:<div className="report-empty" role="status"><h3>עדיין אין מידע זמין להצגה</h3><p>לא נמצאו נתונים שניתן להציג למספר הרישוי הזה במקורות הזמינים. אפשר לבדוק את הכיסוי בהמשך, או לחפש מספר אחר.</p></div>}
   {available.length>0&&<SourceNotes groups={available}/>}
   <CoverageSummary groups={unavailable}/>
   <p className="report-note">מועדים מוצגים בדיוק שבו דווחו: רבעון, חודש או יום. מספר רישומי בעלות אינו מספר ה״ידיים״. הדוח אינו מחליף בדיקת רכב מקצועית.</p>
  </div>}
 </>
}
