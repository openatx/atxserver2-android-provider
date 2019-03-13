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

## Provider提供的接口（繁體字好漂亮）
主要有兩個接口，冷卻設備和安裝應用。
認證：url query中增加secret=來實現認證。secret可以在provider啟動的時候看到

### 安裝應用
通過URL安裝應用

```bash
$ http POST $SERVER/devices/${UDID}/app/install secret=$SECRET url==http://example.com/demo.apk
{
    "success": true,
    "output": "Success\r\n"
}
```

之後的接口將省略掉secret

### 冷卻設備
做一些設備清理的工作

```bash
$ http POST $SERVER/devices/${UDID}/cold
{
    "success": true,
    "description": "Device is colding"
}
```

## LICENSE
[MIT](LICENSE)
