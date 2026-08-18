"""Argv and trace context, the two things a container gets wrong silently.

A host that defaults to loopback inside a container is a service nothing outside it can reach, and
a trace header that never goes out splits one run across two traces in Jaeger.
"""

from typing import Final

from orient.orchestrator import telemetry
from orient.orchestrator.main import DEFAULT_HOST, DEFAULT_PORT, parse


def test_the_defaults_bind_loopback_for_a_local_run() -> None:
    options: Final = parse([])
    assert options.host == DEFAULT_HOST
    assert options.port == DEFAULT_PORT


def test_the_container_can_bind_every_interface() -> None:
    options: Final = parse(["--host", "0.0.0.0", "--port", "8080"])  # noqa: S104  # what compose passes
    assert options.host == "0.0.0.0"  # noqa: S104  # what compose passes
    assert options.port == 8080


def test_the_outgoing_headers_are_a_mapping_even_with_no_span_open() -> None:
    """Called on every model request, so returning nothing has to be safe rather than an error."""
    assert dict(telemetry.outgoing()) == dict(telemetry.outgoing())


def test_there_is_no_trace_to_record_outside_a_span() -> None:
    assert telemetry.current_trace_id() is None


def test_a_span_is_a_context_manager_whether_or_not_a_provider_is_configured() -> None:
    with telemetry.span("phase.gather"):
        pass
