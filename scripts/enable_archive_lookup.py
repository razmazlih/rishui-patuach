"""Use audited archive registration-identifier aliases, not arbitrary text-code normalization."""
import json,os
from pathlib import Path
from importer.cli import connect
if os.environ.get('DATA_MODE')!='live':raise SystemExit('Explicit live mode required')
root=Path(__file__).resolve().parents[1]
audit=json.loads((root/'data/reports/archive-lookup-audit.json').read_text())
if audit.get('status')!='complete':raise RuntimeError('Complete full archive audit required')
updated=0
with connect() as db:
 if not db.execute('SELECT pg_try_advisory_xact_lock(87301826)').fetchone()[0]:raise RuntimeError('Import is running; retry after it finishes')
 for source in audit['sources']:
  if source['invalid_format'] or source['alias_collisions']:raise RuntimeError('Invalid archive lookup audit')
  active=db.execute('SELECT active_run_id FROM sources WHERE id=%s FOR UPDATE',(source['source_id'],)).fetchone()
  if not active or active[0]!=source['active_run_id']:raise RuntimeError('Archive version changed; repeat audit')
  settings={'plate_lookup_format':'zero_padded_8','plate_lookup_run_id':str(active[0]),'plate_lookup_evidence':'data/reports/archive-lookup-audit.json','plate_lookup_semantics':'official vehicle registration identifier; fixed-width export; exact-first lookup-only alias, source strings untouched'}
  db.execute('UPDATE sources SET coverage=coverage||%s::jsonb WHERE id=%s',(json.dumps(settings),source['source_id']));updated+=1
print(json.dumps({'status':'complete','archive_sources_enabled':updated,'source_rows_modified':0}))
