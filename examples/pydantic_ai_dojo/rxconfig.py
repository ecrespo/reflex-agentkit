"""Reflex config for the PydanticAI Dojo. ``AGENTKIT_MODEL`` picks the model (see README)."""

import reflex as rx

config = rx.Config(
    app_name="pydantic_ai_dojo",
    telemetry_enabled=False,
    plugins=[rx.plugins.RadixThemesPlugin()],  # the agentkit components are Radix-based
    disable_plugins=[rx.plugins.SitemapPlugin],
)
