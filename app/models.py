from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, List

from pydantic import BaseModel, Field, ConfigDict, field_validator


class Environment(str, Enum):
    dev = "dev"
    staging = "staging"
    prod = "prod"


class LogLevel(str, Enum):
    debug = "debug"
    info = "info"
    warn = "warn"
    error = "error"
    fatal = "fatal"


class LogType(str, Enum):
    app = "app"
    access = "access"
    audit = "audit"
    ui = "ui"


# ---- Models ----
class LogEvent(BaseModel):
    """
    Canonical log event shape for LIS.
    - Keep low-cardinality fields as top-level columns (tenantId, source, env, level, type).
    - Put extra arbitrary data in properties (JSON).
    """

    model_config = ConfigDict(extra="forbid")  # reject unknown fields (professional contract)

    occurredAt: Optional[datetime] = Field(
        default=None,
        description="When the event occurred at the source (UTC recommended). If omitted, server will set it."
    )

    tenantId: str = Field(..., min_length=2, max_length=64, description="Tenant identifier (e.g., jeddah).")
    source: str = Field(..., min_length=2, max_length=64, description="Service/app name (e.g., authservice, mf-users).")
    environment: Environment = Field(..., description="Deployment environment.")
    level: LogLevel = Field(..., description="Log level.")
    type: LogType = Field(..., description="Log category.")

    message: str = Field(..., min_length=1, max_length=2048, description="Human-readable message.")

    # tracing / correlation
    traceId: Optional[str] = Field(default=None, max_length=128)
    spanId: Optional[str] = Field(default=None, max_length=128)
    correlationId: Optional[str] = Field(default=None, max_length=128)
    requestId: Optional[str] = Field(default=None, max_length=128)

    # actor/context
    userId: Optional[str] = Field(default=None, max_length=128)

    # access log fields (optional)
    path: Optional[str] = Field(default=None, max_length=512)
    method: Optional[str] = Field(default=None, max_length=16)
    statusCode: Optional[int] = Field(default=None, ge=100, le=599)
    durationMs: Optional[int] = Field(default=None, ge=0, le=60_000_000)

    # error details + extra metadata
    exception: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Error info like {name, message, stack}. Keep it small."
    )
    properties: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Extra metadata (JSON). Avoid PII."
    )

    @field_validator("tenantId", "source", mode="before")
    @classmethod
    def strip_and_reject_default_swagger_strings(cls, v: Any) -> Any:
        """
        Swagger defaults to 'string'. People often submit that by accident.
        Reject obvious placeholder values and empty strings.
        """
        if v is None:
            return v
        if isinstance(v, str):
            s = v.strip()
            if s == "" or s.lower() == "string":
                raise ValueError("must be a real value, not empty/'string'")
            return s
        return v

    @field_validator("message", mode="before")
    @classmethod
    def message_not_placeholder(cls, v: Any) -> Any:
        if isinstance(v, str):
            s = v.strip()
            if s == "":
                raise ValueError("message cannot be empty")
            if s.lower() == "string":
                raise ValueError("message must be a real value, not 'string'")
            return s
        return v


class BatchIngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: bool = True
    count: int = Field(ge=0)


# ---- Swagger Examples ----
# This makes /docs show realistic payloads instead of placeholder "string".
LogEvent.model_config["json_schema_extra"] = {
    "examples": [
        {
            "occurredAt": "2026-01-01T08:19:16.966Z",
            "tenantId": "jeddah",
            "source": "authservice",
            "environment": "dev",
            "level": "error",
            "type": "app",
            "message": "Login failed: invalid password",
            "traceId": "a1b2c3d4e5f6",
            "correlationId": "req-9f1a",
            "properties": {"ip": "10.0.0.10", "username": "theakif"}
        },
        {
            "tenantId": "jeddah",
            "source": "mf-users",
            "environment": "dev",
            "level": "error",
            "type": "ui",
            "message": "Unhandled promise rejection",
            "path": "/users/list",
            "properties": {"browser": "Chrome", "appVersion": "1.2.7"},
            "exception": {"name": "TypeError", "message": "Cannot read properties of undefined", "stack": "…"}
        },
        {
            "tenantId": "jeddah",
            "source": "mapservice",
            "environment": "dev",
            "level": "info",
            "type": "access",
            "message": "GET /layers/42",
            "method": "GET",
            "path": "/layers/42",
            "statusCode": 200,
            "durationMs": 23,
            "traceId": "f00dbabe"
        }
    ]
}
