"""Tracing. Sends OpenTelemetry spans to Application Insights when a connection string is set;
otherwise spans are no-ops and only standard logging is used."""

from __future__ import annotations

import logging
from contextlib import contextmanager

from procurement_agent.config import get_settings

_configured = False


def configure() -> None:
    global _configured
    if _configured:
        return
    _configured = True
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    conn = get_settings().applicationinsights_connection_string
    if conn:
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor

            configure_azure_monitor(connection_string=conn)
        except ImportError:
            logging.getLogger(__name__).warning("Install the [azure] extra to export telemetry to App Insights")


@contextmanager
def span(name: str, **attributes):
    try:
        from opentelemetry import trace
    except ImportError:
        yield None
        return
    with trace.get_tracer("procurement_agent").start_as_current_span(name) as s:
        for k, v in attributes.items():
            s.set_attribute(k, v)
        yield s
