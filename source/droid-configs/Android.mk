HYBRIS_TOP_PATH := $(call my-dir)
LOCAL_PATH := $(HYBRIS_TOP_PATH)
include $(call all-subdir-makefiles)

# libhybris has no top-level Android.mk of its own -- all-subdir-makefiles
# only globs one level deep, but libhybris's actual Android.mk files live
# two levels down (compat/*/Android.mk, hybris/*/Android.mk). LOCAL_PATH is
# clobbered by the includes above (each sets its own), so use the saved
# HYBRIS_TOP_PATH here, not LOCAL_PATH.
include $(wildcard $(HYBRIS_TOP_PATH)/libhybris/compat/*/Android.mk)
include $(wildcard $(HYBRIS_TOP_PATH)/libhybris/hybris/*/Android.mk)
