#!/usr/bin/env python3
"""Run benchmark/*.rb on every available engine and compare best-of-N wall times.

Every benchmark prints a checksum, so a run is only reported when all engines
agree on stdout; disagreement is flagged as MISMATCH and exits nonzero.
"""

import argparse
import os
import platform
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOP = os.path.dirname(ROOT)
BUILD = os.environ.get("RPYYARV_BUILD", os.path.join(TOP, "build"))

# Shared-library lookup for the CRuby build tree the engines link against.
LIBVAR = "DYLD_LIBRARY_PATH" if platform.system() == "Darwin" else "LD_LIBRARY_PATH"

ENGINES = [
    ("cruby", [os.path.join(BUILD, "ruby"), "--disable-gems"]),
    ("cruby+yjit", [os.path.join(BUILD, "ruby"), "--yjit", "--disable-gems"]),
    ("cruby+zjit", [os.path.join(BUILD, "ruby"), "--zjit", "--disable-gems"]),
    ("rpyyarv", [os.path.join(ROOT, "rpyyarv")]),
    ("rpyyarv-jit", [os.path.join(ROOT, "rpyyarv-jit")]),
]

CRUBY_ENGINES = ("cruby", "cruby+yjit", "cruby+zjit")


def env_for_run():
    env = dict(os.environ)
    env[LIBVAR] = BUILD + os.pathsep + env.get(LIBVAR, "")
    return env


def run_once(argv, script, env):
    start = time.perf_counter()
    proc = subprocess.run(argv + [script], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env)
    elapsed = time.perf_counter() - start
    if proc.returncode != 0:
        # The boot path always warns about unloaded default gems; drop that noise.
        err = "\n".join(l for l in proc.stderr.decode("utf-8", "replace").splitlines()
                        if "not loaded" not in l).strip()
        return None, elapsed, "exit %d: %s" % (proc.returncode, err[-300:])
    return proc.stdout.decode("utf-8", "replace").strip(), elapsed, None


def flags_supported(argv, env):
    """A JIT flag the build lacks makes ruby exit nonzero before running anything."""
    proc = subprocess.run(argv + ["-e", ""], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, env=env)
    return proc.returncode == 0


def fmt(value):
    return "%.3f" % value if value is not None else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3, help="repetitions per engine")
    ap.add_argument("--filter", default="", help="only benchmarks whose name contains this")
    args = ap.parse_args()

    bench_dir = os.path.join(ROOT, "benchmark")
    scripts = sorted(f for f in os.listdir(bench_dir) if f.endswith(".rb"))
    scripts = [f for f in scripts if args.filter in f]
    if not scripts:
        print("no benchmarks matched", file=sys.stderr)
        return 1

    env = env_for_run()
    engines = []
    for name, argv in ENGINES:
        if not (os.path.exists(argv[0]) and os.access(argv[0], os.X_OK)):
            print("note: skipping %s (%s not found)" % (name, argv[0]))
        elif not flags_supported(argv, env):
            print("note: skipping %s (flags unsupported by this build)" % name)
        else:
            engines.append((name, argv))
    if not engines:
        print("no engines available", file=sys.stderr)
        return 1

    rows = []
    failed = False

    for script in scripts:
        path = os.path.join(bench_dir, script)
        name = script[:-3]
        times, outputs, notes = {}, {}, []
        for ename, argv in engines:
            best = None
            for _ in range(args.reps):
                out, elapsed, err = run_once(argv, path, env)
                if err is not None:
                    notes.append("%s CRASH (%s)" % (ename, err))
                    best = None
                    break
                outputs.setdefault(ename, out)
                if outputs[ename] != out:
                    notes.append("%s UNSTABLE OUTPUT across reps" % ename)
                best = elapsed if best is None else min(best, elapsed)
            times[ename] = best
            if best is None:
                failed = True

        distinct = set(outputs.values())
        if len(distinct) > 1:
            failed = True
            notes.append("MISMATCH: " + "; ".join(
                "%s=%r" % (e, o) for e, o in sorted(outputs.items())))
        checksum = sorted(distinct)[0] if len(distinct) == 1 else "?"
        rows.append((name, checksum, times, notes))
        print("ran %-14s checksum=%s%s" % (name, checksum,
                                           "  [" + " | ".join(notes) + "]" if notes else ""))

    print()
    headers = ["benchmark"] + [e for e, _ in engines] + ["jit/cruby*"]
    table = []
    for name, checksum, times, _ in rows:
        cells = [name] + [fmt(times.get(e)) for e, _ in engines]
        # Ratio is against the fastest CRuby variant, whichever engine that is.
        best_c = min([times[e] for e in CRUBY_ENGINES if times.get(e)] or [None])
        j = times.get("rpyyarv-jit")
        cells.append("%.2fx" % (j / best_c) if best_c and j else "-")
        table.append(cells)

    widths = [max(len(r[i]) for r in [headers] + table) for i in range(len(headers))]
    line = lambda r: "  ".join(
        c.ljust(widths[i]) if i == 0 else c.rjust(widths[i]) for i, c in enumerate(r))
    print(line(headers))
    print("  ".join("-" * w for w in widths))
    for r in table:
        print(line(r))
    print("\nbest of %d reps, seconds; cruby* = fastest CRuby variant per row" % args.reps)

    if failed:
        print("\nFAILED: see notes above", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
