#!/bin/bash
# The paper's evaluation campaign, one experiment at a time on a quiet machine.
#   GEM_PATH=... evaluation/campaign.sh      (STEPS="gc nursery" for a subset)
# Logs go to $CAMPAIGN_DIR; results to evaluation/results as usual.
R=$(cd "$(dirname "$0")/.." && pwd)
T=${CAMPAIGN_DIR:-$R/evaluation/results/campaign-$(date -u +%Y%m%dT%H%M%SZ)}
mkdir -p "$T"
cd "$R" || exit 1
# Absolute binary paths in gccheck, so the watchdog can tell ours apart.
export BIN=$R
# The paper ran without TruffleRuby/JRuby; keep the engine set identical.
export EVAL_OPTIONAL_ENGINES=${EVAL_OPTIONAL_ENGINES:-0}
GATE_LOAD=${GATE_LOAD:-3.0}
GATE_TIMEOUT=${GATE_TIMEOUT:-7200}
STEPS=${STEPS:-"gc nursery nohook crossing boundary coverage performance \
mechanisms memory delegation ablate stress specstress"}

stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }

load5() {
  if [ -r /proc/loadavg ]; then awk '{print $2}' /proc/loadavg
  else sysctl -n vm.loadavg | awk '{print $3}'; fi
}

gate() {
  local start now l5
  start=$(date +%s)
  while :; do
    l5=$(load5)
    if awk "BEGIN{exit !($l5 < $GATE_LOAD)}"; then
      echo "$(stamp) GATE-PASS $1 load5=$l5" >> "$T/gate-log.txt"; return
    fi
    now=$(date +%s)
    if [ $((now - start)) -ge "$GATE_TIMEOUT" ]; then
      echo "$(stamp) GATE-TIMEOUT $1 load5=$l5 proceeding FLAG" \
        >> "$T/gate-log.txt"
      return
    fi
    echo "$(stamp) gate-wait $1 load5=$l5" >> "$T/gate-log.txt"
    sleep 60
  done
}

# Hung rpyyarv children that survived their alarm (nice 19 ones are not ours).
reap() {
  ps -Ao pid=,nice=,command= | awk -v r="$R/rpyyarv" \
    '$2 < 19 && index($3, r) == 1 { print $1 }' | while read -r pid; do
    echo "$(stamp) REAP $pid $(ps -o command= -p "$pid" | cut -c1-160)" \
      >> "$T/campaign.log"
    kill -9 "$pid"
  done
}

# macOS crash reports: a SIGSEGV the harness mislabels still leaves one.
REPORTS=$HOME/Library/Logs/DiagnosticReports
reports() { ls "$REPORTS" 2>/dev/null | grep -E '^rpyyarv.*\.ips$' | sort; }

# Pid, launch time and the crashed thread's top frames of one .ips file.
describe() {
  ruby --disable-gems -rjson -e '
    head, body = File.read(ARGV[0]).split("\n", 2)
    b = JSON.parse(body) rescue {}
    t = (b["threads"] || [])[b["faultingThread"].to_i] || {}
    names = (b["usedImages"] || []).map { |i| i["name"] }
    noise = /\A(_?_?pthread_kill|raise|abort|_sigtramp|sig\w+|
               ruby_default_signal|rb_bug\w*|rb_vm_bugreport)\z/x
    top = (t["frames"] || []).map do |f|
      f["symbol"] || "#{names[f["imageIndex"].to_i]}+#{f["imageOffset"]}"
    end.grep_v(noise).first(6)
    puts [b["pid"], b["parentProc"], b["procLaunch"],
          b.dig("exception", "signal"), top.join(" < ")].join(" | ")
  ' "$REPORTS/$1"
}

step() {
  local name=$1; shift
  gate "$name"
  local before new
  before=$(reports)
  echo "$(stamp) START $name: $*" >> "$T/campaign.log"
  "$@" > "$T/step-$name.log" 2>&1
  local rc=$?
  new=$(comm -13 <(echo "$before") <(reports))
  for f in $new; do
    echo "$(stamp) $name $f $(describe "$f")" >> "$T/crash-reports.txt"
  done
  echo "$(stamp) END $name rc=$rc crash_reports=$(echo -n "$new" | grep -c .)" \
    >> "$T/campaign.log"
  reap
}

# Alarm-surviving children (> 15 min; every run has a 600 s alarm).
watchdog() {
  while :; do
    ps -Ao pid=,nice=,etime=,command= | awk -v r="$R/rpyyarv" '
      $2 < 19 && index($4, r) == 1 {
        n = split($3, a, /[-:]/); s = a[n] + 60 * a[n-1]
        if (n >= 3) s += 3600 * a[n-2]; if (n == 4) s += 86400 * a[1]
        if (s > 900) print $1 }' | while read -r pid; do
      echo "$(stamp) WATCHDOG-KILL $pid" \
        "$(ps -o command= -p "$pid" | cut -c1-160)" >> "$T/campaign.log"
      kill -9 "$pid"
    done
    sleep 60
  done
}
watchdog &
WD=$!
trap 'kill $WD' EXIT

latest() { ls -td evaluation/results/*-"$1"-* | head -1; }

DELEGATION_FILTERS="--suite ruby-bench --filter sequel --filter mail \
--filter rack --filter railsbench --filter shipit --filter lobsters \
--filter erubi-rails --filter activerecord --filter hexapdf --filter rubocop \
--filter fluentd --filter ruby-lsp"

for s in $STEPS; do
  case $s in
    gc) step gc make eval EVAL=gc EVALFLAGS="16384 4096 1024" ;;
    nursery) step nursery env EVAL_TRIALS=20 make eval EVAL=nursery \
      EVALFLAGS="evaluation/nursery-hexapdf.rb 1073741824 4194304 131072" ;;
    nohook) step nohook make eval EVAL=ablate EVALFLAGS="gc-no-hook" ;;
    crossing) step crossing make eval EVAL=crossing ;;
    boundary) step boundary make eval EVAL=boundary EVALFLAGS="--suite all" ;;
    coverage) step coverage make eval EVAL=coverage EVALFLAGS="--suite all" ;;
    performance) step performance make eval EVAL=performance \
      EVALFLAGS="--suite all --procs 3 --refresh-inventory" ;;
    mechanisms) step mechanisms make eval EVAL=mechanisms \
      EVALFLAGS="--suite all --performance $R/$(latest performance)/raw.json" ;;
    memory) step memory make eval EVAL=memory EVALFLAGS="--suite all" ;;
    delegation) step delegation make eval EVAL=delegation \
      EVALFLAGS="$DELEGATION_FILTERS" ;;
    ablate) step ablate make eval EVAL=ablate ;;
    stress) step stress make eval EVAL=stress \
      EVALFLAGS="--timeout 600 --jobs 4" ;;
    specstress)
      SE=(
        "none|"
        "a-autocompact|--env RUBYOPT=-r$R/test/autocompact.rb \
--env RUBY_GC_HEAP_OLDOBJECT_LIMIT_FACTOR=0.01"
        "b-dispatch-compact|--env RPYYARV_GC_STRESS=compact \
--env RPYYARV_GC_STRESS_EVERY=4096"
        "c-timer-compact|--env RUBYOPT=-r$R/test/compact_prelude.rb"
        "d-dispatch-full|--env RPYYARV_GC_STRESS=1 \
--env RPYYARV_GC_STRESS_EVERY=4096"
      )
      for e in "${SE[@]}"; do
        n=${e%%|*}; f=${e#*|}
        # shellcheck disable=SC2086
        step "spec-$n" ruby --disable-gems evaluation/spec.rb --suite language \
          --suite core --suite capi --timeout 120 --jobs 4 $f \
          --out "$R/evaluation/results/$(date -u +%Y%m%dT%H%M%SZ)-spec-$n"
      done ;;
    *) echo "unknown step $s" >&2; exit 1 ;;
  esac
done
echo "$(stamp) CAMPAIGN-DONE" >> "$T/campaign.log"
