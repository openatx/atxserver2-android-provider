#!/bin/bash
#

if test -d venv
then
	. venv/bin/activate
fi

exec python3 main.py "$@"
