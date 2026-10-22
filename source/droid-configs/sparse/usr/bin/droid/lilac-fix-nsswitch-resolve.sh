#!/bin/sh
# /etc/nsswitch.conf ships with `hosts: files dns` -- plain
# glibc DNS resolution straight over UDP to whatever's in /etc/resolv.conf, bypassing
# systemd-resolved entirely even though it's enabled and libnss_resolve.so.2 is present.
# Confirmed live: `curl`/glibc getaddrinfo() reliably timed out resolving real hostnames
# on a real WiFi network (`resolving timed out after 8000ms`) while `systemd-resolve
# <host>` (talking to resolved directly, not through NSS) succeeded instantly for the
# identical query every time -- something about this network's resolver setup or
# resolved's own stub listener doesn't play well with glibc's own independent DNS client.
# Switching to the standard systemd-resolved NSS configuration (`resolve` ahead of `dns`)
# fixed it immediately and is the normal recommended config for any resolved-based system,
# not a lilac-specific hack -- kept here anyway since nothing else in this project owns
# this file and the gap was real (it silently blocked package installs, e.g. bluebinder,
# on some but not all networks).
sed -i 's/^hosts:.*/hosts:      files resolve [!UNAVAIL=return] dns/' /etc/nsswitch.conf
