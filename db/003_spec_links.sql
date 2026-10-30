-- Derived join keys only. Source plate/code/payload values are never rewritten.
CREATE OR REPLACE FUNCTION spec_join_key(data jsonb) RETURNS text
LANGUAGE SQL IMMUTABLE PARALLEL SAFE RETURNS NULL ON NULL INPUT AS $$
 SELECT CASE WHEN data->>'model_type' IS NOT NULL AND data->>'model_type'<>''
                  AND data->>'manufacturer_code' ~ '^[0-9]+$'
                  AND data->>'model_code' ~ '^[0-9]+$'
                  AND data->>'year' ~ '^[0-9]{4}$'
             THEN jsonb_build_array(data->>'model_type',
                       coalesce(nullif(ltrim(data->>'manufacturer_code','0'),''),'0'),
                       coalesce(nullif(ltrim(data->>'model_code','0'),''),'0'),
                       data->>'year')::text
             ELSE NULL END
$$;
CREATE TABLE IF NOT EXISTS spec_links (
 vehicle_id bigint NOT NULL REFERENCES vehicles(id),
 vehicle_run_id bigint NOT NULL REFERENCES import_runs(id),
 spec_id bigint NOT NULL REFERENCES specs(id),
 spec_run_id bigint NOT NULL REFERENCES import_runs(id),
 canonical_key text NOT NULL,
 method text NOT NULL CHECK(method='numeric_code_v1'),
 linked_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(vehicle_id,spec_run_id)
);
CREATE INDEX IF NOT EXISTS spec_links_spec_id ON spec_links(spec_id);
CREATE TABLE IF NOT EXISTS model_count_links (
 vehicle_id bigint NOT NULL REFERENCES vehicles(id),
 vehicle_run_id bigint NOT NULL REFERENCES import_runs(id),
 model_count_id bigint NOT NULL REFERENCES model_counts(id),
 model_count_run_id bigint NOT NULL REFERENCES import_runs(id),
 canonical_key text NOT NULL,
 method text NOT NULL CHECK(method='numeric_code_v1'),
 linked_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(vehicle_id,model_count_run_id)
);
CREATE INDEX IF NOT EXISTS model_count_links_count_id ON model_count_links(model_count_id);
