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
from release_backup import release_archive

def main():
    bridge=Bridge(os.environ['DB_PATH'],os.environ['DASHBOARD_BRIDGE_TOKEN'],os.environ.get('DASHBOARD_ANALYTICS_PATH'))
    child=[None]
    entry=os.environ.get('DASHBOARD_BOT_ENTRY','app.py')
    if entry not in ('app.py','finance_preview.py'):
        raise ValueError('Unsupported bot entry point')
    archive=None
    backup_token=os.environ.get('RELEASE_BACKUP_TOKEN')
    if entry=='app.py' and os.environ.get('RAILWAY_ENVIRONMENT_NAME')=='production':
        if not backup_token or len(backup_token)<32:
            raise ValueError('A separate release backup secret is required')
        archive=release_archive(os.environ['DB_PATH'],'/data/release-backups')
    http=ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','8080'))),handler_for(bridge,lambda:child[0] is not None and child[0].poll() is None,backup_path=archive,backup_token=backup_token))
    child[0]=subprocess.Popen([sys.executable,str(Path(__file__).resolve().parents[1]/entry)])
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
