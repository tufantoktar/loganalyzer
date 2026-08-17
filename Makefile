.DEFAULT_GOAL := help
SHELL := /bin/bash

IMAGE       ?= loganalyzer
TAG         ?= dev
REGISTRY    ?= localhost:8082
MODEL       ?= llama3.2:3b

.PHONY: help
help: ## Komutlari listele
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: venv
venv: ## Sanal ortam kur
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements-dev.txt
	@echo "-> source .venv/bin/activate"

.PHONY: lint
lint: ## ruff + shellcheck
	ruff check loganalyzer tests
	ruff format --check loganalyzer tests
	@command -v shellcheck >/dev/null && shellcheck --severity=warning scripts/*.sh || echo "shellcheck yok, atlandi"

.PHONY: fmt
fmt: ## Kodu formatla
	ruff check --fix loganalyzer tests && ruff format loganalyzer tests

.PHONY: test
test: ## Testleri calistir
	pytest -v --cov=loganalyzer --cov-report=term-missing

.PHONY: sample
sample: ## Ornek log uret
	bash scripts/gen_sample_logs.sh sample_logs/app.log 500

.PHONY: run
run: sample ## Lokalde calistir (LLM'siz)
	python -m loganalyzer sample_logs/app.log --no-llm -o reports/report.md
	@echo "-> reports/report.md"

.PHONY: run-llm
run-llm: sample ## Lokalde calistir (Ollama ile)
	OLLAMA_HOST=http://localhost:11434 OLLAMA_MODEL=$(MODEL) \
	  python -m loganalyzer sample_logs/app.log --pull -o reports/report.md

.PHONY: up
up: ## Nexus'u kaldir
	docker compose up -d nexus
	@echo "Nexus  : http://localhost:8081  (parola: make nexus-password)"
	@echo "NOT: Ollama'yi sisteme kurduysan compose'daki ollama servisini baslatma,"
	@echo "     11434 portu cakisir. Konteyner istersen: docker compose up -d ollama"

.PHONY: pull-model
pull-model: ## Ollama modelini indir
	docker compose --profile setup run --rm model-puller

.PHONY: nexus-password
nexus-password: ## Nexus ilk admin parolasi
	@docker compose exec nexus cat /nexus-data/admin.password || echo "Nexus henuz hazir degil"

.PHONY: build
build: ## Docker imajini build et
	docker build -t $(IMAGE):$(TAG) .

.PHONY: docker-run
docker-run: build sample ## Imaji konteynerde calistir (host'taki Ollama'ya baglanir)
	@mkdir -p reports
	docker run --rm --network host \
	  -e OLLAMA_HOST=http://localhost:11434 \
	  -e OLLAMA_MODEL=$(MODEL) \
	  -v "$(PWD)/sample_logs:/data:ro" \
	  -v "$(PWD)/reports:/reports" \
	  $(IMAGE):$(TAG) /data/app.log -o /reports/report.md
	@echo "-> reports/report.md"

.PHONY: docker-run-compose
docker-run-compose: build sample ## Imaji compose stack'inde calistir (Ollama'yi da konteyner olarak baslatir)
	docker compose run --rm analyzer /data/app.log -o /reports/report.md --pull

.PHONY: push
push: build ## Nexus'a push et
	docker tag $(IMAGE):$(TAG) $(REGISTRY)/$(IMAGE):$(TAG)
	docker push $(REGISTRY)/$(IMAGE):$(TAG)

.PHONY: down
down: ## Stack'i durdur
	docker compose down

.PHONY: clean
clean: ## Uretilen dosyalari sil
	rm -rf reports sample_logs .pytest_cache .ruff_cache .coverage coverage.xml junit.xml
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
