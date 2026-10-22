"""Start the unchanged bot and read-only HTTP bridge in its existing container.

No schema migrations, event mutations, new Telegram pollers or separate DB copies.
The deployment base must match the currently deployed bot commit.
"""
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from bridge import Bridge,handler_for

def main():
    bridge=Bridge(os.environ['DB_PATH'],os.environ['DASHBOARD_BRIDGE_TOKEN'],os.environ.get('DASHBOARD_ANALYTICS_PATH'))
    child=[None]
    http=ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','8080'))),handler_for(bridge,lambda:child[0] is not None and child[0].poll() is None))
    child[0]=subprocess.Popen([sys.executable,str(Path(__file__).resolve().parents[1]/'app.py')])
    def stop(signum,frame):
        if child[0].poll() is None:child[0].send_signal(signum)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try:return child[0].wait()
    finally:
        http.shutdown();http.server_close()
        if child[0].poll() is None:
            child[0].terminate()
            try:child[0].wait(timeout=15)
            except subprocess.TimeoutExpired:child[0].kill();child[0].wait()
if __name__=='__main__':sys.exit(main())
