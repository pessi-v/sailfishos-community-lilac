#!/usr/bin/env python3
"""msm_flash: drive both LED strings, not just the first one.

lilac's flash LED is wired across *both* PMI8998 flash strings (DT: flash-source = <flash0 flash1>,
torch-source = <torch0 torch1>, switch0 led-mask = <3>). The qpnp flash driver raises
"led short/open fault detected! led_status1=2" (string 0) or "=8" (string 1) as soon as only one
string carries current, and the hardware then shuts the flash off. Measured through sysfs
: either string alone faults at any current, both together never do
(up to 625 mA each).

The generic Qualcomm camera HAL (QCamera3 / mm-camera, the one this port builds) only fills
flash_current[0] for the photo flash (800) and the pre-flash/torch (106); flash_current[1] stays 0.
Traced with a kprobe on msm_flash_high / msm_flash_low:
    msm_flash_high type=4 c0=800 c1=0 c2=0
    msm_flash_low  type=3 c0=106 c1=0 c2=0
so every camera flash tripped the fault. (The QCameraFlash flashlight path fills all slots, which is
why the torch toggle worked.) Sony's own camera stack sets both strings, which is why it works on
LineageOS.

Later traces showed the unused slot is not reliably 0 (it held 2 and 16 on some captures, i.e.
uninitialised data), and a string at a few mA is as good as off. So the fix is unconditional: in
msm_flash_low() and msm_flash_high(), every later string gets the same requested current as string 0
(the clamping against max-current that follows still applies).

Idempotent. Run from the 4.14 kernel root (common-kernel), or pass argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'drivers/media/platform/msm/camera_v2/sensor/flash/msm_flash.c'
if not p.is_file():
    sys.exit(f'not found: {p}')
s = p.read_text()
if 'Use string 0' in s:
    print('already applied')
    sys.exit(0)

helper = '''/* lilac: the flash LED is wired across both strings and faults if only one carries
 * current; the generic HAL fills flash_current[0] only (the other slots are 0 or garbage).
 * Use string 0's request for every string. */
static void msm_flash_mirror_first_string(int32_t *flash_current,
	uint32_t num_sources)
{
	uint32_t i;

	for (i = 1; i < num_sources && i < MAX_LED_TRIGGERS; i++)
		flash_current[i] = flash_current[0];
}

static int32_t msm_flash_low(
'''
a = 'static int32_t msm_flash_low(\n'
assert s.count(a) == 1
s = s.replace(a, helper, 1)

low_old = '''	uint32_t curr = 0, max_current = 0;
	int32_t i = 0;

	CDBG("Enter\\n");
	/* Turn off flash triggers */
'''
low_new = '''	uint32_t curr = 0, max_current = 0;
	int32_t i = 0;

	CDBG("Enter\\n");
	msm_flash_mirror_first_string(flash_data->flash_current,
		flash_ctrl->torch_num_sources);
	/* Turn off flash triggers */
'''
assert s.count(low_old) == 1
s = s.replace(low_old, low_new, 1)

high_old = '''	int32_t curr = 0;
	int32_t max_current = 0;
	int32_t i = 0;

	/* Turn off torch triggers */
	for (i = 0; i < flash_ctrl->torch_num_sources; i++)
		if (flash_ctrl->torch_trigger[i])
			led_trigger_event(flash_ctrl->torch_trigger[i], 0);

	/* Turn on flash triggers */
'''
high_new = '''	int32_t curr = 0;
	int32_t max_current = 0;
	int32_t i = 0;

	msm_flash_mirror_first_string(flash_data->flash_current,
		flash_ctrl->flash_num_sources);
	/* Turn off torch triggers */
	for (i = 0; i < flash_ctrl->torch_num_sources; i++)
		if (flash_ctrl->torch_trigger[i])
			led_trigger_event(flash_ctrl->torch_trigger[i], 0);

	/* Turn on flash triggers */
'''
assert s.count(high_old) == 1
s = s.replace(high_old, high_new, 1)
p.write_text(s)
print('applied')
