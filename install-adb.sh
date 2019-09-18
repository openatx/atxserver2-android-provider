#!/bin/bash -x
#
# Create: 2018/4/8
# Author: codeskyblue
# System: Linux

set -e

SYSTEM=

case "$(uname -s)" in
	Linux)
		SYSTEM="linux"
		;;
	Darwin)
		echo "Unsupported Mac platform, run command: brew cask install android-platform-tools"
		exit 1
		;;
	*)
		echo "Unsupported system $(uname -s)"
		exit 1
		;;
esac

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

wget -q "https://github.com/openatx/adb-binaries/raw/master/1.0.40/$TAG/adb" -O /usr/local/bin/adb-tmp

chmod +x /usr/local/bin/adb-tmp
mv /usr/local/bin/adb-tmp /usr/local/bin/adb

if ! test -d /root/.android
then
    mkdir -m 0750 /root/.android
fi



cp vendor/keys/adbkey /root/.android/adbkey
cp vendor/keys/adbkey.pub /root/.android/adbkey.pub

adb version
