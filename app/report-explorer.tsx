'use client';
import {useRef,useState} from 'react';
import type {Report} from '@/lib/report';

type Fact={label:string;value:string};
type Insight={id:string;title:string;icon:string;facts:Fact[];note:string};
function unique(report:Report,kind:string,key:string){
 const values=[...new Set((report.groups[kind]?.rows??[]).map(row=>row.payload[key]).filter(value=>value!=null&&String(value).trim()!==''))];
 return values.length===1?String(values[0]):null;
}
function facts(report:Report,kind:string,fields:[string,string][]):Fact[]{return fields.flatMap(([key,label])=>{const value=unique(report,kind,key);return value?[{label,value}]:[]})}
export default function ReportExplorer({report}:{report:Report}){
 const [selection,setSelection]=useState('license');
 const controls=useRef<(HTMLButtonElement|null)[]>([]);
 const name=unique(report,'vehicles','commercial_name');
 const year=unique(report,'vehicles','year');
 const manufacturer=unique(report,'vehicles','manufacturer');
 const options:Insight[]=[
  {id:'license',title:'רישוי וטסט',icon:'M8 2v4m8-4v4M3 10h18M5 4h14v17H3V4h2m3 11 3 3 5-5',facts:facts(report,'vehicles',[['license_valid_until','תוקף הרישוי במקור'],['test_date','הטסט המדווח האחרון']]),note:'אלה המועדים שנמסרו במקור. יש לבדוק עדכונים מול הגורם הרשמי.'},
  {id:'engine',title:'מתחת למכסה',icon:'M7 7h10v3h4v8H7l-4-4v-4h4V7m3-4h5m-3 0v4',facts:facts(report,'specs',[['power_hp','כוחות סוס'],['engine_volume_raw','נפח מנוע כפי שנמסר'],['drive_type','הנעה'],['fuel','סוג דלק']]),note:'המפרט הותאם לגרסת הדגם במקור; הוא אינו בדיקה של מצב המנוע בפועל.'},
  {id:'ownership',title:'סוג הבעלות',icon:'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8m9 4a4 4 0 0 1 4 4v2',facts:facts(report,'vehicles',[['current_ownership_type','סוג בעלות מדווח נוכחי']]),note:'זהו סוג הבעלות המדווח במאגר, ולא מספר הידיים. אפשר לחקור את תקופות הדיווח בציר שבהמשך.'},
  {id:'model',title:'הדגם במספרים',icon:'M4 20V10h4v10m3 0V4h4v16m3 0v-7h4v7',facts:facts(report,'model_counts',[['active_vehicle_count','כלי רכב פעילים מדגם זה במקור'],['inactive_vehicle_count','כלי רכב לא פעילים מדגם זה במקור']]),note:'נתונים מצרפיים על הדגם במאגר, ולא היסטוריה של הרכב המסוים.'}
 ].filter(option=>option.facts.length>0);
 if(!options.length)return null;
 const active=options.find(option=>option.id===selection)??options[0];
 return <div className="vehicle-explorer">
  <div className="explorer-title"><div className="explorer-identity"><span className="explorer-kicker">בואו נכיר את הרכב</span><h3>{name?<bdi>{name}</bdi>:'מבט מהיר על הנתונים'}{year&&<span className="explorer-year">{year}</span>}</h3>{manufacturer&&<p>{manufacturer}</p>}</div><div className="explorer-scene"><span className="scene-ring" aria-hidden="true"/><svg className="explorer-car" viewBox="0 0 180 90" fill="none" aria-hidden="true"><path d="m20 55 14-23 35-7 22-15h39l20 24 17 10 3 22H14v-9Z" fill="currentColor" fillOpacity=".1" stroke="currentColor" strokeWidth="2"/><path d="m69 29 24-14h34l15 17ZM100 15v16" stroke="currentColor" strokeWidth="2"/><circle cx="47" cy="66" r="13" fill="white" stroke="currentColor" strokeWidth="3"/><circle cx="142" cy="66" r="13" fill="white" stroke="currentColor" strokeWidth="3"/><path d="M21 47h19m112-5 14 5" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/></svg><span className="scene-caption">איור להמחשה</span></div></div>
  <div className="explorer-guide"><span className="guide-spark" aria-hidden="true">✦</span> מה מעניין אותך לגלות?</div>
  <div className="insight-options" role="group" aria-label="מה מעניין אותך ברכב?">{options.map((option,index)=><button type="button" ref={element=>{controls.current[index]=element}} className={option.id===active.id?'is-active':''} aria-pressed={option.id===active.id} aria-controls={`insight-${report.plate}`} key={option.id} onClick={()=>setSelection(option.id)} onKeyDown={event=>{
    let next:number|undefined;
    if(event.key==='ArrowLeft')next=(index+1)%options.length;
    if(event.key==='ArrowRight')next=(index-1+options.length)%options.length;
    if(event.key==='Home')next=0;
    if(event.key==='End')next=options.length-1;
    if(next!==undefined){event.preventDefault();setSelection(options[next].id);controls.current[next]?.focus()}
   }}><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={option.icon}/></svg>{option.title}</button>)}</div>
  <div className="insight-panel" data-insight={active.id} id={`insight-${report.plate}`} aria-live="polite" aria-atomic="true"><div key={active.id} className="insight-content"><div className="insight-panel-label"><span aria-hidden="true"/> {active.title}</div><dl>{active.facts.map(fact=><div key={fact.label}><dt>{fact.label}</dt><dd dir="auto">{fact.value}</dd></div>)}</dl><p>{active.note}</p><a className="insight-deeper" href={`#report-${{license:'vehicles',engine:'specs',ownership:'ownership',model:'model_counts'}[active.id]}`}>לכל הפרטים בדוח <span aria-hidden="true">↙</span></a></div></div>
  <div className="explorer-hint"><span aria-hidden="true">↓</span> התמונה המלאה וכל הנתונים בהמשך</div>
 </div>;
}
