"""Start Story Studio:  python run.py   then open http://127.0.0.1:8000"""
import threading
import time
import webbrowser

import uvicorn

from app.config import APP_PASSWORD, HOST, PORT

if __name__ == "__main__":
    if HOST not in ("127.0.0.1", "localhost") and not APP_PASSWORD:
        print("WARNING: the app is reachable from other machines but APP_PASSWORD is empty. "
              "Anyone who finds it can spend your API credit. Set APP_PASSWORD in .env.")
    url = f"http://{'127.0.0.1' if HOST in ('0.0.0.0', '') else HOST}:{PORT}"
    if HOST in ("127.0.0.1", "localhost"):
        threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(url)), daemon=True).start()
    print(f"Story Studio running at {url}  (Ctrl+C to stop)")
    uvicorn.run("app.api:app", host=HOST, port=PORT, log_level="warning")
