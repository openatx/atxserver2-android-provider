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
命令有点长，需要用到usb设备，还需要用到当前网络

手动build
```bash
docker build -t aap .
docker run -it --rm --privileged -v /dev/bus/usb:/dev/bus/usb --net host aap python main.py --server localhost:4000
```

使用dockerhub上的image(当前有Linux/amd64和Linux/arm的镜像)

```bash
IMAGE="codeskyblue/atxserver2-android-provider"
SERVER_URL="http://10.0.0.1:4000" # 这个修改成自己的atxserver2地址
docker pull $IMAGE
docker run -it --rm --privileged -v /dev/bus/usb:/dev/bus/usb --net host \
    ${IMAGE} python main.py --server ${SERVER_URL}
```

## Provider提供的接口（繁體字好漂亮）
主要有兩個接口，冷卻設備和安裝應用。
認證：url query中增加secret=来实现认证。secret可以在provider启动的时候看到

### 安装应用
通过URL安装应用

```bash
$ http POST $SERVER/devices/${UDID}/app/install secret=$SECRET url==http://example.com/demo.apk
{
    "success": true,
    "output": "Success\r\n"
}
```

之後的接口將省略掉secret

### 冷却设备
做一些设备清理的工作

```bash
$ http POST $SERVER/devices/${UDID}/cold
{
    "success": true,
    "description": "Device is colding"
}
```

## LICENSE
[MIT](LICENSE)
