#!/bin/bash

script_dir=$(dirname "$(realpath $0)")
cd "$script_dir/../.."

mkdir -p static
mkdir -p static/js
mkdir -p static/css
mkdir -p static/fonts

cp GTcommon/css/mathbook-add-on.css static/css

cp lib/mathbook-assets/js/*.js static/js
cp lib/mathbook-assets/js/lib/*.js static/js
cp lib/mathbook-assets/stylesheets/*.css static/css
cp lib/mathbook-assets/stylesheets/fonts/ionicons/fonts/* static/fonts

