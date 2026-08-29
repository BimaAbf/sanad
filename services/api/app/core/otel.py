"""OpenTelemetry wiring.

Instrumentation is unconditional; *export* is conditional. With no OTLP
endpoint configured the SDK still creates spans (so trace ids exist for log
correlation) but ships nothing anywhere. Observability must never be a reason
the app fails to start.
"""

from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings

_configured = False


def configure_tracing(settings: Settings) -> None:
    global _configured
    if _configured:
        return
    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "deployment.environment": str(settings.environment),
        }
    )
    provider = TracerProvider(resource=resource)
    if settings.otel_exporter_otlp_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
        )
    trace.set_tracer_provider(provider)
    _configured = True


def instrument_app(app: FastAPI, *, engine: AsyncEngine | None = None) -> None:
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,health/ready")
    RedisInstrumentor().instrument()
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
