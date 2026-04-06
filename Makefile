.PHONY: draft ingest

ingest:
	docker compose --profile tools run --rm cache-warmer

draft:
	docker compose --profile tools run --rm draft-builder
	docker compose --profile tools run --rm -it draft-runner
