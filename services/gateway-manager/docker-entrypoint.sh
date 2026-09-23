#!/bin/sh
# Starts the one central Nginx installation this service manages, then runs
# the FastAPI app in the foreground. `nginx -t` runs first so a broken image
# build (bad static config) fails fast and loud instead of silently starting
# an API that reports healthy while Nginx isn't actually running.
set -e

nginx -t
nginx

exec "$@"
