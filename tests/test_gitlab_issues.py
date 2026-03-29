from ideas_generator.connectors.gitlab_issues import fetch_gitlab_issues


def test_gitlab_public_project_returns_items():
    items = fetch_gitlab_issues(None, ["gitlab-org/gitlab"], per_project=2)
    assert len(items) >= 1
    assert items[0].source.startswith("gitlab:")
