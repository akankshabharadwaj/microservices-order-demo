# Order Processing System

Educational microservices application using Python 3.12, FastAPI, PostgreSQL, RabbitMQ, Nginx, Docker, and Docker Compose.

## Services

- `order-service`: order API and orchestration.
- `inventory-service`: inventory and stock management.
- `notification-service`: asynchronous order notifications.
- `gateway`: Nginx API gateway.

The Order Service stores orders in its own PostgreSQL database. Before it creates an order, it synchronously reserves the requested quantity through the Inventory Service; it does not access the Inventory database directly. After saving an order, it publishes a persistent `order.created` event to the durable RabbitMQ queue `order_notifications`. The publisher uses RabbitMQ's robust connection recovery; if publishing fails, order creation returns an error even though the order itself has already been saved.

The Order Service provides `POST /orders`, `GET /orders`, `GET /orders/{id}`, and `GET /health`. Creating an order accepts `product_id` and `quantity`; `total_amount` is calculated from the product price returned by Inventory Service. The Nginx gateway is the only service exposed on the host, at `http://localhost:8080`; it routes `/api/orders` to Order Service, `/api/inventory` to Inventory Service, and `/api/notifications` to Notification Service, stripping each API prefix where needed.

The Notification Service consumes `order.created` events from the durable `order_notifications` RabbitMQ queue and stores one notification per order in its own PostgreSQL database. It acknowledges an event only after it is stored (or recognized as a duplicate). Its API provides `GET /notifications`, `GET /notifications/{id}`, and `GET /health`.

Each microservice has a separate PostgreSQL container, connection-string environment variable, and named data volume: Order uses `order-db` / `ORDER_DATABASE_URL` / `order-db-data`, Inventory uses `inventory-db` / `INVENTORY_DATABASE_URL` / `inventory-db-data`, and Notification uses `notification-db` / `NOTIFICATION_DATABASE_URL` / `notification-db-data`. Each database is attached only to its service-specific internal data network, so application services cannot connect to another service's database.

## Local setup

1. Copy `.env.example` to `.env`.
2. Set unique, strong values for the PostgreSQL and RabbitMQ credentials, and set each database URL to use its corresponding Docker service name (for example, `order-db:5432`).
3. Start the stack with `docker compose up --build`.
4. Access the gateway at `http://localhost:8080`.

Only the API gateway (`8080:80`) and RabbitMQ management UI (`15672:15672`) publish host ports. PostgreSQL and application service ports remain internal. The application services share a private network; each PostgreSQL container is additionally isolated on the data network for its own service. All database and RabbitMQ credentials and connection URLs are supplied through `.env`; no development passwords are provided by the Compose configuration.
