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
PYPY    ?= ./pypy
PYTHON  ?= python3
PYTEST  ?= $(PYTHON) -m pytest
PYTHON2 ?= python2
RPYTHON ?= python2 $(PYPY)/rpython/bin/rpython
RUBY    ?= $(BUILD)/ruby

.PHONY: all test test-llinterp build-interp build-jit link clean

link: $(SHIM)

$(SHIM): boot_shim.c boot_shim.h
	@test -n "$(ARCHDIR)" || { echo "ERROR: build CRuby first (--enable-shared)"; exit 1; }
	$(CC) $(CFLAGS) $(CPPFLAGS) $(SHARED) -o $@ boot_shim.c $(LDFLAGS) $(LDLIBS)
	$(call fix_install_name,$@)

$(PROBE): test/probe.c
	@test -n "$(ARCHDIR)" || { echo "ERROR: build CRuby first (--enable-shared)"; exit 1; }
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ $< $(LDFLAGS) $(LDLIBS)
	$(call fix_install_name,$@)

# Tests needing a built CRuby or shim skip themselves when it is missing.
test: $(SHIM)
	RPYYARV_BUILD=$(BUILD) $(PYTEST) $(PYTEST_ARGS)

# llinterp needs Python 2 and the pypy checkout, which pytest 9 cannot host.
test-llinterp: | $(PYPY)
	RPYYARV_BUILD=$(BUILD) $(PYTHON2) test/test_llinterp.py

build-interp: | $(PYPY)
	RPYYARV_BUILD=$(BUILD) $(RPYTHON) --output=rpyyarv targetrpyyarv.py
	$(call fix_install_name,rpyyarv)

build-jit: | $(PYPY)
	RPYYARV_BUILD=$(BUILD) $(RPYTHON) -Ojit --output=rpyyarv-jit targetrpyyarv.py
	$(call fix_install_name,rpyyarv-jit)

$(PYPY):
	git clone --depth=1 https://github.com/pypy/pypy $@

clean:
	rm -f $(PROBE) $(SHIM) rpyyarv rpyyarv-jit
	rm -rf $(PROBE).dSYM $(SHIM).dSYM *.pyc .pytest_cache
	find . -name __pycache__ -prune -exec rm -rf {} +
