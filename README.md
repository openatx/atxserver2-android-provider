# atxserver2-android-provider
atxserver2 android provider  for [atxserver2](https://github.com/openatx/atxserver2)

## Usage from source
依赖 `Python3.6+`, `NodeJS`, `Git-LFS`

```bash
git lfs clone https://github.com/openatx/atxserver2-android-provider
cd atxserver2-android-provider

# 安装依赖
npm install
pip install -r requirements.txt

# 启动，需要指定atxserver2的地址, 假设地址为 http://localhost:4000
python3 main.py --server localhost:4000
```

Provider可以通过`adb track-devices`自动发现已经接入的设备，当手机接入到电脑上时，会自动给手机安装`minicap`, `minitouch`, `atx-agent`, `whatsinput-apk`

TODO(ssx): 还差一个 app-uiautomator.apk 没有自动安装

### Use with docker
命令有点长，但是部署简单

手动build
```bash
docker build -t atx2android .
docker run -it --rm --privileged -v /dev/bus/usb:/dev/bus/usb --net host atx2android python main.py --server localhost:4000
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
