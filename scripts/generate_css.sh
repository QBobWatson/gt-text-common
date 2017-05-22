#!/bin/bash

script_dir=$(dirname "$(realpath $0)")
cd "$script_dir/../.."
cd lib/mathbook-assets

cat <<EOF >scss/mathbook-gt.scss
\$mathbook-primary:#eab72c;
\$mathbook-primary:darken(\$mathbook-primary, 15%);
\$mathbook-secondary:#888;
@import "mathbook";
EOF

compass compile --time --force
