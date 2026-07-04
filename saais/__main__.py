# -*- coding: utf-8 -*-
"""`python -m saais` — start the local advising system and open the browser."""
import threading
import webbrowser

from . import config as config_mod
from .app import create_app


def main():
    cfg = config_mod.load()
    host = cfg["server"]["host"]
    port = int(cfg["server"]["port"])
    url = f"http://{host}:{port}/"
    print(f"SAAIS running at {url}  (Ctrl+C to stop)")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    create_app().run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
