#!/bin/sh
S=/private/tmp/claude-501/-Users-yizawa-src-github-com-3tty0n-ruby-rpyyarv/6cc8f810-eb5c-4004-a459-b8a6c01914e2/scratchpad
for n in "$@"; do
  echo "===== $n"
  grep -v 'not loaded' $S/logs/$n.log | grep -v '^\[rpyyarv\]   cruby ' | head -8
done
