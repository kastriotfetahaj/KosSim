#############################################
##             PROJECT OPTIONS             ##
#############################################

# Compiler, change if your installation comes with a suffix, e.g., clang-10
CXX = clang
CXX_FUZZING = afl-clang-lto

# Compiler options
#
# need gnu extensions for snmp u_char like types
# need large code model because the data section is larger than 2GB
SHARED_OPTS = -mcmodel=large -fpic -fno-plt \
	      -Wall -Wextra -Wshadow -Wno-gnu-statement-expression -pedantic -pedantic-errors
RELEASE_OPTS = $(SHARED_OPTS) -O2
RELEASE_LFLAGS = -lsnmp -lcrypto -lssl -fpic -fno-plt -Wl,-z,relro,-z,now

PROFILING_OPTS = $(SHARED_OPTS) -O2 -g -pg
PROFILING_LFLAGS = -lsnmp -lcrypto -lssl -fpic -fno-plt -Wl,-z,relro,-z,now -pg

DEBUG_OPTS = $(SHARED_OPTS) -Og -g -DDEBUG=1 # -fsanitize=address,undefined
DEBUG_LFLAGS = -lsnmp -lcrypto -lssl -fpic -fno-plt -Wl,-z,relro,-z,now # -fsanitize=address,undefined

FUZZING_OPTS = $(SHARED_OPTS) -O2 -DFUZZING=1
FUZZING_LFLAGS = -lcrypto -lssl -fpic -fno-plt -Wl,-z,relro,-z,now

# Input
SRC_DIR = src
INC_DIR = src

# Output
RELEASE_BUILD_DIR = build_release
PROFILING_BUILD_DIR = build_profiling
DEBUG_BUILD_DIR = build_debug
FUZZING_BUILD_DIR = build_fuzzing
BINARY = agent

# Verbose Output?
V = 0

# Query obfuscator
QOBF = obfuscator/qobf.py

#############################################
##          CORE (do not touch)            ##
#############################################

# get all source files
SRC_FILES = $(shell find $(SRC_DIR) -name "*.c")
HDR_FILES = $(shell find $(INC_DIR) -name "*.h")
# create paths for debug and release object files
DEBUG_OBJ_FILES = $(patsubst $(SRC_DIR)/%,$(DEBUG_BUILD_DIR)/%, $(SRC_FILES:.c=.o))
PROFILING_OBJ_FILES = $(patsubst $(SRC_DIR)/%,$(PROFILING_BUILD_DIR)/%, $(SRC_FILES:.c=.o))
RELEASE_OBJ_FILES = $(patsubst $(SRC_DIR)/%,$(RELEASE_BUILD_DIR)/%, $(SRC_FILES:.c=.o))
FUZZING_OBJ_FILES = $(patsubst $(SRC_DIR)/%,$(FUZZING_BUILD_DIR)/%, $(SRC_FILES:.c=.o))


# prepare verbosity flag
ifeq ($(V),0)
AT := @
endif

all: debug

release: $(RELEASE_BUILD_DIR) $(RELEASE_BUILD_DIR)/$(BINARY)
	@echo

profiling: $(PROFILING_BUILD_DIR) $(PROFILING_BUILD_DIR)/$(BINARY)
	@echo

debug: $(DEBUG_BUILD_DIR) $(DEBUG_BUILD_DIR)/$(BINARY)
	@echo

fuzzing: $(FUZZING_BUILD_DIR) $(FUZZING_BUILD_DIR)/$(BINARY)
	@echo


$(DEBUG_BUILD_DIR)/$(BINARY): $(DEBUG_BUILD_DIR) $(DEBUG_OBJ_FILES)
ifeq ($(V), 0)
	@echo  -e 'LINK\t$(notdir $@)'
endif
	$(AT) $(CXX) $(DEBUG_LFLAGS) $(DEBUG_OBJ_FILES) -o $(DEBUG_BUILD_DIR)/$(BINARY)

$(DEBUG_BUILD_DIR)/%.o: $(SRC_DIR)/%.c $(HDR_FILES) Makefile
ifeq ($(V), 0)
	@echo  -e 'CC\t$(notdir $<)'
endif
	$(AT) $(CXX) $(DEBUG_OPTS) -I $(INC_DIR) -c $< -o $@
	$(AT) $(QOBF) $@


$(PROFILING_BUILD_DIR)/$(BINARY): $(PROFILING_BUILD_DIR) $(PROFILING_OBJ_FILES)
ifeq ($(V), 0)
	@echo  -e 'LINK\t$(notdir $@)'
endif
	$(AT) $(CXX) $(PROFILING_LFLAGS) $(PROFILING_OBJ_FILES) -o $(PROFILING_BUILD_DIR)/$(BINARY)

$(PROFILING_BUILD_DIR)/%.o: $(SRC_DIR)/%.c $(HDR_FILES) Makefile
ifeq ($(V), 0)
	@echo  -e 'CC\t$(notdir $<)'
endif
	$(AT) $(CXX) $(PROFILING_OPTS) -I $(INC_DIR) -c $< -o $@
	$(AT) $(QOBF) $@


$(RELEASE_BUILD_DIR)/$(BINARY): $(RELEASE_BUILD_DIR) $(RELEASE_OBJ_FILES)
ifeq ($(V), 0)
	@echo  -e 'LINK\t$(notdir $@)'
endif
	$(AT) $(CXX) $(RELEASE_LFLAGS) $(RELEASE_OBJ_FILES) -o $(RELEASE_BUILD_DIR)/$(BINARY)
	$(AT) objdump -t $@ | grep -e SERVER_ -e OBF_ | sed 's/.* /--strip-symbol=/' | xargs strip $@

$(RELEASE_BUILD_DIR)/%.o: $(SRC_DIR)/%.c $(HDR_FILES) Makefile
ifeq ($(V), 0)
	@echo  -e 'CC\t$(notdir $<)'
endif
	$(AT) $(CXX) $(RELEASE_OPTS) -I $(INC_DIR) -c $< -o $@
	$(AT) $(QOBF) $@


$(FUZZING_BUILD_DIR)/$(BINARY): $(FUZZING_BUILD_DIR) $(FUZZING_OBJ_FILES)
ifeq ($(V), 0)
	@echo  -e 'LINK\t$(notdir $@)'
endif
	$(AT) $(CXX_FUZZING) $(FUZZING_LFLAGS) $(FUZZING_OBJ_FILES) fuzzing/libsnmp.a -o $(FUZZING_BUILD_DIR)/$(BINARY)

$(FUZZING_BUILD_DIR)/%.o: $(SRC_DIR)/%.c $(HDR_FILES) Makefile
ifeq ($(V), 0)
	@echo  -e 'CC\t$(notdir $<)'
endif
	$(AT) $(CXX_FUZZING) $(FUZZING_OPTS) -I $(INC_DIR) -c $< -o $@


$(DEBUG_BUILD_DIR):
	@mkdir -p $(DEBUG_BUILD_DIR)

$(PROFILING_BUILD_DIR):
	@mkdir -p $(PROFILING_BUILD_DIR)

$(RELEASE_BUILD_DIR):
	@mkdir -p $(RELEASE_BUILD_DIR)

$(FUZZING_BUILD_DIR):
	@mkdir -p $(FUZZING_BUILD_DIR)


clean:
	@echo  Removing build artifacts...
	@rm -rf $(DEBUG_BUILD_DIR)
	@rm -rf $(PROFILING_BUILD_DIR)
	@rm -rf $(RELEASE_BUILD_DIR)
	@rm -rf $(FUZZING_BUILD_DIR)
	@rm -rf *.stackdump

.PHONY: all release debug profiling fuzzing clean
