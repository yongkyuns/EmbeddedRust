include $(APPDIR)/Make.defs
PROGNAME = rust_std
PRIORITY = 100
STACKSIZE = 65536
MODULE = $(CONFIG_EXAMPLES_NXRS_STD)
EXTOBJS = rust_std.o

# The input is the linked Cargo binary, not a hand-exported Rust library entry.
# Rename rustc's generated C-ABI main, preserving its call into std::rt.
rust_std.o: $(NXRS_STD_ELF)
	$(OBJCOPY) --redefine-sym main=rust_std_main $< $@

include $(APPDIR)/Application.mk
