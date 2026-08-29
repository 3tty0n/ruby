TOP     := $(abspath $(CURDIR)/..)
BUILD   := $(TOP)/build
ARCHDIR := $(patsubst %/ruby/config.h,%,\
             $(firstword $(wildcard $(BUILD)/.ext/include/*/ruby/config.h)))
OS      := $(shell uname -s)
# The cruby reference needs this to find lib/ and the built extensions; rpyyarv derives the same set from RPYYARV_BUILD.
UNINSTALLED_RUBYLIB := $(TOP)/lib:$(BUILD)/.ext/common:$(BUILD):$(BUILD)/.ext/$(notdir $(ARCHDIR))

CFLAGS  += -Wall -Wextra -g -O0
# $(TOP) and $(BUILD) are on the path for shape.h and the generated id.h.
CPPFLAGS+= -I$(TOP)/include -I$(ARCHDIR) -I$(CURDIR) -I$(TOP) -I$(BUILD)
LDFLAGS += -L$(BUILD) -Wl,-rpath,$(BUILD)

ifeq ($(OS),Darwin)
SOEXT   := dylib
SOVER   := $(patsubst $(BUILD)/libruby.%.dylib,%,$(firstword $(wildcard $(BUILD)/libruby.*.dylib)))
LIBRUBY := $(BUILD)/libruby.$(SOVER).dylib
LDLIBS  += -lruby.$(SOVER)
SHARED  := -dynamiclib
LIBPATH := DYLD_LIBRARY_PATH=$(BUILD)
LDFLAGS += -Wl,-headerpad_max_install_names
INSTNAME := $(shell otool -D $(LIBRUBY) 2>/dev/null | tail -1)

define fix_install_name
	@[ -e "$(1)" ] || exit 0; \
	 cur=`otool -L "$(1)" | awk '/libruby\..*\.dylib/ { print $$1; exit }'`; \
	 if [ -n "$$cur" ] && [ "$$cur" != "$(LIBRUBY)" ]; then \
	   install_name_tool -change "$$cur" "$(LIBRUBY)" "$(1)"; \
	 fi
endef
else
SOEXT   := so
LIBRUBY := $(firstword $(wildcard $(BUILD)/libruby.so))
LDLIBS  += -lruby
LDFLAGS += -Wl,-rpath,'$$ORIGIN'
SHARED  := -shared -fPIC
LIBPATH := LD_LIBRARY_PATH=$(BUILD)
define fix_install_name
endef
endif

SHIM    := librpyyarv_boot.$(SOEXT)
PYPY    ?= ./pypy
RUBY_BENCH ?= $(CURDIR)/ruby-bench
# AWFY needs set/subclass_compatible.rb from the source tree, or deltablue dies.
AWFY_RUBYLIB ?= $(TOP)/lib
PYTHON  ?= python3
PYTHONPATH ?= $(TOP)
RPYTHON ?= python2 $(PYPY)/rpython/bin/rpython
RUBY    ?= $(BUILD)/ruby
# Run benchmark drivers with the same local CRuby build as their child jobs.
# This avoids accidentally selecting a system or rbenv Ruby from PATH.
RUBY_CMD ?= $(RUBY)
CRUBY_CONFIGURE_ARGS ?=
CRUBY_JIT_CONFIGURE_ARGS ?= --enable-yjit --enable-zjit
# rustup's rustc/cargo are often missing from make's PATH.
export PATH := $(HOME)/.cargo/bin:$(PATH)

# A tight malloc limit fires real GCs inside compiled traces; GC_STRESS cannot,
# it escapes the vable and aborts tracing.
GCLIMIT   ?= 16384
GCTIMEOUT ?= 60

.PHONY: all test microbench awfy bench bench-viz eval eval-test setup setup-gems
.PHONY: bench-bootstrap bench-setup
.PHONY: gccheck ractorcheck build build-cruby build-interp build-jit link clean
.PHONY: pypy-patch

build: build-cruby build-interp build-jit

build-cruby:
	@command -v rustc >/dev/null 2>&1 || { \
	  echo "error: rustc is required to build CRuby with YJIT/ZJIT"; \
	  echo "install: https://www.rust-lang.org/tools/install"; \
	  exit 1; \
	}
	mkdir -p "$(BUILD)"
	cd "$(BUILD)" && "$(TOP)/configure" --enable-shared \
	  $(CRUBY_JIT_CONFIGURE_ARGS) $(CRUBY_CONFIGURE_ARGS)
	$(MAKE) -C "$(BUILD)"

link: $(SHIM)

$(SHIM): boot_shim.c boot_shim.h
	@test -n "$(ARCHDIR)" || { echo "ERROR: build CRuby first (--enable-shared)"; exit 1; }
	@test -n "$(LIBRUBY)" || { \
	  echo "ERROR: $(BUILD) has no shared Ruby library; run 'make build-cruby'"; \
	  exit 1; \
	}
	$(CC) $(CFLAGS) $(CPPFLAGS) $(SHARED) -o $@ boot_shim.c $(LDFLAGS) $(LDLIBS)
	$(call fix_install_name,$@)

# TODO: test_interp/test_debug/test_loader are parked on this branch; they
# assert on the W_* object model the VALUE-direct rewrite replaced.
test: $(SHIM)
	RPYYARV_BUILD=$(BUILD) $(PYTHON) test/test_boot_ctypes.py $(SCRIPT)
	RPYYARV_BUILD=$(BUILD) $(PYTHON) test/test_gc_ctypes.py

microbench:
	RPYYARV_BUILD=$(BUILD) RUBYLIB=$(UNINSTALLED_RUBYLIB) $(LIBPATH) $(RUBY_CMD) scripts/microbench.rb $(MICROBENCHFLAGS)

# AWFY steady state. AWFY_RUBYLIB supplies set/subclass_compatible.rb, which
# CRuby 4.0's Set.inherited hook needs before deltablue will load anywhere.
awfy:
	RPYYARV_BUILD=$(BUILD) AWFY_RUBYLIB=$(AWFY_RUBYLIB) RUBYLIB=$(UNINSTALLED_RUBYLIB) \
	  $(LIBPATH) $(RUBY_CMD) scripts/awfy.rb $(AWFYFLAGS)

# Both suites through one driver; RUBY_BENCH points at the ruby-bench checkout.
bench:
	RPYYARV_BUILD=$(BUILD) AWFY_RUBYLIB=$(AWFY_RUBYLIB) RUBY_BENCH=$(RUBY_BENCH) \
	  BENCH_GEMS=$(BENCH_GEMS) RUBYLIB=$(UNINSTALLED_RUBYLIB) \
	  $(LIBPATH) $(RUBY_CMD) scripts/bench.rb $(BENCHFLAGS)

# One entry point for every paper measurement; EVAL names the sub-experiment.
EVAL ?= doctor
eval:
	RPYYARV_BUILD=$(BUILD) AWFY_RUBYLIB=$(AWFY_RUBYLIB) RUBY_BENCH=$(RUBY_BENCH) \
	  BENCH_GEMS=$(BENCH_GEMS) RUBYLIB=$(UNINSTALLED_RUBYLIB) \
	  $(LIBPATH) $(RUBY_CMD) evaluation/run.rb $(EVAL) $(EVALFLAGS)

eval-test:
	RPYYARV_BUILD=$(BUILD) RUBYLIB=$(UNINSTALLED_RUBYLIB) $(LIBPATH) \
	  $(RUBY_CMD) evaluation/test_run.rb

# JSONL history from bench.rb, plotted separately from the worker.
bench-viz:
	$(RUBY_CMD) scripts/bench_viz.rb $(VIZFLAGS)

$(RUBY_BENCH):
	git clone --depth=1 https://github.com/ruby/ruby-bench $@

# Each benchmark's Gemfile.lock, installed by the CRuby under test into
# $(BENCH_GEMS), so another machine resolves the same versions. The installer
# bootstraps CRuby automatically if Psych cannot load.
BENCH_GEMS ?= $(CURDIR)/.bench-gems
setup-gems: | $(RUBY_BENCH)
	RPYYARV_BUILD=$(BUILD) RUBY_BENCH=$(RUBY_BENCH) BENCH_GEMS=$(BENCH_GEMS) \
	  CRUBY_CONFIGURE_ARGS='$(CRUBY_CONFIGURE_ARGS)' \
	  scripts/bench-setup $(BENCH)

setup: setup-gems
	RPYYARV_BUILD=$(BUILD) BENCH_GEMS=$(BENCH_GEMS) RUBYLIB=$(UNINSTALLED_RUBYLIB) \
	  $(LIBPATH) $(RUBY_CMD) scripts/setup.rb

# Compatibility names. setup-gems already bootstraps CRuby when necessary.
bench-setup bench-bootstrap: setup-gems

# Compare stdout of both rpyyarv binaries against CRuby under a tight GC limit.
gccheck:
	@export $(LIBPATH); \
	 export RPYYARV_BUILD=$(BUILD) RUBYLIB=$(UNINSTALLED_RUBYLIB); \
	 lim() { RUBY_GC_MALLOC_LIMIT=$(GCLIMIT) perl -e 'alarm shift; exec @ARGV' $(GCTIMEOUT) "$$@" 2>/dev/null; }; \
	 nolim() { ( perl -e 'alarm shift; exec @ARGV' $(GCTIMEOUT) "$$@" >/dev/null 2>&1 ) 2>/dev/null; }; \
	 ok=0; skipped=0; failed=0; \
	 for s in benchmark/*.rb test/exceptions.rb test/coverage.rb \
	          test/requires.rb test/trampoline.rb \
	          test/definesmethod.rb test/nonlocal_return.rb \
	          test/attrs.rb test/fastops.rb test/floats.rb test/ivars.rb \
	          test/classivar.rb \
	          test/benchpaths.rb \
	          test/aset.rb \
	          test/consts.rb test/arynew.rb \
	          test/recursion.rb test/intabs.rb test/intbits.rb test/mixins.rb \
	          test/floatops.rb \
	          test/equality.rb \
	          test/nulstr.rb test/opcodes4.rb test/moduledefs.rb \
	          test/kwargs.rb test/strops.rb \
	          test/splatargs.rb test/pushtoarray.rb test/modulefunction.rb \
	          test/regexpmatch.rb test/regexbackref.rb \
	          test/sendblock.rb test/crefconsts.rb test/respondto.rb \
	          test/fastsends.rb test/supercruby.rb test/supersplat.rb \
	          test/gvaralias.rb test/expandsplat.rb test/faststr.rb \
	          test/fastfmt.rb \
	          test/fastctx.rb \
	          test/scanner.rb test/instanceeval.rb \
	          test/enumerators.rb test/loopiter.rb test/classvars.rb \
	          test/scopedclass.rb test/trampolinekw.rb test/moduleattrs.rb \
	          test/once.rb test/ranges.rb test/hasharef.rb test/kindof.rb \
	          test/redefcache.rb \
          test/lambdas.rb test/objops.rb test/aliasnest.rb test/enumops.rb \
	          test/defaultgems.rb test/modevalproc.rb \
	          test/strevallocals.rb test/refinements.rb test/superblock.rb \
	          test/bmethod.rb test/visibility.rb test/fiberblock.rb \
	          test/allocfast.rb test/strwire.rb test/evalcref.rb \
	          test/superchain.rb test/blockself.rb test/fcallproc.rb \
	          test/splatkw.rb test/r2kwargs.rb test/fwdargs.rb \
	          test/delegators.rb \
	          test/aryslice.rb \
	          test/intstep.rb \
	          test/classnewblock.rb \
	          test/constpath.rb \
	          test/bighash.rb \
	          test/rangeinc.rb test/intpow.rb \
	          test/structnew.rb \
	          test/parameters.rb \
	          test/protected.rb \
	          test/rangeeach.rb \
	          test/foreignbreak.rb \
	          test/symblock.rb \
	          test/pubsend.rb \
	          test/aliasinherit.rb \
	          test/bmethodreturn.rb \
	          test/bmethodcref.rb \
	          test/bindinglocals.rb \
	          test/coreops.rb \
	          test/threadmark.rb test/superdup.rb \
	          $(TOP)/benchmark/app_*.rb $(TOP)/benchmark/so_*.rb; do \
	   n=`basename $$s`; \
	   case $$s in test/*) \
	     if ./rpyyarv $$s 2>&1 >/dev/null | grep -q 'running under CRuby instead'; then \
	       echo "FAIL  $$n DELEGATED to cruby, so it compares cruby against cruby"; \
	       failed=`expr $$failed + 1`; continue; \
	     fi;; \
	   esac; \
	   jo=`lim ./rpyyarv-jit $$s`; jrc=$$?; \
	   io=`lim ./rpyyarv $$s`; irc=$$?; \
	   jpre=0; ipre=0; \
	   [ $$jrc -eq 0 ] || { nolim ./rpyyarv-jit $$s || jpre=1; }; \
	   [ $$irc -eq 0 ] || { nolim ./rpyyarv $$s || ipre=1; }; \
	   if [ $$jrc -ne 0 ] && [ $$irc -ne 0 ] && [ $$jpre -eq 1 ] && [ $$ipre -eq 1 ]; then \
	     echo "SKIP  $$n (does not run without the GC limit either)"; \
	     skipped=`expr $$skipped + 1`; continue; \
	   fi; \
	   co=`lim $(RUBY) --disable-gems $$s`; crc=$$?; \
	   if [ $$crc -ne 0 ]; then \
	     echo "SKIP  $$n (cruby reference exits $$crc)"; \
	     skipped=`expr $$skipped + 1`; continue; \
	   fi; \
	   bad=0; \
	   for e in jit interp; do \
	     if [ $$e = jit ]; then rc=$$jrc; out=$$jo; pre=$$jpre; else rc=$$irc; out=$$io; pre=$$ipre; fi; \
	     if [ $$rc -ne 0 ]; then \
	       if [ $$pre -eq 1 ]; then echo "  skip  $$n rpyyarv-$$e (pre-existing, not GC)"; \
	       else echo "FAIL  $$n rpyyarv-$$e CRASHED under GC limit (exit $$rc)"; bad=1; fi; \
	     elif [ "$$out" != "$$co" ]; then \
	       echo "FAIL  $$n rpyyarv-$$e OUTPUT MISMATCH vs cruby"; bad=1; \
	     fi; \
	   done; \
	   if [ $$bad -eq 1 ]; then failed=`expr $$failed + 1`; \
	   else echo "ok    $$n"; ok=`expr $$ok + 1`; fi; \
	 done; \
	 echo; echo "gccheck: $$ok ok, $$skipped skipped, $$failed failed (RUBY_GC_MALLOC_LIMIT=$(GCLIMIT))"; \
	 [ $$failed -eq 0 ] || { echo "GCCHECK FAILED"; exit 1; }

ractorcheck:
	@export $(LIBPATH); \
	 export RPYYARV_BUILD=$(BUILD) RUBYLIB=$(UNINSTALLED_RUBYLIB); \
	 co=`$(RUBY) --disable-gems test/ractors.rb`; \
	 io=`./rpyyarv test/ractors.rb`; \
	 jo=`./rpyyarv-jit test/ractors.rb`; \
	 [ "$$io" = "$$co" ] && [ "$$jo" = "$$co" ] && echo "ok ractors"

build-interp: pypy-patch
	RPYYARV_BUILD=$(BUILD) PYTHONPATH=$(PYTHONPATH) $(RPYTHON) --output=rpyyarv targetrpyyarv.py
	$(call fix_install_name,rpyyarv)

build-jit: pypy-patch
	RPYYARV_BUILD=$(BUILD) PYTHONPATH=$(PYTHONPATH) $(RPYTHON) -Ojit --output=rpyyarv-jit targetrpyyarv.py
	$(call fix_install_name,rpyyarv-jit)

# Clone does not re-run once ./pypy exists; apply any patch that is still missing.
pypy-patch: | $(PYPY)
	@for p in $(CURDIR)/pypy-patches/*.patch; do \
	  (cd $(PYPY) && git apply --reverse --check "$$p" >/dev/null 2>&1) \
	    || (cd $(PYPY) && git apply "$$p"); \
	done

$(PYPY):
	git clone --depth=1 https://github.com/pypy/pypy $@

clean:
	rm -f $(PROBE) $(SHIM) rpyyarv rpyyarv-jit
	rm -rf $(PROBE).dSYM $(SHIM).dSYM *.pyc
