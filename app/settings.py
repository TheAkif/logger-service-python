import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://lis:lis@localhost:5433/lis_logs"
)

INGEST_TOKEN = os.getenv("INGEST_TOKEN", "dev-token")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://lis:lis@localhost:5672/")
LOG_QUEUE = os.getenv("LOG_QUEUE", "lis.logs")
LOG_DLQ = os.getenv("LOG_DLQ", "lis.logs.dlq")
