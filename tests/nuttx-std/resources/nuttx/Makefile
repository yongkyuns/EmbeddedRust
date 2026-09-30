include $(APPDIR)/Make.defs
PROGNAME = rust_resources
PRIORITY = 100
STACKSIZE = 65536
MODULE = $(CONFIG_EXAMPLES_RUSTCAM_STD)
MAINSRC = fd_setup.c
EXTOBJS = rust_resources.o

# Test setup must close descriptors BEFORE compiler-generated Rust startup.
# It does not call a private Rust function or replace the handwritten fn main.
rust_resources.o: $(RUSTCAM_STD_ELF)
	$(OBJCOPY) --redefine-sym main=rust_resources_probe_main $< $@

include $(APPDIR)/Application.mk
