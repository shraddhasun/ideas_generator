from ideas_generator.connectors.github_issues import fetch_github_issues


def test_github_public_repo_returns_items():
    items = fetch_github_issues(None, ["octocat/Hello-World"], per_repo=2)
    assert len(items) >= 1
    assert items[0].source.startswith("github:")
    assert "github.com" in items[0].url
