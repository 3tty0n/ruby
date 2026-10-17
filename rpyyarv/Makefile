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
LDFLAGS += -Wl,-headerpad_max_install_names

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
define fix_install_name
endef
endif

PROBE   := test/probe
SHIM    := librpyyarv_boot.$(SOEXT)
PYPY    ?= ./pypy
PYPY_URL ?= https://github.com/plig-tmu/pypy
PYPY_BRANCH ?= callee-frame
PYTHON  ?= pypy2
RPYTHON ?= $(PYTHON) $(PYPY)/rpython/bin/rpython
PYTEST  ?= $(PYTHON) $(PYPY)/pytest.py
RPYTHON_FLAGS ?=

.PHONY: test test-llinterp build-interp build-jit link clean

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

# llinterp needs Python 2 (pypy2) and the pypy checkout, which pytest 9 cannot host.
test-llinterp: | $(PYPY)
	RPYYARV_BUILD=$(BUILD) $(PYTHON) $(PYPY)/pytest.py test/test_llinterp.py

build-interp: | $(PYPY)
	RPYYARV_BUILD=$(BUILD) $(RPYTHON) --output=rpyyarv-runtime-replacing targetrpyyarv.py
	$(call fix_install_name,rpyyarv-runtime-replacing)

build-jit: | $(PYPY)
	RPYYARV_BUILD=$(BUILD) $(RPYTHON) -Ojit --output=rpyyarv-runtime-replacing-jit targetrpyyarv.py
	$(call fix_install_name,rpyyarv-runtime-replacing-jit)

$(PYPY):
	git clone --depth=1 --branch $(PYPY_BRANCH) $(PYPY_URL) $@

clean:
	rm -f $(PROBE) $(SHIM) rpyyarv-runtime-replacing rpyyarv-runtime-replacing-jit
	rm -rf $(PROBE).dSYM $(SHIM).dSYM *.pyc .pytest_cache
	find . -name __pycache__ -prune -exec rm -rf {} +
