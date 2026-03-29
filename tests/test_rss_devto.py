from ideas_generator.connectors.devto import fetch_devto_articles
from ideas_generator.connectors.rss_feeds import fetch_rss_feeds


def test_devto_returns_items():
    items = fetch_devto_articles(None, limit=2)
    assert len(items) >= 1
    assert items[0].source == "devto"
    assert items[0].url.startswith("http")


def test_rss_hnrss():
    # Lobsters default may return HTML in some environments; use hnrss for stable XML.
    items = fetch_rss_feeds(["https://hnrss.org/frontpage"], max_per_feed=3)
    assert len(items) >= 1
    assert items[0].source.startswith("rss:")
