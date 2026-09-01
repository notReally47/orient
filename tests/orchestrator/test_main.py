"""Trace context, which a container gets wrong silently.

A trace header that never goes out splits one run across two traces in Jaeger, and a span that
raises when no provider is configured takes the run down with it. Argv is shared by all three
entry points and is covered in `tests/test_serving.py`.
"""

from orient.orchestrator import telemetry


def test_the_outgoing_headers_are_a_mapping_even_with_no_span_open() -> None:
    """Called on every model request, so returning nothing has to be safe rather than an error."""
    assert dict(telemetry.outgoing()) == dict(telemetry.outgoing())


def test_there_is_no_trace_to_record_outside_a_span() -> None:
    assert telemetry.current_trace_id() is None


def test_a_span_records_nothing_and_raises_nothing_when_no_provider_is_configured() -> None:
    """The exporter is optional, so every span in the run passes through this path when Jaeger is
    not wired up. Entering it must be inert rather than an error."""
    with telemetry.span("phase.gather"):
        inside = telemetry.current_trace_id()

    assert inside is None
    assert telemetry.current_trace_id() is None
