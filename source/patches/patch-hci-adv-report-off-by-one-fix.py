#!/usr/bin/env python3
"""Fix a real, upstream-class off-by-one bug in hci_le_adv_report_evt() that
drops every LE advertising report which exactly fills its HCI event buffer,
misclassifying it as "malicious", regardless of which device sent it.

Found 2026-09-24 while diagnosing a
Bluetooth headset pairing failure and missing device names during scans.
The diagnostic patch (patch-hci-adv-report-diag.py) added logging that
proved the pattern conclusively: every single occurrence logged
`remaining=1/1` (this was the one-and-only report in the event, correctly
parsed in full) with `offset` exactly equal to `skb_len` (the parser
walked precisely to the end of the buffer, as it should for a
completely, correctly consumed report) -- across many distinct, clearly
unrelated MAC addresses, not one specific misbehaving device.

Root cause: the loop's own trailing bounds check --
`if (ptr > tail - sizeof(*ev)) { ...Malicious...; break; }` -- exists to
make sure there's enough room left in the buffer for at least one more
report's header before the *next* loop iteration tries to read one. But
it runs unconditionally after every iteration, including the last one
(when `num_reports` has already reached 0 and the `while (num_reports--)`
condition is about to end the loop on its own). For a single-report event
that exactly fills its buffer -- an extremely common, entirely valid
shape -- `ptr` legitimately lands exactly at `tail`, `sizeof(*ev)` is a
strictly positive struct size, so `ptr > tail - sizeof(*ev)` is always
true, and a perfectly well-formed report gets thrown away every time.
This silently drops advertising data (including EIR device-name fields)
from effectively any device whose report happens to fill its buffer
exactly -- explaining both the missing device names during scans and,
very plausibly, degraded pairing reliability.

Fix: only run that check when there's actually another iteration coming
(`num_reports` is nonzero after the decrement) -- matches the intent of
the check (guard the *next* read) without misfiring on the last one.

Idempotent. Run from the root of this AOSP tree (the directory containing
`kernel/`), or pass that root as argv[1]. Expects
patch-hci-adv-report-diag.py's own diagnostic logging already applied
first (this patch targets the post-diagnostic loop body).
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'kernel/sony/msm-4.14/common-kernel/net/bluetooth/hci_event.c'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
MARK = 'lilac-v2 off-by-one fix'
if MARK in s:
    print('already patched')
    sys.exit(0)

old = '''		ptr += sizeof(*ev) + ev->length + 1;

		if (ptr > (void *) skb_tail_pointer(skb) - sizeof(*ev)) {
			/* lilac-v2 diag */
			bt_dev_err(hdev,
				"Malicious advertising data. Stopping processing: last bdaddr=%pMR type=%u evt_type=%u len=%u skb_len=%u remaining=%u/%u offset=%ld",
				&ev->bdaddr, ev->bdaddr_type, ev->evt_type,
				ev->length, skb->len, num_reports + 1,
				orig_num_reports,
				(long)((void *)ptr - (void *)skb->data));
			break;
		}'''

new = '''		ptr += sizeof(*ev) + ev->length + 1;

		/* lilac-v2 off-by-one fix: only
		 * check that there's room for another report's header when
		 * another iteration is actually coming -- num_reports==0
		 * here means this was the last (or only) report, already
		 * fully and correctly consumed; the while() loop's own
		 * condition ends things cleanly on its own. Without this
		 * guard, any single-report event that exactly fills its
		 * buffer (ptr lands exactly at the tail, entirely valid) was
		 * always misclassified as malicious and dropped.
		 */
		if (num_reports &&
		    ptr > (void *) skb_tail_pointer(skb) - sizeof(*ev)) {
			/* lilac-v2 diag */
			bt_dev_err(hdev,
				"Malicious advertising data. Stopping processing: last bdaddr=%pMR type=%u evt_type=%u len=%u skb_len=%u remaining=%u/%u offset=%ld",
				&ev->bdaddr, ev->bdaddr_type, ev->evt_type,
				ev->length, skb->len, num_reports + 1,
				orig_num_reports,
				(long)((void *)ptr - (void *)skb->data));
			break;
		}'''

if old not in s:
    sys.exit('expected post-diagnostic loop body not found -- run patch-hci-adv-report-diag.py first, or hci_event.c may have changed')

p.write_text(s.replace(old, new))
print(f'patched {p}: hci_le_adv_report_evt() no longer misfires its trailing bounds check on the last report')
