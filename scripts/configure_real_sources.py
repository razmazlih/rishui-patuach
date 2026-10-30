#!/usr/bin/env python3
"""Generate reviewed structural mappings; reads metadata reports, never raw records.
Source fields not needed by this website are explicitly ignored. Local source files
are never read or modified. Every output includes verification scope and holds.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRICT = {'bb2355dc-9ec7-4f06-9c3f-3344672171da','0866573c-40cd-4ca8-91d2-9dd2d7a492e5',
          '36bf1404-0be4-49d2-82dc-2f1ead4a8b93','2c33523f-87aa-44ec-a736-edbb0a82975e'}
ARCHIVES = {'2010-2016_bitul_sofi':'4e6b9724-4c1e-43f0-909a-154d4cc4e046',
            'bitul_sofi_2000_2009':'ec8cbc34-72e1-4b69-9c48-22821ba0bd6c'}
KINDS = {
 '053cea08-09bc-40ec-8f7a-156f0677aff3':'vehicles',
 'f6efe89a-fb3d-43a4-bb61-9bf12a9b9099':'vehicles',
 'bf9df4e2-d90d-4c0a-a400-19e15af8e95f':'vehicles',
 'cd3acc5c-03c3-4c89-9c54-d40f93c0d790':'vehicles',
 '6f6acd03-f351-4a8f-8ecf-df792f4f573a':'vehicles',
 'cf29862d-ca25-4691-84f6-1be60dcb4a1e':'vehicles',
 '851ecab1-0622-4dbe-a6c7-f950cf82abf9':'statuses',
 '2010-2016_bitul_sofi':'statuses','bitul_sofi_2000_2009':'statuses',
 '0866573c-40cd-4ca8-91d2-9dd2d7a492e5':'statuses',
 '142afde2-6228-49f9-8a29-9b6c3a0cbe40':'specs',
 '5e87a7a1-2f6f-41c1-8aec-7216d52a6cf6':'model_counts',
 '2c33523f-87aa-44ec-a736-edbb0a82975e':'recall_catalog',
 '36bf1404-0be4-49d2-82dc-2f1ead4a8b93':'recalls',
 'bb2355dc-9ec7-4f06-9c3f-3344672171da':'ownership',
 '56063a99-8a3e-4ff4-912e-5966c0279bad':'mileage',
}
COMMON = {
 'mispar_rechev':'plate','MISPAR_RECHEV':'plate',
 'tozeret_cd':'manufacturer_code','tozeret_nm':'manufacturer',
 'degem_cd':'model_code','degem_nm':'model','sug_degem':'model_type',
 'shnat_yitzur':'year','tzeva_rechev':'color','sug_delek_nm':'fuel',
 'kinuy_mishari':'commercial_name','ramat_gimur':'trim',
 'baalut':'current_ownership_type',
 'moed_aliya_lakvish':'first_registration_date_raw',
}
SPEC = {
 'nefah_manoa':'engine_volume_raw','koah_sus':'power_hp','mispar_dlatot':'doors',
 'mispar_moshavim':'seats','automatic_ind':'automatic_transmission_flag_raw',
 'delek_nm':'fuel','hanaa_nm':'drive_type',
}
SUPPLEMENT = {
 'kod_omes_tzmig_kidmi':'front_tire_load_code','kod_omes_tzmig_ahori':'rear_tire_load_code',
 'kod_mehirut_tzmig_kidmi':'front_tire_speed_code','kod_mehirut_tzmig_ahori':'rear_tire_speed_code',
 'grira_nm':'towing_description',
}
RECALL = {'RECALL_ID':'recall_id','SUG_RECALL':'recall_type','SUG_TAKALA':'fault_type',
          'TEUR_TAKALA':'description','TAARICH_PTICHA':'announced_at',
          'TOZAR_CD':'manufacturer_code','TOZAR_TEUR':'manufacturer','DEGEM':'model',
          'SHNAT_RECALL':'recall_year','BUILD_BEGIN_A':'production_begin_raw',
          'BUILD_END_A':'production_end_raw','OFEN_TIKUN':'remedy_description',
          'TKINA_EU':'type_approval_code'}
COMPOSITE = ['model_type','manufacturer_code','model_code','year']


def build(local, official, evidence):
    stem=Path(local['name']).stem
    if stem not in KINDS:
        raise ValueError('Unrecognized source identity: '+stem)
    rid=ARCHIVES.get(stem,stem)
    entry=official[rid]
    headers=[f['id'] for f in entry['fields'] if f['id']!='_id']
    if local['headers']!=headers:
        raise ValueError('Local and official header mismatch: '+stem)
    ev=evidence[local['name']]
    if ev.get('header_matches') is not True or ev.get('source_framing_sample_verified') is not True or ev.get('encoding_content_sample_verified') is not True:
        raise ValueError('Required independent framing/content sample evidence absent: '+stem)
    kind=KINDS[stem]
    fields={header:{'ignore':True} for header in headers}
    def put(source,target,**kwargs):
        if source in fields:
            fields[source]={'target':target,'type':'text',**kwargs}
    for source,target in COMMON.items():put(source,target)
    for source in ('mispar_rechev','MISPAR_RECHEV'):
        put(source,'plate',required=True,normalize='plate')
    for source,target in [('mivchan_acharon_dt','test_date'),('tokef_dt','license_valid_until'),('bitul_dt','cancellation_date')]:
        put(source,target,type='date',formats=['iso_date','iso_datetime'])
    if kind=='specs':
        for source,target in SPEC.items():put(source,target)
    if stem=='0866573c-40cd-4ca8-91d2-9dd2d7a492e5':
        for source,target in SUPPLEMENT.items():put(source,target)
    if stem=='bb2355dc-9ec7-4f06-9c3f-3344672171da':
        put('baalut','ownership_type');put('baalut_dt','ownership_date_raw')
    if stem=='56063a99-8a3e-4ff4-912e-5966c0279bad':
        put('kilometer_test_aharon','kilometers',type='integer')
        put('rishum_rishon_dt','first_registration_date_raw')
        put('mkoriut_nm','original_usage_description')
        for source in ('shinui_mivne_ind','gapam_ind','shnui_zeva_ind','shinui_zmig_ind'):
            put(source,'source_flag_'+source)
    if kind in ('recalls','recall_catalog'):
        for source,target in RECALL.items():
            if source=='TAARICH_PTICHA':put(source,target,type='date',formats=['iso_date','iso_datetime'])
            else:put(source,target)
    if kind=='model_counts':
        put('mispar_rechavim_pailim','active_vehicle_count',type='integer')
        put('mispar_rechavim_le_pailim','inactive_vehicle_count',type='integer')
    date_hold=[]
    if kind=='ownership':date_hold=['baalut_dt_semantics_unverified']
    if stem=='053cea08-09bc-40ec-8f7a-156f0677aff3':date_hold=['strict_codec_failed']
    config={
      'id':'mot-'+rid,'source_file':local['name'],'resource_id':rid,'kind':kind,
      'name':entry['resource']['name'],'version':'real-1','verified':True,'synthetic':False,
      'official_url':'https://data.gov.il/api/3/action/resource_show?id='+rid,
      'encoding':local['encoding'],'encoding_verified':True,'delimiter':'|',
      'dialect':'csv' if stem in STRICT else 'mot_envelope',
      'dialect_verified':True,
      'key_mode':'fields' if kind in ('vehicles','specs','recall_catalog','model_counts') else 'row_number',
      'keys':['plate'] if kind=='vehicles' else ['recall_id'] if kind=='recall_catalog' else COMPOSITE if kind in ('specs','model_counts') else [],
      'fields':fields,'publication_hold':date_hold,
      'coverage':{
         'description':entry['dataset'].get('notes') or entry['resource']['name'],
         'as_of':None,'date_precision':None,'scope':'official source coverage; local snapshot date unknown',
         'official_metadata_updated':entry['resource'].get('last_modified'),
         'source_resource_id':rid,
      },
      'verification':{
         'official_headers_exact':True,'official_metadata':'data/reports/official-metadata.json',
         'field_semantics':'docs/REAL_SOURCES.md',
         'framing_encoding_evidence':'data/reports/official-framing-encoding-evidence.json',
         'framing_encoding_scope':'sampled; independent official selection; lexical values retained',
         'sampled_records':ev.get('local_records'),
         'full_validation_required':True,
      },
      'max_unmatched_rate':1,
      'matching_threshold_reason':'Official populations and update dates differ; unmatched rows are retained and fully counted, never guessed or matched by model name.',
    }
    if kind=='specs':
        config.update(composite_key_fields=COMPOSITE,verified_composite_key=True)
    # A shared name is only a candidate; vehicle-spec linkage remains held pending
    # full catalog uniqueness and explicit source-pair key meaning verification.
    if kind=='vehicles' and all(any(v.get('target')==k for v in fields.values()) for k in COMPOSITE):
        config['candidate_composite_key_fields']=COMPOSITE
    if kind=='recalls':config['verified_plate_link']=True
    if kind=='ownership':config['preserve_exact_events']=True
    return config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enable-audited-primary-quarantine',action='store_true')
    args=parser.parse_args()
    inspection=json.loads((ROOT/'data/reports/real-inspect-explicit.json').read_text())
    metadata=json.loads((ROOT/'data/reports/official-metadata.json').read_text())
    official={e['resource_id']:e for e in metadata['sources']}
    framing=json.loads((ROOT/'data/reports/official-framing-encoding-evidence.json').read_text())
    evidence={e['file']:e for e in framing['sources']}
    out=ROOT/'mappings/real';out.mkdir(parents=True,exist_ok=True)
    configs=[build(local,official,evidence) for local in inspection]
    if args.enable_audited_primary_quarantine:
        primary=next(c for c in configs if c['resource_id']=='053cea08-09bc-40ec-8f7a-156f0677aff3')
        audit_path=ROOT/'data/reports/audit-mot-bytes-main-20261030/053cea08-09bc-40ec-8f7a-156f0677aff3.audit.json'
        audit=json.loads(audit_path.read_text())
        if not (audit.get('scan_complete') is True and audit.get('status')=='complete' and audit.get('source_unchanged') is True and audit.get('duplicates',{}).get('status')=='complete' and audit['duplicates'].get('extra_rows')==0 and audit.get('records_read')==4197986 and len(audit.get('sha256',''))==64):
            raise ValueError('Primary byte-preserving audit is incomplete or differs from reviewed evidence')
        primary.update(dialect='mot_envelope_bytesbridge',publication_hold=[],full_audit_report=str(audit_path.relative_to(ROOT)),quarantine_policy={'max_records':3,'max_fraction':0.000001,'allowed_reasons':['decode_error']})
        primary['coverage']['quarantine_note']='מקור חלקי: עד 3 רשומות עם שגיאת פענוח יבודדו במלואן, ללא תיקון או ניחוש תווים. הספירה המדויקת מופיעה בדוח היבוא.'
        primary['verification']['quarantine_policy']='Explicit audited bounded whole-record rejection; no ignore or replacement; source bytes retained unchanged.'
    for config in configs:
        (out/(Path(config['source_file']).stem+'.json')).write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':'generated','sources':len(configs),'held_sources':sum(bool(c['publication_hold']) for c in configs),'raw_files_read':0},ensure_ascii=False))


if __name__=='__main__':main()
