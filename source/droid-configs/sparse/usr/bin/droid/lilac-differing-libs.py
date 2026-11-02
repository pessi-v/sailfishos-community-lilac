#!/usr/bin/python3
"""Print the libraries of our droid-hybris system overlay that differ from the copy mounted on /system.

    lilac-differing-libs.py OVERLAY_DIR

For lib64 and lib prints "lib64/name.so" / "lib/name.so" for every file that exists on /system and has different
content (an empty placeholder differs too). Identical files are not listed: binding a file over an identical copy
changes nothing and only adds entries to the mount table. One process, because a cmp per file takes about 24 s
on a cold cache.
"""
import filecmp
import glob
import os
import sys

overlay = sys.argv[1]
for libdir in ("lib64", "lib"):
    for src in sorted(glob.glob("%s/%s/*.so" % (overlay, libdir))):
        name = os.path.basename(src)
        dst = "/system/%s/%s" % (libdir, name)
        if os.path.isfile(dst) and not filecmp.cmp(src, dst, shallow=False):
            print("%s/%s" % (libdir, name))
