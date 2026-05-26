TARGETS := fwmark ip-wrapper tunctl

all: $(TARGETS)

%.o: %.c
	$(CC) -c -Os -Wall -Wextra -Wpedantic -Werror -fstack-clash-protection -fstack-protector-all -fcf-protection -D_FORTIFY_SOURCE=3 -Wl,-z,relro,-z,now $^ -o $@

$(TARGETS): %: %.o
	$(CC) -pie -Wl,-z,relro,-z,now $^ -o $@

clean:
	$(RM) $(TARGETS) $(patsubst %,%.o,$(TARGETS))

.PHONY: all clean
