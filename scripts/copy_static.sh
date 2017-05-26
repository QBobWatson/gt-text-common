#!/bin/bash

realpath=$(realpath "$0")
script_dir=$(dirname "$realpath")
cd "$script_dir/../.."

mkdir -p static
mkdir -p static/js
mkdir -p static/css
mkdir -p static/fonts

cp gt-text-common/css/*.css static/css
cp gt-text-common/js/*.js static/js

# cp lib/mathbook-assets/js/*.js static/js
# cp lib/mathbook-assets/js/lib/*.js static/js
cp lib/mathbook-assets/stylesheets/*.css static/css
cp lib/mathbook-assets/stylesheets/fonts/ionicons/fonts/* static/fonts

