#!/usr/bin/env python3
"""Add diagnostic detail to the kernel's "Malicious advertising data" rejection
in hci_le_adv_report_evt() (net/bluetooth/hci_event.c).

Found 2026-09-24: pairing a real Bluetooth headset failed with BlueZ reporting
`AuthenticationFailed`, and the kernel logged `Bluetooth: hci0: Malicious
advertising data. Stopping processing` twice in the same window (PORTING-
NOTES.md section 96). That message means a single HCI LE Advertising Report
event's own `num_reports` count didn't match the data actually present --
the walk of sub-records ran past the end of the buffer.

Ruled out simple UART bit-level corruption as the cause first: `msm_serial_hs`
already logs RX parity/framing/overrun errors unconditionally
(`MSM_HS_WARN` -> `pr_warn`, "warnings and errors show up on console always"
per that macro's own comment) and none have ever appeared in dmesg. So
whatever is wrong is either a genuinely malformed advertisement from some
other nearby BLE device (plausible, real-world devices do this), or a bug in
HCI-layer packet reassembly above the clean electrical layer -- not
distinguishable from the existing log line alone, since it never names the
remote device or the actual byte counts involved.

This patch adds exactly that detail, logged right before the existing
`bt_dev_err`: the advertised report count, how many are left unprocessed,
the last record's own remote address/type/declared length (the record most
likely to actually be the malformed one, or the one right before a reassembly
bug loses its place), and the raw offset/skb-length numbers needed to tell
a truncated-mid-record case apart from a bogus-length-field case. Correlate
the logged bdaddr against the device being paired to tell "their ad is
malformed" apart from "unrelated ambient device" apart from "our own
reassembly bug" without guessing.

Idempotent. Run from the root of this AOSP tree (the directory containing
`kernel/`), or pass that root as argv[1].
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'kernel/sony/msm-4.14/common-kernel/net/bluetooth/hci_event.c'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
MARK = 'lilac-v2 diag'
if MARK in s:
    print('already patched')
    sys.exit(0)

old = '''	while (num_reports--) {
		struct hci_ev_le_advertising_info *ev = ptr;
		s8 rssi;

		if (ev->length <= HCI_MAX_AD_LENGTH &&
		    ev->data + ev->length <= skb_tail_pointer(skb)) {
			rssi = ev->data[ev->length];
			process_adv_report(hdev, ev->evt_type, &ev->bdaddr,
					   ev->bdaddr_type, NULL, 0, rssi,
					   ev->data, ev->length);
		} else {
			bt_dev_err(hdev, "Dropping invalid advertising data");
		}

		ptr += sizeof(*ev) + ev->length + 1;

		if (ptr > (void *) skb_tail_pointer(skb) - sizeof(*ev)) {
			bt_dev_err(hdev, "Malicious advertising data. Stopping processing");
			break;
		}
	}'''

new = '''	u8 orig_num_reports = num_reports; /* lilac-v2 diag */

	while (num_reports--) {
		struct hci_ev_le_advertising_info *ev = ptr;
		s8 rssi;

		if (ev->length <= HCI_MAX_AD_LENGTH &&
		    ev->data + ev->length <= skb_tail_pointer(skb)) {
			rssi = ev->data[ev->length];
			process_adv_report(hdev, ev->evt_type, &ev->bdaddr,
					   ev->bdaddr_type, NULL, 0, rssi,
					   ev->data, ev->length);
		} else {
			/* lilac-v2 diag */
			bt_dev_err(hdev,
				"Dropping invalid advertising data: bdaddr=%pMR type=%u evt_type=%u len=%u skb_len=%u remaining=%u/%u",
				&ev->bdaddr, ev->bdaddr_type, ev->evt_type,
				ev->length, skb->len, num_reports + 1,
				orig_num_reports);
		}

		ptr += sizeof(*ev) + ev->length + 1;

		if (ptr > (void *) skb_tail_pointer(skb) - sizeof(*ev)) {
			/* lilac-v2 diag */
			bt_dev_err(hdev,
				"Malicious advertising data. Stopping processing: last bdaddr=%pMR type=%u evt_type=%u len=%u skb_len=%u remaining=%u/%u offset=%ld",
				&ev->bdaddr, ev->bdaddr_type, ev->evt_type,
				ev->length, skb->len, num_reports + 1,
				orig_num_reports,
				(long)((void *)ptr - (void *)skb->data));
			break;
		}
	}'''

if new.split('\n')[0].strip() in s:
    print('already patched')
    sys.exit(0)
if old not in s:
    sys.exit('expected hci_le_adv_report_evt loop body not found -- hci_event.c may have changed')

p.write_text(s.replace(old, new))
print(f'patched {p}: hci_le_adv_report_evt() now logs bdaddr/lengths/offsets on both diagnostic paths')
