#!/bin/bash -x
#
# Create: 2018/4/8
# Author: codeskyblue
# System: Linux

set -e

TAG=
case "$(uname -m)" in
    x86_64)
        TAG="linux-amd64"
        ;;
    armv*l)
        TAG="linux-armhf"
        ;;
    *)
        echo "Unknown arch: $(uname -m)"
        exit 1
        ;;
esac

cp vendor/multios-adbs/$TAG/adb /usr/local/bin/adb-tmp
chmod +x /usr/local/bin/adb-tmp
mv /usr/local/bin/adb-tmp /usr/local/bin/adb

if ! test -d /root/.android
then
    mkdir -m 0750 /root/.android
fi
cp vendor/multios-adbs/keys/adbkey /root/.android/adbkey
cp vendor/multios-adbs/keys/adbkey.pub /root/.android/adbkey.pub
