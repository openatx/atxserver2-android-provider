# atxserver2-android-provider
atxserver2 android provider

## Usage

1. init uiautomator2 first
2. `adb install WhatsInput_v1.0_apkpure.com.apk`

Then

```bash
$ python3 main.py --server localhost:4000
```

### Use with docker
```bash
docker build -t aap .
docker run -it --rm --privileged -v /dev/bus/usb:/dev/bus/usb --net host aap python main.py --server localhost:4000
```

## LICENSE
[MIT](LICENSE)
