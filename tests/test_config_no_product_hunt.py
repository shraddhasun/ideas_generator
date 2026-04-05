"""Product Hunt is not an ingest source; config should not expose PH env fields."""

from ideas_generator.config import Settings


def test_settings_has_no_product_hunt_fields():
    assert "product_hunt_token" not in Settings.model_fields
    assert "product_hunt_posts_limit" not in Settings.model_fields
