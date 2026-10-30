-- Optional full technical fields, pinned to the original imported source row/run.
CREATE TABLE IF NOT EXISTS record_details (
 source_id text NOT NULL REFERENCES sources(id),
 run_id bigint NOT NULL REFERENCES import_runs(id),
 source_record_id text NOT NULL,
 details jsonb NOT NULL,
 source_sha256 text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(source_id,run_id,source_record_id)
);
