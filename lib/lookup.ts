import type {Source} from './report';

/** Lookup-only alias. Never changes user input, source plate, or model codes. */
export function paddedLookup(plate:string, mode:'demo'|'live'):string|null {
  return mode==='live' && /^[0-9]{7}$/.test(plate) ? `0${plate}` : null;
}

export function emptyGroupState(sources:Source[]):string {
  if(sources.length===0)return 'not_loaded';
  // A held supplemental source does not erase the fact that loaded sources were searched.
  if(sources.some(s=>Boolean(s.active_run_id)&&s.availability==='available'&&s.coverage.covered!==false))return 'not_found';
  if(sources.every(s=>s.state==='not_covered'))return 'not_covered';
  if(sources.some(s=>s.state==='quality_failed'))return 'quality_failed';
  if(sources.some(s=>s.state==='unavailable'))return 'unavailable';
  return 'not_loaded';
}
