import memray
import datetime
import os

# NB: preload_app is True in the gunicorn config, so this works.
now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
tracker = memray.Tracker(f'/heap/output/{now}-{os.getpid()}.bin', follow_fork=True)
tracker.__enter__() # ...and we are live!

from checker import app
