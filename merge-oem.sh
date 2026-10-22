#!/usr/bin/env bash
# merge-oem.sh -- build SW_binaries_merged_yoshino.img, the image flash.sh writes to the "oem" partition, from the two
# software-binary packages that Sony publishes for the Yoshino platform.
#
#   ./merge-oem.sh [OUTPUT_IMAGE]
#
# Sony's images cannot be redistributed, so you download them yourself (accepting Sony's licence):
#   https://developer.sony.com/develop/open-devices/downloads/software-binaries/   (Xperia XZ1 Compact is a Yoshino device)
#     SW_binaries_for_Xperia_Android_11_4.14_v9a_yoshino   (the base: the version this port was built against)
#     SW_binaries_for_Xperia_Android_11_4.14_v8a_yoshino   (donor for 58 files that v9a dropped but the modem stack still uses)
# Put the two .zip files (or the .img files from inside them) next to this script, or point to them with
#   OEM_V9A=/path/to/v9a.zip OEM_V8A=/path/to/v8a.zip ./merge-oem.sh
#
# What it does: converts both images to raw ext4, copies the 58 files listed in oem-added-from-v8a.txt from v8a into a copy
# of v9a (with owner, mode and SELinux label), checks the result with e2fsck, and compares every copied file byte for byte.
# It never modifies your downloads and needs no root. Needs about 1.2 GB of free disk space.
# Needs: python3, unzip (only for .zip input) and e2fsprogs 1.43 or newer (debugfs, e2fsck). On macOS: brew install e2fsprogs.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${1:-$HERE/SW_binaries_merged_yoshino.img}
LIST=$HERE/oem-added-from-v8a.txt
N9=SW_binaries_for_Xperia_Android_11_4.14_v9a_yoshino
N8=SW_binaries_for_Xperia_Android_11_4.14_v8a_yoshino

die() { echo "merge-oem.sh: $*" >&2; exit 1; }

# e2fsprogs is keg-only on Homebrew and lives in sbin on most Linux distributions
for d in /opt/homebrew/opt/e2fsprogs/sbin /opt/homebrew/opt/e2fsprogs/bin /usr/local/opt/e2fsprogs/sbin /usr/local/opt/e2fsprogs/bin /sbin /usr/sbin; do
    [ -d "$d" ] && PATH="$PATH:$d"
done
for t in python3 debugfs e2fsck; do
    command -v "$t" >/dev/null || die "missing tool: $t (install python3 and e2fsprogs)"
done
ver=$(debugfs -V 2>&1 | sed -n 's/.*debugfs \([0-9]*\)\.\([0-9]*\).*/\1 \2/p' | head -1)
set -- $ver
{ [ -n "${1:-}" ] && { [ "$1" -gt 1 ] || [ "${2:-0}" -ge 43 ]; }; } || die "e2fsprogs 1.43 or newer is required (found: $(debugfs -V 2>&1 | head -1))"
[ -f "$LIST" ] && [ -f "$HERE/sparse2raw.py" ] || die "oem-added-from-v8a.txt and sparse2raw.py must be next to this script"

find_input() { # find_input <env value> <name>: print the path of NAME.img or NAME.zip
    local given=$1 name=$2 c
    if [ -n "$given" ]; then [ -f "$given" ] || die "not found: $given"; echo "$given"; return; fi
    for c in "$HERE/$name.img" "$HERE/$name.zip" "./$name.img" "./$name.zip"; do
        [ -f "$c" ] && { echo "$c"; return; }
    done
    die "$name.zip (or .img) not found next to this script; see the download link at the top of merge-oem.sh"
}
IN9=$(find_input "${OEM_V9A:-}" "$N9")
IN8=$(find_input "${OEM_V8A:-}" "$N8")

W=$(mktemp -d "${TMPDIR:-/tmp}/merge-oem.XXXXXX")
trap 'rm -rf "$W"' EXIT

to_raw() { # to_raw <name> <input> <output>: zip or sparse or raw -> raw ext4
    local name=$1 in=$2 out=$3
    case "$in" in
        *.zip) command -v unzip >/dev/null || die "missing tool: unzip"
               unzip -p "$in" "$name.img" > "$W/$name.sparse" || die "$in does not contain $name.img"
               in=$W/$name.sparse;;
    esac
    python3 -I "$HERE/sparse2raw.py" "$in" "$out"
    rm -f "$W/$name.sparse"
}
echo "== converting the Sony images"
to_raw "$N9" "$IN9" "$W/v9a.raw"
to_raw "$N8" "$IN8" "$W/v8a.raw"

dfs() { debugfs "$@" 2>/dev/null; }
for v in v9a v8a; do
    dfs -R "stat /etc/build.prop" "$W/$v.raw" | grep -q "Type: regular" || die "$v: not the expected Sony odm image (no /etc/build.prop)"
done
dfs -R "cat /etc/build.prop" "$W/v9a.raw" | grep -q "odm.version=.*yoshino_v9" || die "the first image is not v9a"
dfs -R "cat /etc/build.prop" "$W/v8a.raw" | grep -q "odm.version=.*yoshino_v8" || die "the second image is not v8a"

echo "== copying $(wc -l < "$LIST" | tr -d ' ') files from v8a into v9a"
mkdir "$W/files"
dump_cmds=$W/dump.cmd; write_cmds=$W/write.cmd; : > "$dump_cmds"; : > "$write_cmds"
i=0
while IFS= read -r f; do
    [ -n "$f" ] || continue
    i=$((i+1))
    st=$(dfs -R "stat /$f" "$W/v8a.raw") || true
    echo "$st" | grep -q "Type: regular" || die "v8a: /$f is missing or not a regular file"
    mode=$(echo "$st" | sed -n 's/.*Mode: *\([0-7]*\).*/\1/p' | head -1)
    uid=$(echo "$st" | sed -n 's/.*User: *\([0-9]*\).*/\1/p' | head -1)
    gid=$(echo "$st" | sed -n 's/.*Group: *\([0-9]*\).*/\1/p' | head -1)
    [ -n "$mode" ] && [ -n "$uid" ] && [ -n "$gid" ] || die "could not read owner and mode of /$f"
    dfs -R "stat /$f" "$W/v9a.raw" | grep -q "Type:" && die "/$f already exists in v9a; the file list does not match these images"
    echo "dump /$f $W/files/$i" >> "$dump_cmds"
    # the file type bits (0100000) are not part of the "Mode" debugfs prints for a plain permission value
    # debugfs "write" creates the name in its current directory: cd there first (and back to the root after)
    { echo "cd /$(dirname "$f")"; echo "write $W/files/$i $(basename "$f")"; echo "cd /"
      printf 'sif /%s mode 0%o\n' "$f" $((0100000 + 8#$mode))
      echo "sif /$f uid $uid"; echo "sif /$f gid $gid"
      echo "ea_set -f $W/files/$i.selinux /$f security.selinux"; } >> "$write_cmds"
    # SELinux label of the donor file (kept if present; permissive boot does not depend on it)
    dfs -R "ea_get -f $W/files/$i.selinux /$f security.selinux" "$W/v8a.raw" >/dev/null || true
done < "$LIST"
debugfs -f "$dump_cmds" "$W/v8a.raw" >/dev/null 2>&1
# a missing label file makes only that ea_set line fail; debugfs carries on with the next command
cp "$W/v9a.raw" "$OUT.tmp"
debugfs -w -f "$write_cmds" "$OUT.tmp" >/dev/null 2>&1 || true

echo "== checking"
fails=0
i=0
while IFS= read -r f; do
    [ -n "$f" ] || continue
    i=$((i+1))
    dfs -R "dump /$f $W/check" "$OUT.tmp" >/dev/null || true
    if cmp -s "$W/check" "$W/files/$i"; then :; else echo "MISMATCH: /$f" >&2; fails=$((fails+1)); fi
    rm -f "$W/check"
done < "$LIST"
[ "$fails" = 0 ] || die "$fails file(s) differ after the copy; the output was not written"
e2fsck -fn "$OUT.tmp" >"$W/fsck.log" 2>&1 || { cat "$W/fsck.log" >&2; die "e2fsck reports errors; the output was not written"; }
mv -f "$OUT.tmp" "$OUT"
echo "== done: $OUT ($(wc -c < "$OUT" | tr -d ' ') bytes, $i files added from v8a, e2fsck clean)"
