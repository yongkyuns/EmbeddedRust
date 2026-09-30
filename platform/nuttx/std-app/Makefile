include $(APPDIR)/Make.defs

PROGNAME = $(NXRS_APP_COMMAND)
PRIORITY = $(NXRS_APP_PRIORITY)
STACKSIZE = $(NXRS_APP_STACKSIZE)
MODULE = $(CONFIG_EXAMPLES_NXRS_STD_APP)
EXTOBJS = nxrs_app.o

nxrs_app.o: $(NXRS_STD_ELF)
	@test -n "$(NXRS_APP_COMMAND)"
	$(OBJCOPY) --redefine-sym main=$(NXRS_APP_COMMAND)_main $< $@

include $(APPDIR)/Application.mk
