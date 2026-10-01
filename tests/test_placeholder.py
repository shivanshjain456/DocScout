"""Phase 0 placeholder: proves the test runner is wired. Replaced in the build phase."""


def test_environment_is_wired() -> None:
    import app

    assert app is not None
