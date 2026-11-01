'use client';
import { useState, useRef, useEffect } from 'react';
import {reportLabels,technicalLabel,technicalCategory} from '@/lib/source-labels';
import {formatReportedPeriod} from '@/lib/presentation';
import {normalizePlate} from '@/lib/input';
import {groupNames,stateLabels,type Report,type DataRow,type Group} from '@/lib/report';
const hidden=new Set(['record_id','plate','plate_original','spec_key','source_record_id','verified','match_verified','match_method','date_precision','ownership_date_raw','source_date','source_date_precision']);
function display(value:unknown){if(value===null||value==='')return 'לא נמסר';if(typeof value==='boolean')return value?'כן':'לא';if(typeof value==='object')return JSON.stringify(value);return String(value)}
function Fields({payload,technical=false}:{payload:Record<string,unknown>;technical?:boolean}){
 const entries=Object.entries(payload).filter(([key])=>!hidden.has(key)&&!key.endsWith('_precision')&&!key.endsWith('_original'));
 return <dl>{entries.map(([key,value])=><div key={key}><dt>{technical?technicalLabel(key):reportLabels[key]??`נתון מקור: ${key}`}</dt><dd dir="auto">{key==='ownership_period'||key==='next_reported_period'?formatReportedPeriod(value):display(value)}</dd></div>)}</dl>;
}
function FullSpecification({details}:{details:Record<string,unknown>}){
 const categories:Record<string,Record<string,unknown>>={};
 for(const [key,value] of Object.entries(details)){const category=technicalCategory(key);(categories[category]??={})[key]=value}
 return <div className="full-spec"><p className="small-note">מפרט הגרסה הותאם לפי קודי תוצר ודגם, סוג דגם ושנה. החיוויים והמדדים להלן הם ערכי המקור; שדה חסר אינו מעיד שאביזר אינו קיים.</p>{Object.entries(categories).map(([title,fields])=><details className="sources" key={title}><summary>{title}</summary><Fields payload={fields} technical/></details>)}</div>;
}
function Row({row,kind,sourceName}:{row:DataRow;kind:string;sourceName?:string}){
 const quarter=kind==='ownership'&&typeof row.payload.ownership_period==='string';
 const payload=quarter?Object.fromEntries(Object.entries(row.payload).filter(([k])=>k!=='ownership_period'&&k!=='next_reported_period')):row.payload;
 return <div className={kind==='ownership'?'timeline-row':'data-row'}>
  {kind==='vehicles'&&<h4 className="profile-source">{sourceName??'רשומת זיהוי במקור'}</h4>}
  {quarter&&<div className="ownership-marker"><strong>{formatReportedPeriod(row.payload.ownership_period)}</strong><p className="small-note">מועד הדיווח הוא ברמת רבעון; יום המעבר המדויק אינו ידוע.</p></div>}
  <Fields payload={payload}/>
  {quarter&&<p className="small-note">{row.payload.next_reported_period?`דיווח מאוחר יותר במקור: ${formatReportedPeriod(row.payload.next_reported_period)}. אין זה תאריך סיום בעלות מדויק.`:'אין במקור דיווח בעלות מאוחר יותר; אין בכך אישור למצב הבעלות כיום.'}</p>}
  {row.projection==='reported_status_flags'&&<p className="small-note">חיוויים כפי שנמסרו במקור. מועד הרישום הראשון אינו מועד המדידה או השינוי.</p>}
  {kind==='specs'&&row.details&&<FullSpecification details={row.details}/>}
  {row.catalog&&<details className="sources"><summary>פרטי קריאת היצרן ואופן התיקון</summary><Fields payload={row.catalog.payload}/><p className="lineage">קטלוג: {row.catalog.source_id} · ריצה {row.catalog.run_id} · רשומה {row.catalog.source_record_id}</p></details>}
  {kind==='recalls'&&row.catalog_state==='not_found'&&<p className="small-note">רשומת הריקול לפי מספר הרכב נשמרה; לא נמצאה לה הרחבה יחידה בקטלוג היצרן.</p>}
  <div className="lineage">מקור: {sourceName??row.source_id} · ריצה {row.run_id} · רשומה {row.source_record_id}</div>
 </div>;
}
function Section({kind,group}:{kind:string;group:Group}){
 return <section className="report-card"><div className="card-heading"><h3>{groupNames[kind]}</h3><span className={`state ${group.rows.length?'good':''}`}>{stateLabels[group.state]}</span></div>
  {kind==='model_counts'&&<p className="small-note">ספירות מצרפיות של כלי רכב מאותו דגם במקור. אלה אינן ספירות של בעלים, ידיים או היסטוריית הרכב המסוים.</p>}
  {group.state==='multiple_sources'&&<p className="small-note">כל רשומת זיהוי מוצגת בנפרד עם המקור שלה. ערכים שונים לא נדרסו ולא נבחר מקור אחד בניחוש.</p>}
  {group.rows.length?<div className={kind==='ownership'?'timeline':''}>{group.rows.map((row,i)=><Row key={`${row.source_id}-${row.run_id}-${row.source_record_id}-${i}`} row={row} kind={kind} sourceName={group.sources.find(s=>s.id===row.source_id)?.name}/>)}</div>:<p className="muted">{stateLabels[group.state]}. אין להסיק מכך מסקנה על מצב הרכב.</p>}
  {kind==='mileage'&&Boolean(group.withheld_undated_count)&&<p className="small-note">{group.withheld_undated_count} רשומות נסועה ללא מועד מדידה ידוע אינן מוצגות כמדידה מתוארכת.</p>}
  {kind==='ownership'&&<p className="small-note">רישומי המקור נשמרו, כולל רישומים חוזרים. מספר הרשומות אינו מספר ה״ידיים״, והרבעונים אינם תאריכי מעבר מדויקים.</p>}
  {kind==='recalls'&&<p className="small-note">רק התאמות מאומתות למספר הרכב מוצגות. היעדר רשומה אינו אישור שאין ריקול.</p>}
  <details className="sources"><summary>מקורות, עדכון וכיסוי</summary>{group.sources.length?group.sources.map(s=><div key={s.id}><strong>{s.name}</strong><p>{stateLabels[s.state]} · עדכון מערכת: <bdi>{new Date(s.updated_at).toLocaleDateString('he-IL')}</bdi></p><p className="small-note">כיסוי: {display(s.coverage.description??s.coverage.scope??'לא פורט')} · מועד הנתונים במקור: {display(s.coverage.as_of)}</p>{Boolean(s.coverage.quarantine_note)&&<p className="small-note">{display(s.coverage.quarantine_note)}</p>}{Boolean(s.coverage.import_note)&&<p className="small-note">{display(s.coverage.import_note)}</p>}{s.official_url&&<a href={s.official_url} rel="noreferrer" target="_blank">מקור רשמי</a>}</div>):<p>לא הוגדר מקור לקבוצה זו.</p>}</details>
 </section>;
}
export default function Search({mode}:{mode:'demo'|'live'}){const [ready,setReady]=useState(false);useEffect(()=>setReady(true),[]);const [input,setInput]=useState('');const [loading,setLoading]=useState(false);const [error,setError]=useState('');const [report,setReport]=useState<Report|null>(null);const result=useRef<HTMLDivElement>(null);async function submit(e:React.FormEvent){e.preventDefault();const plate=normalizePlate(input);setError('');setReport(null);if(!plate){setError('יש להזין מספר רישוי בן 7 או 8 ספרות. אפשר לכלול רווחים ומקפים.');return}setLoading(true);try{const response=await fetch(`/api/vehicles/${encodeURIComponent(plate)}`,{cache:'no-store'});const data=await response.json();if(!response.ok)throw new Error(data.error||'לא ניתן להשלים את החיפוש כרגע.');if(data.mode!==mode)throw new Error('מצב הנתונים השתנה. יש לרענן את העמוד.');setReport(data);setTimeout(()=>result.current?.scrollIntoView({behavior:'smooth',block:'start'}),80)}catch(err){setError(err instanceof Error?err.message:'תקלה בחיבור לשירות. נסו שוב.')}finally{setLoading(false)}}return <><form className="search-box" data-ready={ready} onSubmit={submit}><label htmlFor="plate">מספר רישוי</label><div className="search-controls"><div className="plate-input"><span className="plate-strip">IL</span><input id="plate" name="plate" disabled={!ready} aria-describedby="input-help" inputMode="numeric" autoComplete="off" maxLength={32} placeholder="מספר הרכב שלך" value={input} onChange={e=>setInput(e.target.value)} dir="ltr"/></div><button type="submit" disabled={loading||!ready}>{loading?'מחפשים…':'בדיקת רכב'}<span aria-hidden="true">←</span></button></div><p id="input-help">7 או 8 ספרות · אפשר להקליד עם רווחים או מקפים</p>{mode==='demo'&&<p className="demo-hint">להתנסות: <button type="button" className="example" onClick={()=>setInput('01234567')}>01234567</button> — מספר סינתטי בלבד</p>}<div aria-live="polite">{loading&&<p className="loading">טוענים נתונים מהמאגר…</p>}{error&&<p className="error" role="alert">{error}</p>}</div></form>{report&&<div className="report" ref={result} tabIndex={-1}><div className="report-heading"><div><span className="eyebrow">תוצאת החיפוש</span><h2>דוח רכב <bdi>{report.plate}</bdi></h2></div><span className="report-mode">{report.mode==='demo'?'נתונים סינתטיים':'נתונים טעונים'}</span></div><p className="report-note">המידע מתייחס למקורות הזמינים במערכת. מועדים מוצגים בדיוק שבו דווחו: רבעון, חודש או יום. אין להסיק מספר ידיים ממספר רישומי הבעלות.</p><div className="report-grid">{Object.entries(report.groups).map(([kind,group])=><Section key={kind} kind={kind} group={group}/>)}</div></div>}</>}
