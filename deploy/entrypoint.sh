#!/bin/sh
# The container's entrypoint.
#
#   serve   (default) start the server at once, and fetch and build California's file in the background when
#           the volume does not hold it yet. The server answers /api/health straight away; /api/ready answers
#           503 with the progress until the file is loaded.
#   test    the image's own checks: the programs, the fonts, the built pages and a server started in process.
#           It needs no network, no keys and no data.
#   fetch   only fetch and build the data, in the foreground, then stop.
set -eu
cd /app
case "${1:-serve}" in
  serve)
    python deploy/first_start.py &
    exec uvicorn khutlisa.server:app --host 0.0.0.0 --port "${PORT:-8000}" --log-level "${KHUTLISA_LOG_LEVEL:-info}"
    ;;
  test)
    exec python deploy/selftest.py
    ;;
  fetch)
    exec python deploy/first_start.py
    ;;
  *)
    exec "$@"
    ;;
esac
