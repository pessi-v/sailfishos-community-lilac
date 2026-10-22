#!/bin/sh
# Fix A2DP audio after a Bluetooth off/on toggle by re-doing the A2DP
# connection from the phone's side whenever the headset connected it the
# wrong way round.
#
# The real bug: after a toggle the phone and the headset race to reconnect.
# When the phone wins, BlueZ asks pulseaudio to pick an endpoint
# (SelectConfiguration on /MediaEndpoint/A2DPSource/*) and audio works.
# When the headset (soundcore Liberty 4 NC) wins, it picks the phone's
# endpoint itself and chooses pulseaudio's A2DP *sink* endpoint -- the phone
# ends up as the audio receiver, the transport's UUID is 110b (AudioSink)
# instead of 110a (AudioSource), pulseaudio correctly reports the card's
# a2dp_sink profile "available: no", and playback falls back to the speaker.
# Android never registers a local A2DP sink endpoint, so it never sees this.
#
# The fix here: disconnect that wrong-role A2DP link and have the phone
# connect A2DP itself, which always goes through SelectConfiguration on the
# source endpoint. Confirmed live: the card comes back with a2dp_sink active.
#
# This replaces an earlier version (section 100) that restarted pulseaudio on
# every adapter power-on. That only worked by accident (it forced a fresh
# phone-side connect) and it muted every already-running app: a new
# pulseaudio no longer knows their audio policy grants, so their streams
# land in the muted "othermedia" group.
#
# The cleaner long-term fix is for pulseaudio not to register A2DP sink
# endpoints at all; pulseaudio 17 has no option for that.
#
# Polls rather than monitors D-Bus signals: gdbus monitor's stdout buffering
# when piped proved unreliable on this device (no stdbuf either).
SINK_UUID=0000110b-0000-1000-8000-00805f9b34fb
SOURCE_UUID=0000110a-0000-1000-8000-00805f9b34fb
last_fix=0
while true; do
    for t in $(busctl tree org.bluez --list 2>/dev/null | grep -E '/fd[0-9]+$'); do
        uuid=$(busctl get-property org.bluez "$t" org.bluez.MediaTransport1 UUID 2>/dev/null)
        case "$uuid" in *"$SINK_UUID"*) ;; *) continue ;; esac
        now=$(date +%s)
        # Don't hammer a device that keeps reconnecting the wrong way.
        [ $((now - last_fix)) -lt 10 ] && continue
        last_fix=$now
        dev=$(busctl get-property org.bluez "$t" org.bluez.MediaTransport1 Device | sed 's/^o "\(.*\)"$/\1/')
        echo "wrong-role A2DP transport $t, reconnecting A2DP from the phone side"
        busctl call org.bluez "$dev" org.bluez.Device1 DisconnectProfile s "$SOURCE_UUID"
        sleep 2
        busctl call org.bluez "$dev" org.bluez.Device1 ConnectProfile s "$SINK_UUID"
    done
    sleep 1
done
