"""mousemap: interface gráfica de configuração."""

import sys

from gi.repository import Adw, Gio

from .. import APP_ID
from .window import MainWindow


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        window = self.props.active_window or MainWindow(self)
        window.present()


def main():
    return Application().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
