#!/bin/bash

realpath=$(realpath "$0")
script_dir=$(dirname "$realpath")
cd "$script_dir/../.."
cd lib/mathbook-assets

compass compile --time --force
"$script_dir/copy_static.sh"
