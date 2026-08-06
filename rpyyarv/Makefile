TOP     := $(abspath $(CURDIR)/..)
BUILD   := $(TOP)/build
ARCHDIR := $(patsubst %/ruby/config.h,%,\
             $(firstword $(wildcard $(BUILD)/.ext/include/*/ruby/config.h)))
OS      := $(shell uname -s)

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
PYTHON  ?= python3
RPYTHON ?= python2 $(PYPY)/rpython/bin/rpython
RUBY    ?= $(BUILD)/ruby

.PHONY: all test microbench build-interp build-jit link clean

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
	RPYYARV_BUILD=$(BUILD) $(PYTHON) scripts/microbench.py $(MICROBENCHFLAGS)

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
	rm -rf $(PROBE).dSYM $(SHIM).dSYM *.pyc
