CXX := g++
CXXFLAGS := -std=c++20 -O2 -Wall -Wextra -pedantic -pthread
LDFLAGS := -lsqlite3 -lcrypt
SRC := $(wildcard src/*.cpp)

vaultgrid: $(SRC)
	$(CXX) $(CXXFLAGS) -o $@ $(SRC) $(LDFLAGS)

.PHONY: clean
clean:
	rm -f vaultgrid
