"""HA fixtures with actual temporary disk storage, not a mocked Store."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.solbuddy_access.models import Action, Grant, LightPolicy

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture
def hass_storage():
    """Override the plugin's mocked Store so persistence tests exercise real IO."""
    return {}


@pytest.fixture
def hass_config_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Allow HA to discover this local custom integration."""


@pytest.fixture
def now():
    return datetime(2026, 10, 19, 12, tzinfo=UTC)


@pytest.fixture
def policy():
    return LightPolicy(
        "light.guest_room",
        "registry-1",
        "integration-1",
        frozenset(Action),
        brightness_min=20,
        brightness_max=180,
        turn_on_brightness=100,
    )


@pytest.fixture
def grant(now, policy):
    return Grant.create(
        guest_display_name="Guest A",
        created_by="owner",
        now=now,
        starts_at=now,
        expires_at=now + timedelta(hours=72),
        policies=(policy,),
    )
