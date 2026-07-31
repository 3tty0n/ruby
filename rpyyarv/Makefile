TOP     := $(abspath $(CURDIR)/..)
BUILD   := $(TOP)/build
ARCHDIR := $(patsubst %/ruby/config.h,%,\
             $(firstword $(wildcard $(BUILD)/.ext/include/*/ruby/config.h)))
OS      := $(shell uname -s)

CFLAGS  += -Wall -Wextra -g -O0
CPPFLAGS+= -I$(TOP)/include -I$(ARCHDIR) -I$(CURDIR)
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
PYPY    ?= $(HOME)/src/pypy
PYTHON  ?= python3
RPYTHON ?= python2 $(PYPY)/rpython/bin/rpython
RUBY    ?= $(BUILD)/ruby

.PHONY: all
all: $(SHIM) $(PROBE)

.PHONY: info
info:
	@echo "OS       = $(OS)"
	@echo "TOP      = $(TOP)"
	@echo "BUILD    = $(BUILD)"
	@echo "ARCHDIR  = $(ARCHDIR)"
	@echo "LIBRUBY  = $(LIBRUBY)"
	@echo "INSTNAME = $(INSTNAME)"
	@echo "SHIM     = $(SHIM)"
	@echo "RUBY     = $(LIBPATH) $(RUBY)"

.PHONY: $(SHIM)
$(SHIM): boot_shim.c boot_shim.h
	@test -n "$(ARCHDIR)" || { echo "ERROR: build CRuby first (--enable-shared)"; exit 1; }
	$(CC) $(CFLAGS) $(CPPFLAGS) $(SHARED) -o $@ boot_shim.c $(LDFLAGS) $(LDLIBS)
	$(call fix_install_name,$@)

.PHONY: $(PROBE)
$(PROBE): test/probe.c
	@test -n "$(ARCHDIR)" || { echo "ERROR: build CRuby first (--enable-shared)"; exit 1; }
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ $< $(LDFLAGS) $(LDLIBS)
	$(call fix_install_name,$@)

.PHONY: test
test: $(SHIM)
	RPYYARV_BUILD=$(BUILD) $(PYTHON) test/test_boot_ctypes.py $(SCRIPT)

.PHONY: test-unit
test-unit:
	$(PYTHON) test/test_interp.py
	RPYYARV_BUILD=$(BUILD) $(PYTHON) test/test_loader.py

# Checked in, so the tests do not need a ruby.
FIXTURES := $(patsubst %.rb,%.iseq,$(wildcard test/*.rb))

.PHONY: fixtures
fixtures: $(FIXTURES)

test/%.iseq: test/%.rb scripts/dump_iseq.rb
	$(LIBPATH) $(RUBY) scripts/dump_iseq.rb $< > $@

.PHONY: build-interp
build-interp:
	RPYYARV_BUILD=$(BUILD) $(RPYTHON) --output=rpyyarv targetrpyyarv.py
	$(call fix_install_name,rpyyarv)

.PHONY: build-jit
build-jit:
	RPYYARV_BUILD=$(BUILD) $(RPYTHON) -Ojit --output=rpyyarv-jit targetrpyyarv.py
	$(call fix_install_name,rpyyarv-jit)

# For binaries RPython linked outside `make build-*`.
.PHONY: relink
relink:
	$(call fix_install_name,rpyyarv)
	$(call fix_install_name,rpyyarv-jit)
	$(call fix_install_name,$(SHIM))
	$(call fix_install_name,$(PROBE))

.PHONY: build-dump
build-dump:
	$(RPYTHON) --output=rpyyarv-dump targetdump.py

.PHONY: clean
clean:
	rm -f $(PROBE) $(SHIM) rpyyarv rpyyarv-jit rpyyarv-dump
	rm -rf $(PROBE).dSYM $(SHIM).dSYM *.pyc
