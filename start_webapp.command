#!/bin/zsh
# Double-click this file in Finder, or run it from Terminal, to launch Open ECA.
cd -- "$(dirname "$0")"
exec python3 -m webapp.app "$@"
