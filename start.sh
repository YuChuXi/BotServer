#!/usr/bin/bash

activate_outer_venv() {
    local dir="$PWD"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/.venv/bin/activate" ]; then
            . "$dir/.venv/bin/activate"
            echo "Activated venv: $dir/.venv"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    return 1
}

activate_outer_venv

nb run