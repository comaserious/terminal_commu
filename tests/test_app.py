from fmk_reader.app import FmkReaderApp


def test_app_has_expected_title() -> None:
    app = FmkReaderApp()
    assert app.TITLE == "FMK 해외축구"
