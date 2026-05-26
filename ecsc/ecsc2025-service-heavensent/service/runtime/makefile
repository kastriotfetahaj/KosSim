# GCC Makefile
CXX = g++
SRCDIR = heavensent
OBJDIR = obj

# Add our build flags
CXXFLAGS += -std=c++20 -ggdb -Iangelscript/include

SRCNAMES = \
  main.cpp \
  api.cpp

OBJ = $(addprefix $(OBJDIR)/, $(notdir $(SRCNAMES:.cpp=.o))) \
	obj/scriptbuilder.o \
	obj/scripthelper.o \
	obj/scriptarray.o \
	obj/scriptstdstring.o \
	obj/scriptstdstring_utils.o \
	obj/scriptmath.o \
	obj/scriptmathcomplex.o \
	obj/datetime.o \
	obj/scriptfile.o \
	obj/scriptfilesystem.o \
	obj/TracyClient.o

BIN = bin/heavensent
DELETER = rm -f

all: $(BIN)

$(BIN): $(OBJ)
	$(CXX) -o $(BIN) $(OBJ) -static -langelscript -dynamic -lpthread -L angelscript/lib
	@echo -------------------------------------------------------------------
	@echo Done.

$(OBJDIR)/%.o: $(SRCDIR)/%.cpp
	$(CXX) $(CXXFLAGS) -o $@ -c $<

# AngelScript addons
obj/scripthelper.o: add_on/scripthelper/scripthelper.cpp
	$(CXX) $(CXXFLAGS) -o $@ -c $<

obj/scriptbuilder.o: add_on/scriptbuilder/scriptbuilder.cpp
	$(CXX) $(CXXFLAGS) -o $@ -c $<

obj/scriptarray.o: add_on/scriptarray/scriptarray.cpp
	$(CXX) $(CXXFLAGS) -o $@ -c $<

obj/scriptstdstring.o: add_on/scriptstdstring/scriptstdstring.cpp
	$(CXX) $(CXXFLAGS) -o $@ -c $<

obj/scriptstdstring_utils.o: add_on/scriptstdstring/scriptstdstring_utils.cpp
	$(CXX) $(CXXFLAGS) -o $@ -c $<

obj/scriptmath.o: add_on/scriptmath/scriptmath.cpp
	$(CXX) $(CXXFLAGS) -o $@ -c $<

obj/scriptmathcomplex.o: add_on/scriptmath/scriptmathcomplex.cpp
	$(CXX) $(CXXFLAGS) -o $@ -c $<

# DateTime is a hidden dependency of scriptfile, which, when compiled without datetime,
# complains, that it can't find CDateTime::* ...
obj/datetime.o: add_on/datetime/datetime.cpp
	$(CXX) $(CXXFLAGS) -o $@ -c $<

obj/scriptfile.o: add_on/scriptfile/scriptfile.cpp
	$(CXX) $(CXXFLAGS) -o $@ -c $<

obj/scriptfilesystem.o: add_on/scriptfile/scriptfilesystem.cpp
	$(CXX) $(CXXFLAGS) -o $@ -c $<

obj/TracyClient.o: tracy/TracyClient.cpp
	$(CXX) $(CXXFLAGS) -o $@ -c $<


clean:
	$(DELETER) $(OBJ) $(BIN)

.PHONY: all clean
