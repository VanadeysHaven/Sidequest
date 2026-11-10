#!/usr/bin/env bash
# Compile requirements.txt and requirements-dev.txt from pyproject.toml.
#
# pip-compile runs inside the same base image as the bot (python:3.12-slim, Linux),
# so the pins match what the Docker image installs, not the host OS.
# --no-emit-index-url keeps any (credentialed) index URL out of the lockfiles.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")/.."

IMAGE="python:3.12-slim"
root="$(pwd)"
user_args=()

case "$(uname -s)" in
    MINGW* | MSYS* | CYGWIN*)
        # Git Bash on Windows: give Docker a Windows path and stop MSYS from rewriting /work.
        root="$(cygpath -w "$root")"
        export MSYS_NO_PATHCONV=1
        ;;
    *)
        # Linux/macOS: write the output files as the calling user, not root.
        user_args=(--user "$(id -u):$(id -g)")
        ;;
esac

docker run --rm "${user_args[@]}" \
    -e HOME=/tmp \
    -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
    -v "$root:/work" \
    -w /work \
    "$IMAGE" \
    sh -euc '
        python -m venv /tmp/venv
        /tmp/venv/bin/pip install --quiet pip-tools
        /tmp/venv/bin/pip-compile --quiet --no-emit-index-url --strip-extras \
            -o requirements.txt pyproject.toml
        /tmp/venv/bin/pip-compile --quiet --no-emit-index-url --strip-extras --extra dev \
            -o requirements-dev.txt pyproject.toml
    '

echo "Wrote requirements.txt and requirements-dev.txt"
