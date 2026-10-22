#!/usr/bin/env python3
"""Make build/make/tools/fs_config/fs_config_generator.py run under BOTH
Python 2 and Python 3.

This script is invoked from two genuinely different execution contexts, each
with a different `python` on PATH:
1. droid-hal-device's build step (`fs_config_generator.py aidarray ...`,
   invoked via mb2/sb2 inside the sfossdk Platform SDK) -- that chroot and its
   aarch64 target ship ONLY python3 (3.11); no `python`/python2 binary exists
   there or on oldlenny's own Ubuntu 26.04 host at all.
2. The Android tree's own Soong build (`passwd_gen_product`/`_odm`/`_vendor`
   genrules, hit by an ordinary `m <target>` once enough of the tree needs
   building) -- that runs host tools through Soong's `sbox` sandbox, which
   resolves `#!/usr/bin/env python` to a *real, bundled Python 2* somewhere
   in the tree's own prebuilts. Confirmed empirically: the identical
   `ImportError: No module named configparser` (Python 2's unquoted message
   format, not Python 3's `ModuleNotFoundError: No module named 'configparser'`)
   surfaced only once genrules started invoking this file, after the
   droid-hal-device codepath above had already been confirmed working under
   python3 alone.

So this file must remain valid syntax AND semantics under both interpreters,
not be ported to python3-only. `android-11.0.0_r46`'s build/make predates
AOSP's python3 migration of this particular tool (the first port's Android-15
base already has the migrated, dual-compatible version, which is why it never
hit any of this).

Three fixes, each dual-compatible:
- 14 bare `print X` statements -> `print(X)`. Never `print X, Y` (always a
  single expression), so this is just parenthesization -- valid, identical
  syntax under both python2 and python3.
- one `.iteritems()` -> `.items()`. Returns a list instead of an iterator
  under python2 instead of a view -- irrelevant here (dict is tiny, consumed
  once).
- `import ConfigParser` -> a try/except that imports `configparser` under
  python3 and falls back to `ConfigParser` under python2, both aliased to the
  same `ConfigParser` name the rest of the file already uses
  (`ConfigParser.ConfigParser()`).
Verified by grep before writing this patch -- no `except X, e:`, `xrange`,
`unicode()`, `.has_key()`, `StringIO`, `cPickle`, `Queue`, or other
non-dual-compatible py2-only constructs anywhere in the file.

A fourth, separate bug surfaced only once the above three let the script
actually run: `_process_and_check()`'s OEM-range-overlap check does
`Utils.in_any_range(aid, ranges)` where `aid` is a *dict key taken straight
from `self._aid_value_to_name`* -- i.e. the raw, never-`int()`-converted
`value` string parsed out of the #define. `ranges` holds real ints. Python 2
silently allowed `int <= str` (ordering cross-type comparisons by type name,
so every such comparison was `False`) -- this check has therefore been a
silent no-op for as long as this file has existed under Python 2. Python 3
raises `TypeError` on the same comparison instead of pretending to succeed.
The fix restores the obviously-intended behavior (convert the value to int
before the numeric range comparison, exactly as normalized_value already does
elsewhere in this same file) rather than papering over the crash -- if this
newly-*working* check ever raises `ValueError: AID ... within reserved OEM
Range`, that is a real overlap in this device's own
android_filesystem_config.h, not a false positive from this patch.

Idempotent (checks all four constructs; only re-applies what's still
present). Run from the repo-synced tree root, or pass it as argv[1].
"""
import re
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'build/make/tools/fs_config/fs_config_generator.py'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
needs_print = re.search(r'^\s*print [^(]', s, re.M) is not None
needs_iter = '.iteritems()' in s
needs_configparser = 'except ImportError:\n    import ConfigParser  # python2' not in s
old_range_check = '''        for aid in self._aid_value_to_name:
            for ranges in self._ranges.values():
                if Utils.in_any_range(aid, ranges):
                    name = self._aid_value_to_name[aid]
                    raise ValueError(
                        'AID "%s" value: %u within reserved OEM Range: "%s"' %
                        (name, aid, str(ranges)))'''
needs_range_fix = old_range_check in s

if not (needs_print or needs_iter or needs_configparser or needs_range_fix):
    print('already patched')
    sys.exit(0)

# `print EXPR` -> `print(EXPR)`. Every call site here is a single expression
# (no comma-separated print args), confirmed by inspection -- safe as a
# whole-line wrap.
new_s, n_print = re.subn(
    r'^(\s*)print (.+)$', r'\1print(\2)', s, flags=re.M)

new_s, n_iter = re.subn(r'\.iteritems\(\)', '.items()', new_s)

cfg_replacement = (
    'try:\n    import configparser as ConfigParser  # python3\n'
    'except ImportError:\n    import ConfigParser  # python2')
n_cfg = 0
if needs_configparser:
    if re.search(r'^import configparser as ConfigParser$', new_s, re.M):
        # earlier, non-dual-compatible version of this patch already ran
        new_s, n_cfg = re.subn(
            r'^import configparser as ConfigParser$', cfg_replacement,
            new_s, flags=re.M)
    else:
        new_s, n_cfg = re.subn(
            r'^import ConfigParser$', cfg_replacement, new_s, flags=re.M)

new_range_check = '''        for aid in self._aid_value_to_name:
            aid_value = int(aid, 0)
            for ranges in self._ranges.values():
                if Utils.in_any_range(aid_value, ranges):
                    name = self._aid_value_to_name[aid]
                    raise ValueError(
                        'AID "%s" value: %u within reserved OEM Range: "%s"' %
                        (name, aid_value, str(ranges)))'''
n_range = 0
if old_range_check in new_s:
    new_s = new_s.replace(old_range_check, new_range_check)
    n_range = 1

if n_print == 0 and n_iter == 0 and n_cfg == 0 and n_range == 0:
    sys.exit('expected py2 constructs not found -- file may have changed upstream')

p.write_text(new_s)
print(f'patched {p}: {n_print} print statement(s), {n_iter} .iteritems() call(s), '
      f'{n_cfg} ConfigParser import(s), {n_range} range-check int fix(es)')
