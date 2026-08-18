"""Tracing for the orchestrator.

Configured here rather than through environment magic, so the exporter's endpoint is one setting
and the trace context the proxy joins comes from one function. Everything else in the orchestrator
takes a span factory as an argument, which is what keeps a test free of a tracer.
"""

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import Final

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import inject
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

TRACES_PATH: Final = "/v1/traces"
TRACE_ID_WIDTH: Final = 32


def configure(service_name: str, endpoint: str) -> None:
    provider: Final = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}{TRACES_PATH}")))
    trace.set_tracer_provider(provider)


@contextmanager
def span(name: str) -> Generator[None]:
    with trace.get_tracer(__name__).start_as_current_span(name):
        yield


def outgoing() -> Mapping[str, str]:
    """The headers that put the proxy's spans in the same trace as the phase that called it."""
    carrier: Final[dict[str, str]] = {}
    inject(carrier)
    return carrier


def current_trace_id() -> str | None:
    """Stored on the run row, which is what makes a trace in Jaeger correspond to something queryable."""
    context: Final = trace.get_current_span().get_span_context()
    return format(context.trace_id, f"0{TRACE_ID_WIDTH}x") if context.is_valid else None
