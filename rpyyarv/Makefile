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

PROBE   := test/probe
SHIM    := librpyyarv_boot.$(SOEXT)
PYPY    ?= ./pypy
RUBY_BENCH ?= $(CURDIR)/ruby-bench
PYTHON  ?= python3
PYTHONPATH ?= $(TOP)
# The harness must not run on $(BUILD)/ruby: that is the system under test.
RUBY_CMD ?= ruby
RPYTHON ?= python2 $(PYPY)/rpython/bin/rpython
RUBY    ?= $(BUILD)/ruby

# A tight malloc limit fires real GCs inside compiled traces; GC_STRESS cannot,
# it escapes the vable and aborts tracing.
GCLIMIT   ?= 16384
GCTIMEOUT ?= 60

.PHONY: all test microbench awfy bench gccheck build-interp build-jit link clean

link: $(SHIM)

$(SHIM): boot_shim.c boot_shim.h
	@test -n "$(ARCHDIR)" || { echo "ERROR: build CRuby first (--enable-shared)"; exit 1; }
	$(CC) $(CFLAGS) $(CPPFLAGS) $(SHARED) -o $@ boot_shim.c $(LDFLAGS) $(LDLIBS)
	$(call fix_install_name,$@)

$(PROBE): test/probe.c
	@test -n "$(ARCHDIR)" || { echo "ERROR: build CRuby first (--enable-shared)"; exit 1; }
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ $< $(LDFLAGS) $(LDLIBS)
	$(call fix_install_name,$@)

# TODO: test_interp/test_debug/test_loader are parked on this branch; they
# assert on the W_* object model the VALUE-direct rewrite replaced.
test: $(SHIM)
	RPYYARV_BUILD=$(BUILD) $(PYTHON) test/test_boot_ctypes.py $(SCRIPT)
	RPYYARV_BUILD=$(BUILD) $(PYTHON) test/test_gc_ctypes.py

microbench:
	RPYYARV_BUILD=$(BUILD) $(RUBY_CMD) scripts/microbench.rb $(MICROBENCHFLAGS)

# AWFY steady state. AWFY_RUBYLIB supplies set/subclass_compatible.rb, which
# CRuby 4.0's Set.inherited hook needs before deltablue will load anywhere.
awfy:
	RPYYARV_BUILD=$(BUILD) AWFY_RUBYLIB=$(AWFY_RUBYLIB) $(RUBY_CMD) scripts/awfy.rb $(AWFYFLAGS)

# Both suites through one driver; RUBY_BENCH points at the ruby-bench checkout.
bench:
	RPYYARV_BUILD=$(BUILD) AWFY_RUBYLIB=$(AWFY_RUBYLIB) RUBY_BENCH=$(RUBY_BENCH) $(RUBY_CMD) scripts/bench.rb $(BENCHFLAGS)

$(RUBY_BENCH):
	git clone --depth=1 https://github.com/ruby/ruby-bench $@

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
	          test/aset.rb \
	          test/consts.rb test/arynew.rb \
	          test/recursion.rb test/intabs.rb test/mixins.rb \
	          test/floatops.rb \
	          test/equality.rb \
	          test/nulstr.rb test/opcodes4.rb test/moduledefs.rb \
	          test/kwargs.rb test/strops.rb \
	          test/sendblock.rb test/crefconsts.rb \
	          test/defaultgems.rb \
	          $(TOP)/benchmark/app_*.rb $(TOP)/benchmark/so_*.rb; do \
	   n=`basename $$s`; \
	   case $$s in test/*) \
	     if ./rpyyarv $$s 2>&1 >/dev/null | grep -q 'running under CRuby instead'; then \
	       echo "FAIL  $$n PUNTED to cruby, so it compares cruby against cruby"; \
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

build-interp: | $(PYPY)
	RPYYARV_BUILD=$(BUILD) PYTHONPATH=$(PYTHONPATH) $(RPYTHON) --output=rpyyarv targetrpyyarv.py
	$(call fix_install_name,rpyyarv)

build-jit: | $(PYPY)
	RPYYARV_BUILD=$(BUILD) PYTHONPATH=$(PYTHONPATH) $(RPYTHON) -Ojit --output=rpyyarv-jit targetrpyyarv.py
	$(call fix_install_name,rpyyarv-jit)

$(PYPY):
	git clone --depth=1 https://github.com/pypy/pypy $@
	cd $@ && git apply $(CURDIR)/pypy-patches/*.patch

clean:
	rm -f $(PROBE) $(SHIM) rpyyarv rpyyarv-jit
	rm -rf $(PROBE).dSYM $(SHIM).dSYM *.pyc
