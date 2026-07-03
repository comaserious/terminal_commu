from textual.app import App


class FmkReaderApp(App[None]):
    TITLE = "FMK 해외축구"


def main() -> None:
    FmkReaderApp().run()
