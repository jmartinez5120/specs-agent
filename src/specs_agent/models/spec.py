"""Data models for parsed OpenAPI/Swagger specifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    OPTIONS = "OPTIONS"
    HEAD = "HEAD"


class ParameterLocation(str, Enum):
    QUERY = "query"
    PATH = "path"
    HEADER = "header"
    COOKIE = "cookie"
    BODY = "body"


@dataclass
class Parameter:
    name: str
    location: ParameterLocation
    required: bool
    schema_type: str = "string"
    description: str = ""
    default: Any = None
    example: Any = None
    enum_values: list[str] = field(default_factory=list)


@dataclass
class ResponseSpec:
    status_code: int
    description: str = ""
    schema: dict | None = None


@dataclass
class PerformanceSLA:
    """Expected performance thresholds from x-performance extension."""
    latency_p95_ms: float | None = None
    latency_p99_ms: float | None = None
    throughput_rps: float | None = None
    timeout_ms: float | None = None


@dataclass
class Endpoint:
    path: str
    method: HttpMethod
    operation_id: str | None = None
    summary: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    request_body_schema: dict | None = None
    responses: list[ResponseSpec] = field(default_factory=list)
    security: list[dict] = field(default_factory=list)
    performance_sla: PerformanceSLA | None = None

    @property
    def display_name(self) -> str:
        return self.operation_id or f"{self.method.value} {self.path}"


@dataclass
class ServerInfo:
    url: str
    description: str = ""


@dataclass
class ParsedSpec:
    title: str
    version: str
    description: str = ""
    spec_version: str = "3.0"
    servers: list[ServerInfo] = field(default_factory=list)
    endpoints: list[Endpoint] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    raw_spec: dict = field(default_factory=dict, repr=False)

    @property
    def base_url(self) -> str:
        if self.servers:
            return self.servers[0].url.rstrip("/")
        return "http://localhost"

    @property
    def endpoints_by_tag(self) -> dict[str, list[Endpoint]]:
        grouped: dict[str, list[Endpoint]] = {}
        for ep in self.endpoints:
            tags = ep.tags or ["default"]
            for tag in tags:
                grouped.setdefault(tag, []).append(ep)
        return grouped
