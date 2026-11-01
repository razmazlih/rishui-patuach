SHELL := /bin/sh
PY := .venv/bin/python
# .env is local CLI configuration; web loads .env.local or .env.
-include .env
export DATABASE_URL DATA_MODE DATA_DIR

.PHONY: setup db db-native up down dev start migrate demo inspect import rollback test unit integration api e2e check benchmark stage-real promote-real e2e-live modes
setup:
	npm ci
	python3 -m venv .venv
	$(PY) -m pip install -r importer/requirements.txt
db-native:
	sh scripts/local-postgres.sh
db:
	docker compose up -d db
up:
	docker compose up -d --build db web
down:
	docker compose down
dev:
	npm run dev
start:
	npm start
migrate:
	$(PY) -m importer.cli migrate
demo:
	DATA_MODE=demo $(PY) -m importer.cli demo
inspect:
	$(PY) -m importer.cli inspect "$(FILE)" $(if $(ENCODING),--encoding "$(ENCODING)") $(if $(DELIMITER),--delimiter '$(DELIMITER)')
import:
	$(PY) -m importer.cli import "$(FILE)" --mapping "$(MAPPING)"
rollback:
	$(PY) -m importer.cli rollback "$(SOURCE)" "$(RUN)"
unit:
	npm test
	$(PY) -m unittest importer.test_unit
integration:
	@test -n "$(DATABASE_URL)" || (echo 'DATABASE_URL required (use a disposable local database)'; exit 1)
	TEST_DATABASE_URL="$(DATABASE_URL)" $(PY) -m unittest importer.test_database
	TEST_DATABASE_URL="$(DATABASE_URL)" $(PY) -m unittest discover -s tests -p 'test_import*.py'
api:
	$(PY) -m unittest tests.test_api
e2e:
	npm run test:e2e
check:
	npm run typecheck
	npm run build
modes:
	RUN_MODE_TESTS=1 $(PY) -m unittest tests.test_modes
test: unit integration api e2e modes
benchmark:
	$(PY) scripts/benchmark.py --rows $(or $(ROWS),100000)

stage-real:
	DATA_MODE=live $(PY) -m importer.real stage "$(FILE)" --mapping "$(MAPPING)"
promote-real:
	DATA_MODE=live $(PY) -m importer.real promote "$(RUN)"
e2e-live:
	E2E_LIVE=1 npm run test:e2e -- --grep 'live imported'
