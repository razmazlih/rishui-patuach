-- Aggregate/catalog source records are distinct from vehicle-linked observations.
-- They are intentionally not exposed as vehicle facts without a verified join.
CREATE TABLE IF NOT EXISTS model_counts (LIKE vehicles INCLUDING ALL);
CREATE TABLE IF NOT EXISTS recall_catalog (LIKE vehicles INCLUDING ALL);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['model_counts','recall_catalog'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname=t||'_source_fk' AND conrelid=to_regclass(t)) THEN
   EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY(source_id) REFERENCES sources(id)',t,t||'_source_fk');
   EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY(run_id) REFERENCES import_runs(id)',t,t||'_run_fk');
  END IF;
 END LOOP;
END $$;
