# Order Processing System

Educational microservices application using Python 3.12, FastAPI, PostgreSQL, RabbitMQ, Nginx, Docker, and Docker Compose.

## Services

- `order-service`: order API and orchestration.
- Product and stock management are handled by Order Service to keep the demo small.
- `notification-service`: asynchronous order notifications.
- `gateway`: Nginx API gateway.

Order Service stores products, stock, and orders in its own PostgreSQL database. Creating an order checks and decrements stock in the same transaction, then publishes a persistent `order.created` event to the durable RabbitMQ queue `order_notifications`. The publisher uses RabbitMQ's robust connection recovery; if publishing fails, order creation returns an error even though the order itself has already been saved.

The Order Service provides `POST /orders`, `GET /orders`, `GET /orders/{id}`, `POST /products`, `GET /products`, `GET /products/{id}`, and `GET /health`. Creating an order accepts `product_id` and `quantity`; `total_amount` is calculated from the product price. The Nginx gateway is the only application entry point exposed on the host, at `http://localhost:8080`; `/api/orders` routes to orders, `/api/inventory` routes to product management in Order Service, and `/api/notifications` routes to Notification Service.

The Notification Service consumes `order.created` events from the durable `order_notifications` RabbitMQ queue and stores one notification per order in its own PostgreSQL database. It acknowledges an event only after it is stored (or recognized as a duplicate). Its API provides `GET /notifications`, `GET /notifications/{id}`, and `GET /health`.

Order Service and Notification Service each have their own PostgreSQL container, connection-string environment variable, and named volume. Inventory no longer runs as a separate container or database. The services use Docker's private bridge network and connect to databases using service names.

## Local setup

1. Copy `.env.example` to `.env` (`Copy-Item .env.example .env` in PowerShell).
2. Fill in the required values in `.env`. Generate strong credentials rather than using example/default passwords. Set the database URLs to use their Docker service names (`order-db:5432` and `notification-db:5432`); set `RABBITMQ_URL` to `amqp://<RABBITMQ_USER>:<RABBITMQ_PASSWORD>@rabbitmq:5672/`.
3. Start the stack with `docker compose up --build`.
4. Access the gateway at `http://localhost:8080`.

Only the API gateway (`8080:80`) and RabbitMQ management UI (`15672:15672`) publish host ports. PostgreSQL and application service ports remain internal. All database and RabbitMQ credentials and connection URLs are supplied through `.env`; no development passwords are provided by the Compose configuration.
