.PHONY: draft

draft:
	docker compose --profile tools run --rm draft-builder
	docker compose --profile tools run --rm -it draft-runner
