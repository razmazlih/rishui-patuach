export function formatReportedPeriod(value:unknown):string{
 const text=String(value??'');const match=/^([0-9]{4})-Q([1-4])$/.exec(text);
 return match?`רבעון ${match[2]}, ${match[1]}`:text||'לא נמסר';
}
