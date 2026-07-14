.PHONY: dev down migrate revision test fmt lint backend-install frontend-install gen-key check-providers check-session-links

dev:
	docker compose up --build

down:
	docker compose down

migrate:
	cd backend && uv run alembic upgrade head

revision:
	cd backend && uv run alembic revision --autogenerate -m "$(m)"

test:
	cd backend && uv run pytest -q

fmt:
	cd backend && uv run ruff format app tests

lint:
	cd backend && uv run ruff check app tests

backend-install:
	cd backend && uv sync

frontend-install:
	cd frontend && pnpm install

# Generate a base64url 32-byte master key for ABOS_MASTER_KEY
gen-key:
	@python3 -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"

# Guardrail: no vendor SDK imported outside app/providers/
check-providers:
	@! grep -rnE "^\s*(import anthropic|from anthropic)" backend/app --include='*.py' \
		| grep -v "backend/app/providers/" \
		|| (echo "ERROR: anthropic SDK imported outside app/providers/" && exit 1)
	@! grep -rnE "^\s*(import openai|from openai)" backend/app --include='*.py' \
		| grep -v "backend/app/providers/" \
		|| (echo "ERROR: openai SDK imported outside app/providers/" && exit 1)
	@echo "provider-boundary OK"

# Guardrail: no Claude session links in commit messages or tracked files
check-session-links:
	@scripts/check_no_session_links.sh
