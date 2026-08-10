#!/bin/sh
# usage: run1.sh <engine> <benchmark.rb> ; engine: rpyyarv | rpyyarv-jit | cruby | yjit
S=/private/tmp/claude-501/-Users-yizawa-src-github-com-3tty0n-ruby-rpyyarv/6cc8f810-eb5c-4004-a459-b8a6c01914e2/scratchpad
R=/Users/yizawa/src/github.com/3tty0n/ruby/.claude/worktrees/agent-acc9bb32eabad7ee8/rpyyarv
BUILD=/Users/yizawa/src/github.com/3tty0n/ruby/build
export DYLD_LIBRARY_PATH=$BUILD
export RUBYLIB=$S/yjb-shim
export RPYYARV_COVERAGE=1
case "$1" in
  rpyyarv) CMD="$R/rpyyarv" ;;
  rpyyarv-jit) CMD="$R/rpyyarv-jit" ;;
  cruby) CMD="$BUILD/ruby --disable-gems" ;;
  yjit) CMD="$BUILD/ruby --disable-gems --yjit" ;;
  *) echo "unknown engine $1" >&2; exit 2 ;;
esac
shift
exec $CMD "$@"
