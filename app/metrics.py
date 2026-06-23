from prometheus_client import Counter, Gauge, Histogram

events_enqueued_total = Counter(
    "lis_events_enqueued_total",
    "Total log events accepted into the queue",
)
events_flushed_total = Counter(
    "lis_events_flushed_total",
    "Total log events successfully flushed to the database",
)
events_dropped_total = Counter(
    "lis_events_dropped_total",
    "Total log events dropped due to queue overflow",
)
flush_errors_total = Counter(
    "lis_flush_errors_total",
    "Total batch flush errors (written to dead-letter table)",
)
queue_depth = Gauge(
    "lis_queue_depth",
    "Current number of events waiting in the in-memory queue",
)
flush_duration_seconds = Histogram(
    "lis_flush_duration_seconds",
    "Wall-clock time to flush one batch to the database",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
