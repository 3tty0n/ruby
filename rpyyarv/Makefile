TOP     := $(abspath $(CURDIR)/..)
BUILD   := $(TOP)/build
ARCHDIR := $(firstword $(wildcard $(BUILD)/.ext/include/*))
SOVER   := $(patsubst $(BUILD)/libruby.%.dylib,%,$(firstword $(wildcard $(BUILD)/libruby.*.dylib)))
DYLIB   := $(BUILD)/libruby.$(SOVER).dylib

INSTNAME := $(shell otool -D $(DYLIB) 2>/dev/null | tail -1)

CFLAGS  += -Wall -Wextra -g -O0
CPPFLAGS+= -I$(TOP)/include -I$(ARCHDIR) -I$(CURDIR)
LDFLAGS += -L$(BUILD) -Wl,-rpath,$(BUILD)
LDLIBS  += -lruby.$(SOVER)

PROBE   := test/probe
SHIM    := librpyyarv_boot.dylib
PYPY    ?= $(HOME)/src/pypy

.PHONY: all
all: $(SHIM) $(PROBE)

.PHONY: info
info:
	@echo "TOP      = $(TOP)"
	@echo "BUILD    = $(BUILD)"
	@echo "ARCHDIR  = $(ARCHDIR)"
	@echo "SOVER    = $(SOVER)"
	@echo "INSTNAME = $(INSTNAME)"

define fix_install_name
	@if [ "$(INSTNAME)" != "$(DYLIB)" ]; then \
	   install_name_tool -change "$(INSTNAME)" "$(DYLIB)" $@; \
	 fi
endef

.PHONY: $(SHIM)
$(SHIM): boot_shim.c boot_shim.h
	@test -n "$(ARCHDIR)" || { echo "ERROR: build CRuby first (--enable-shared)"; exit 1; }
	$(CC) $(CFLAGS) $(CPPFLAGS) -dynamiclib -o $@ boot_shim.c $(LDFLAGS) $(LDLIBS)
	$(fix_install_name)

.PHONY: $(PROBE)
$(PROBE): test/probe.c
	@test -n "$(ARCHDIR)" || { echo "ERROR: build CRuby first (--enable-shared)"; exit 1; }
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ $< $(LDFLAGS) $(LDLIBS)
	$(fix_install_name)

.PHONY: test
test: $(SHIM)
	RPYYARV_BUILD=$(BUILD) python3 test/test_boot_ctypes.py $(SCRIPT)

.PHONY: build-interp
build-interp:
	RPYYARV_BUILD=$(BUILD) $(PYPY)/rpython/bin/rpython targetrpyyarv.py

.PHONY: build-jit
build-jit:
	RPYYARV_BUILD=$(BUILD) $(PYPY)/rpython/bin/rpython -Ojit targetrpyyarv.py

.PHONY: clean
clean:
	rm -f $(PROBE) $(SHIM) rpyyarv
	rm -rf $(PROBE).dSYM $(SHIM).dSYM *.pyc
