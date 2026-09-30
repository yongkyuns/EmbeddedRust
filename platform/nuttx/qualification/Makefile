include $(APPDIR)/Make.defs
PROGNAME = rustcam_sim
PRIORITY = 100
STACKSIZE = 65536
MODULE = $(CONFIG_EXAMPLES_RUSTCAM_SIM)
MAINSRC = runner.c
CSRCS = storage.c camera.c nuttx_support.c qualification.c close_fault.c storage_fault.c

# The old core-only ARCH_SIM fixture keeps its test-local UDP scalar bridge.
# The std integration image uses rustcam-transport-nuttx and therefore must not
# compile or link that compatibility implementation.
ifeq ($(RUSTCAM_STD_ELF),)
CSRCS += time.c transport.c
endif

# Test-only interposition: the real bridge still calls actual NuttX close.
# close_fault.c returns an injected error after closing and reusing an fd.
# Production builds of nuttx_support.c keep the ordinary rc_nx_close symbol.
nuttx_support.c_CFLAGS += -Drc_nx_close=rc_nx_close_real

# Inject below append/flush so the production retry/rollback code still runs.
# These macros affect ONLY storage.c; the fixture calls the ordinary target VFS.
storage.c_CFLAGS += -Drc_nx_file_create=rc_nx_file_create_real \
  -Dwrite=rc_test_storage_write -Dftruncate=rc_test_storage_truncate \
  -Dlseek=rc_test_storage_seek -Dfsync=rc_test_storage_sync

# ARCH_SIM retains the old core-only staticlib solely as a compatibility oracle.
# The ESP32-S3 std integration path consumes an ordinary Cargo binary and
# renames rustc's generated C-ABI main; its call into std::rt is preserved.
ifneq ($(RUSTCAM_STD_ELF),)
runner.c_CFLAGS += -DRUSTCAM_STD_ENTRY=1
EXTOBJS = rustcam_std_app.o
rustcam_std_app.o: $(RUSTCAM_STD_ELF)
	$(OBJCOPY) --redefine-sym main=rc_rust_std_main $< $@
else
EXTOBJS = rustcam_core.o
rustcam_core.o: $(RUSTCAM_SIM_LIB)
	$(LD) -r --whole-archive $(RUSTCAM_SIM_LIB) --no-whole-archive -o $@
endif

include $(APPDIR)/Application.mk
