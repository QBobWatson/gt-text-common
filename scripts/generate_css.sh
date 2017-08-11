#!/bin/bash

realpath=$(realpath "$0")
script_dir=$(dirname "$realpath")
cd "$script_dir/../.."
cd mathbook-assets

compass compile --time --force
