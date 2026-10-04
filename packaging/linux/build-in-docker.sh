#!/bin/sh
# Release build for Linux: compiles inside Ubuntu 22.04 (glibc 2.35) so the
# AppImage also runs on 22.04 and newer, then wraps it on the host.
# Usage: packaging/linux/build-in-docker.sh   (needs docker; output in dist/)
set -eu
cd "$(dirname "$0")/../.."
docker run --rm -v "$PWD":/src -w /src ubuntu:22.04 sh -c '
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null
apt-get install -y -qq python3 python3-venv python3-pip binutils libgl1 libegl1 libxkbcommon0 \
  libxkbcommon-x11-0 libfontconfig1 libdbus-1-3 libglib2.0-0 libxcb-cursor0 libxcb-icccm4 \
  libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 \
  libxcb-xinerama0 libxcb-xkb1 >/dev/null
python3 -m venv /venv
/venv/bin/pip install -q -U pip >/dev/null
/venv/bin/pip install -q -r requirements-build.txt
/venv/bin/python simplebrain_core.py
/venv/bin/pyinstaller --noconfirm --clean packaging/simplebrain.spec
chown -R '"$(id -u):$(id -g)"' /src/build /src/dist
'
sh packaging/linux/build-appimage.sh
