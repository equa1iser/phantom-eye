"""
OpenTelemetry SDK setup for Phantom Eye.
Initialises traces, metrics, and logs — all exported via gRPC OTLP to SigNoz.
Falls back to (None, None) when OTEL packages are not installed so the server
runs normally outside Docker without any code changes.
"""

import os

try:
    from opentelemetry import trace, metrics
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
    from opentelemetry.instrumentation.flask import FlaskInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False


def setup_otel(service_name: str):
    """
    Configure and return (tracer, meter).
    Returns (None, None) when opentelemetry packages are not installed.
    Reads OTEL_EXPORTER_OTLP_ENDPOINT and OTEL_SERVICE_NAME from env.
    """
    if not _OTEL_AVAILABLE:
        return None, None

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    svc_name = os.getenv("OTEL_SERVICE_NAME", service_name)

    resource = Resource({SERVICE_NAME: svc_name})

    # ── Traces ────────────────────────────────────────────────────────────────
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(tracer_provider)

    # ── Metrics ───────────────────────────────────────────────────────────────
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, insecure=True),
        export_interval_millis=15_000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # ── Logs ──────────────────────────────────────────────────────────────────
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint, insecure=True))
    )
    set_logger_provider(logger_provider)
    # Bridges Python's standard logging module → OTLP log records.
    # Also injects trace_id/span_id into every log line format when inside a span.
    LoggingInstrumentor().instrument(set_logging_format=True)

    # ── Auto-instrumentation ──────────────────────────────────────────────────
    # FlaskInstrumentor global registration — instrument_app(app) called in server.py
    # after the Flask instance is constructed (two-phase pattern required).
    FlaskInstrumentor().instrument()

    # Wraps the requests library globally: covers push_cam_settings, push_led,
    # status sync on reconnect, and all 254 network discovery probes.
    RequestsInstrumentor().instrument()

    return trace.get_tracer(svc_name), metrics.get_meter(svc_name)
