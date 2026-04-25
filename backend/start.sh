#!/bin/sh
set -e

dotmd mcp --transport streamable-http --host 0.0.0.0 --port 8080 &
exec dotmd serve --host 0.0.0.0
