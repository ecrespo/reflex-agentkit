"""Reflex config for the quickstart.

``AGENTKIT_MODEL=test`` swaps every PydanticAI model for ``TestModel``, so CI compiles
and drives the example with no network and no API key (REQ-030.2). The quickstart file
itself stays verbatim (API §2).
"""

import os

import reflex as rx

if os.getenv("AGENTKIT_MODEL") == "test":
    from pydantic_ai import models
    from pydantic_ai.models.test import TestModel

    models.infer_model = lambda *_args, **_kwargs: TestModel()

config = rx.Config(
    app_name="quickstart",
    telemetry_enabled=False,
    plugins=[rx.plugins.RadixThemesPlugin()],  # the agentkit components are Radix-based
    disable_plugins=[rx.plugins.SitemapPlugin],
)
