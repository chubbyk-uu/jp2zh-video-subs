import re

from app_version import APP_BUILD, APP_VERSION, display_version


def test_application_version_and_build_are_visible_and_well_formed():
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", APP_VERSION)
    assert re.fullmatch(r"\d{4}\.\d{2}\.\d{2}-[0-9A-Za-z.-]+", APP_BUILD)
    assert display_version() == f"{APP_VERSION} ({APP_BUILD})"
