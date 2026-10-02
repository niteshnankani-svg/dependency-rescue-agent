#!/bin/sh
set -eu
RESCUE_EVAL_MUTATIONS=1 python -m pytest -q
python -m compileall -q rescue scripts
# Set BUILD_IMAGES=1 on a runner with Docker; model/data evaluation is a separate job.
if [ "${BUILD_IMAGES:-0}" = 1 ]; then
  docker build --target api -t dependency-rescue-api:ci .
  docker build --target executor -t dependency-rescue-executor:ci .
fi
