.PHONY: up down build logs restart test-backend clean

up:
	docker compose up -d --build

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

restart:
	docker compose restart

test-backend:
	cd backend && pytest -v

clean:
	docker compose down -v
