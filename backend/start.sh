#!/bin/sh
set -e

exec dotmd mcp --transport streamable-http --host 0.0.0.0 --port 8080
