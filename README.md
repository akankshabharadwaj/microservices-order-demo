# Mini Order Processing System

A small classroom example of two FastAPI services communicating over REST. It uses Python 3.12, async SQLAlchemy, PostgreSQL, Nginx, and Docker Compose.

## Architecture

```text
Client
  |
  v
Nginx API Gateway (localhost:8080)
  |
  v
Order Service ------> order-db
  |
  | HTTP POST /notifications
  v
Notification Service ------> notification-db
```

## What each service does

- **Order Service** owns products, stock, and orders. It checks and reduces stock when creating an order, then calls Notification Service over HTTP.
- **Notification Service** accepts `order.created` requests and stores a notification such as `Order 1 created successfully`. Repeated requests for the same order do not create duplicate notifications.
- **Nginx API Gateway** is the only container port exposed to the host. It routes `/api/orders/` to Order Service and `/api/notifications/` to Notification Service, removing the `/api/orders/` or `/api/notifications/` prefix so the FastAPI paths match.

## REST communication

Order Service sends a synchronous HTTP `POST` to `http://notification-service:8000/notifications` after saving an order. If Notification Service is unavailable, the order remains saved and the API returns an error explaining that notification creation failed. The order can be retrieved normally, and retrying the notification request with the same order ID is safe.

## Database per service

Order Service connects to `order-db`, which stores products and orders. Notification Service connects to `notification-db`, which stores notifications. The databases have separate named volumes and do not share tables.

## Docker Compose

`compose.yaml` starts five containers: `api-gateway`, `order-service`, `notification-service`, `order-db`, and `notification-db`. They use the same Docker bridge network named `private`. Each database has its own named volume. Only the gateway publishes a host port: `8080`.

Start the containers from the project root:

```powershell
docker compose up --build -d
```

Set PostgreSQL credentials and database URLs in `.env` before running Compose. The FastAPI services are not published as host ports.

## Classroom demonstration

Use `curl` (or `curl.exe` in Windows PowerShell).

1. **Start Docker Compose** (if you have not already):

   ```sh
   docker compose up --build -d
   ```

2. **Check the containers**:

   ```sh
   docker compose ps
   ```

3. **Create an ESP32 product with stock 20**:

   ```sh
   curl -X POST http://localhost:8080/api/orders/products \
     -H "Content-Type: application/json" \
     -d '{"name":"ESP32","price":650,"stock":20}'
   ```

4. **Retrieve products**:

   ```sh
   curl http://localhost:8080/api/orders/products
   ```

5. **Create an order for 2 ESP32 units**:

   ```sh
   curl -X POST http://localhost:8080/api/orders/orders \
     -H "Content-Type: application/json" \
     -d '{"product_id":1,"quantity":2}'
   ```

6. **Retrieve products again** and see that stock changed from 20 to 18:

   ```sh
   curl http://localhost:8080/api/orders/products
   ```

7. **Retrieve orders**:

   ```sh
   curl http://localhost:8080/api/orders/orders
   ```

8. **Retrieve notifications**:

   ```sh
   curl http://localhost:8080/api/notifications/notifications
   ```

9. Explain the synchronous REST flow:

   ```text
   Order Service -> HTTP POST /notifications -> Notification Service
   ```

   Health checks are available at `/api/orders/health` and `/api/notifications/health`.
