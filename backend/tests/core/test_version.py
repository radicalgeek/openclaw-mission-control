from app.core.version import APP_NAME, APP_VERSION


def test_app_name_constant() -> None:
    # APP_NAME is derived from the branding config product_name slug
    assert isinstance(APP_NAME, str)
    assert len(APP_NAME) > 0
    assert APP_NAME == APP_NAME.lower()
    assert " " not in APP_NAME


def test_app_version_semver_format() -> None:
    parts = APP_VERSION.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
