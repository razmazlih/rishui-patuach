"""Enable only audited lookup aliases for the current active runs; preserve source rows."""
import json,os
from pathlib import Path
from importer.cli import connect
if os.environ.get('DATA_MODE')!='live':raise SystemExit('Explicit live mode required')
root=Path(__file__).resolve().parents[1]
audit=json.loads((root/'data/reports/plate-lookup-audit.json').read_text())
updated=0
with connect() as db:
 if not db.execute('SELECT pg_try_advisory_xact_lock(87301826)').fetchone()[0]:raise RuntimeError('Import in progress')
 for item in audit['sources']:
  if not (item.get('lookup_format_verified') and item.get('official_plate_field_numeric') and item['invalid_or_non_8_digit_rows']==0 and item['alias_collision_count']==0):continue
  table=item['table']
  if table not in ('vehicles','statuses','mileage','ownership','recalls'):raise RuntimeError('Unsupported plate table')
  source=item['source_id']
  active=db.execute('SELECT active_run_id FROM sources WHERE id=%s FOR UPDATE',(source,)).fetchone()
  if not active or not active[0]:raise RuntimeError('Audited source is no longer active')
  count=db.execute(f'SELECT count(*) FROM {table} WHERE source_id=%s AND run_id=%s',(source,active[0])).fetchone()[0]
  if count!=item['rows']:raise RuntimeError('Audited source changed; repeat full audit')
  settings={'plate_lookup_format':'zero_padded_8','plate_lookup_run_id':str(active[0]),'plate_lookup_evidence':'data/reports/plate-lookup-audit.json'}
  db.execute('UPDATE sources SET coverage=coverage||%s::jsonb WHERE id=%s',(json.dumps(settings),source));updated+=1
print(json.dumps({'status':'complete','verified_active_sources_enabled':updated,'source_records_modified':0}))
