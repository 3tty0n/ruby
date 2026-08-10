#!/bin/sh
S=/private/tmp/claude-501/-Users-yizawa-src-github-com-3tty0n-ruby-rpyyarv/6cc8f810-eb5c-4004-a459-b8a6c01914e2/scratchpad
for n in `grep '^NATIVE' $S/inventory.txt | cut -f2`; do
  printf '%-22s %s\n' "$n" "`grep -m1 'sends: rpyyarv' $S/blogs/$n.rpyyarv-jit.1.log`"
done
