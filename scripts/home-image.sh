#!/bin/bash
#
# Test and build the patched image for the Raspberry Pi. Needs only Docker:
# Poetry runs in throwaway containers, never on the host.
#
# Usage (normally through the Makefile):
#   scripts/home-image.sh test     run the unit tests in a python container
#   scripts/home-image.sh image    build the wheel and the linux/arm64 image
#   scripts/home-image.sh name     print the image name and exit
#
# The image is the upstream release tag this checkout is sitting on plus the
# local commits on top of it, tagged psa-car-controller:<tag>-local so it can
# never be confused with the official flobz/psa_car_controller images.
# Shipping and deploying it is done from the raspberry repository:
# ./pi release peugeot.
#
# The tests are not run on the host: macOS Pythons are often linked against
# the system SQLite, which is not built thread-safe, and the app refuses to
# open its database there. Downloads are cached in the psacc-test-cache volume.
#
# Environment overrides:
#   PLATFORM     target platform          (default: linux/arm64)
#   TEST_IMAGE   image the tests run in   (default: python:3.11-slim)

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
SRC_DIR="$(pwd)"

PLATFORM="${PLATFORM:-linux/arm64}"
TEST_IMAGE="${TEST_IMAGE:-python:3.11-slim}"

BASE_TAG="$(git describe --tags --abbrev=0 2>/dev/null || echo v0.0.0)"
COMMIT="$(git rev-parse --short HEAD)"
IMAGE="psa-car-controller:${BASE_TAG}-local"
# pyproject.toml always declares 0.0.0; the web UI shows the wheel's version.
PSACC_VERSION="${BASE_TAG#v}+local.${COMMIT}"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*" >&2; }
fail() { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

docker_ok() {
    command -v docker >/dev/null || fail "docker is not installed"
    docker info >/dev/null 2>&1 || fail "The Docker daemon is not reachable (is your Docker VM running?)"
    docker buildx version >/dev/null 2>&1 || fail "docker buildx is not available"
}

# The source is mounted read-only and copied inside the container, so neither a
# host .venv nor the files the tests leave behind end up in the checkout.
run_tests() {
    step "Running the unit tests ($TEST_IMAGE)"
    local log
    log="$(mktemp "${TMPDIR:-/tmp}/psacc-tests.XXXXXX")"
    if docker run --rm \
        -v "$SRC_DIR":/src:ro \
        -v psacc-test-cache:/root/.cache \
        -e PIP_DEFAULT_TIMEOUT=120 \
        -e PIP_RETRIES=10 \
        -e PYTHONWARNINGS=ignore \
        "$TEST_IMAGE" \
        bash -c '
            set -e
            cp -a /src /work && cd /work && rm -rf .venv dist
            pip install --quiet --root-user-action=ignore poetry
            poetry config virtualenvs.in-project true
            poetry install --no-interaction --quiet
            .venv/bin/python -m unittest
        ' >"$log" 2>&1; then
        grep -E '^Ran [0-9]+ tests' "$log" | sed 's/^/  /' >&2
        echo "  OK" >&2
        rm -f "$log"
    else
        grep -E '^(ERROR|FAIL):|^Ran [0-9]+ tests|^FAILED' "$log" | sed 's/^/  /' >&2 || true
        fail "Unit tests failed. Full output: $log"
    fi
}

# Like upstream's release workflow, set the real version with `poetry version`
# before building, then rename the wheel to the 0.0.0 filename the Dockerfile
# expects. The build runs on a copy, so pyproject.toml is left untouched.
build_image() {
    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
        echo "WARNING: uncommitted changes in $SRC_DIR will be baked into the image." >&2
    fi

    step "Building the Python wheel $PSACC_VERSION (containerised Poetry)"
    rm -rf dist && mkdir -p dist
    docker run --rm \
        -v "$SRC_DIR":/src:ro \
        -v "$SRC_DIR/dist":/out \
        -e PSACC_VERSION="$PSACC_VERSION" \
        python:3.11-slim \
        bash -c '
            set -e
            cp -a /src /work && cd /work && rm -rf .venv dist
            pip install --quiet --root-user-action=ignore poetry
            poetry version "$PSACC_VERSION"
            poetry build --format wheel
            cp dist/psa_car_controller-*-py3-none-any.whl /out/psa_car_controller-0.0.0-py3-none-any.whl
        ' >&2 || fail "Wheel build failed"
    [ -f dist/psa_car_controller-0.0.0-py3-none-any.whl ] || fail "Expected wheel not found in dist/"

    step "Building $IMAGE for $PLATFORM"
    docker buildx build --platform "$PLATFORM" --tag "$IMAGE" --load --file Dockerfile . >&2 \
        || fail "Image build failed"

    local arch
    arch="$(docker image inspect "$IMAGE" --format '{{.Os}}/{{.Architecture}}')"
    [ "$arch" = "$PLATFORM" ] || fail "Built $arch but wanted $PLATFORM"
    echo "  built $IMAGE ($arch, version $PSACC_VERSION)" >&2
}

case "${1:-}" in
    test)  docker_ok; run_tests ;;
    image) docker_ok; build_image ;;
    name)  echo "$IMAGE" ;;
    *)     echo "Usage: $0 test|image|name" >&2; exit 2 ;;
esac
