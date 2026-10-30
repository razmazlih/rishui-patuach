CREATE TABLE IF NOT EXISTS sources (
 id text PRIMARY KEY, kind text NOT NULL, name text NOT NULL, coverage jsonb NOT NULL,
 synthetic boolean NOT NULL, active_run_id bigint, availability text NOT NULL DEFAULT 'not_loaded',
 official_url text, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS source_files (
 id bigserial PRIMARY KEY, source_id text NOT NULL REFERENCES sources(id), name text NOT NULL,
 sha256 text NOT NULL, size_bytes bigint NOT NULL, received_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS import_runs (
 id bigserial PRIMARY KEY, source_id text NOT NULL REFERENCES sources(id), file_id bigint REFERENCES source_files(id),
 state text NOT NULL, fingerprint text NOT NULL, mapping_version text NOT NULL, importer_version text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), published_at timestamptz, report jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS import_runs_fingerprint ON import_runs(fingerprint,state);
CREATE TABLE IF NOT EXISTS staging (
 run_id bigint NOT NULL REFERENCES import_runs(id), row_number bigint NOT NULL,
 source_record_id text, plate text, payload jsonb NOT NULL, row_hash text NOT NULL,
 PRIMARY KEY(run_id,row_number)
);
CREATE INDEX IF NOT EXISTS staging_record_key ON staging(run_id,source_record_id);
CREATE INDEX IF NOT EXISTS staging_row_hash ON staging(run_id,row_hash);
CREATE TABLE IF NOT EXISTS rejected_rows (
 run_id bigint NOT NULL REFERENCES import_runs(id), row_number bigint NOT NULL, reason text NOT NULL,
 PRIMARY KEY(run_id,row_number)
);
CREATE TABLE IF NOT EXISTS vehicles (
 id bigserial PRIMARY KEY, plate text, source_id text NOT NULL REFERENCES sources(id),
 run_id bigint NOT NULL REFERENCES import_runs(id), source_record_id text NOT NULL, payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS vehicles_plate ON vehicles(plate,run_id);
CREATE TABLE IF NOT EXISTS specs (LIKE vehicles INCLUDING ALL);
CREATE TABLE IF NOT EXISTS ownership (LIKE vehicles INCLUDING ALL);
CREATE TABLE IF NOT EXISTS mileage (LIKE vehicles INCLUDING ALL);
CREATE TABLE IF NOT EXISTS statuses (LIKE vehicles INCLUDING ALL);
CREATE TABLE IF NOT EXISTS recalls (LIKE vehicles INCLUDING ALL);
CREATE INDEX IF NOT EXISTS specs_key ON specs((payload->>'spec_key'),run_id);
CREATE TABLE IF NOT EXISTS request_limits (
 bucket text PRIMARY KEY, window_start timestamptz NOT NULL DEFAULT now(), requests integer NOT NULL DEFAULT 1
);

DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['specs','ownership','mileage','statuses','recalls'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname=t||'_source_fk' AND conrelid=to_regclass(t)) THEN
   EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY(source_id) REFERENCES sources(id)',t,t||'_source_fk');
   EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY(run_id) REFERENCES import_runs(id)',t,t||'_run_fk');
  END IF;
 END LOOP;
END $$;
