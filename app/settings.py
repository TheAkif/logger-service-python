import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://lis:lis@localhost:5433/lis_logs")
INGEST_TOKEN = os.getenv("INGEST_TOKEN", "dev-token")

DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))

DB_COMMAND_TIMEOUT = float(os.getenv("DB_COMMAND_TIMEOUT", "10"))
DB_ACQUIRE_TIMEOUT = float(os.getenv("DB_ACQUIRE_TIMEOUT", "5"))

BATCH_MAX = int(os.getenv("BATCH_MAX", "500"))          # flush when buffer reaches this size
BATCH_FLUSH_SEC = float(os.getenv("BATCH_FLUSH_SEC", "2"))  # flush interval
QUEUE_MAX = int(os.getenv("QUEUE_MAX", "20000"))        # backpressure (max queued events)
