from ideas_generator.filters import is_healthcare_related


def test_non_healthcare_business():
    assert not is_healthcare_related(
        "Our Shopify store checkout is broken on mobile",
        "https://reddit.com/r/ecommerce/foo",
    )


def test_healthcare_blocked():
    assert is_healthcare_related(
        "HIPAA compliance for our EHR integration with the hospital system",
        "https://example.com",
    )


def test_keyword_in_url():
    assert is_healthcare_related("general discussion", "https://reddit.com/r/medicine/xyz")
