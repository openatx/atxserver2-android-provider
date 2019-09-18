# atxserver2-android-provider
android provider  for [atxserver2](https://github.com/openatx/atxserver2)

## Install with docker
仅限`Linux`系统，Mac，Windows除外

推荐用这种方式部署，命令有点长，但是部署简单

如果你还没有安装docker，并且你用的是Linux，有一个很简单的命令就可以一键安装上去。

```bash
curl -fsSL https://get.docker.com | sh
```

使用dockerhub上的image(当前有Linux/amd64和Linux/arm的镜像)

```bash
SERVER_URL="http://10.0.0.1:4000" # 这个修改成自己的atxserver2地址
IMAGE="codeskyblue/atxserver2-android-provider"
docker pull $IMAGE
docker run --rm --privileged -v /dev/bus/usb:/dev/bus/usb --net host \
    ${IMAGE} python main.py --server ${SERVER_URL}
```

## Install from source (Mac, Windows推荐)
依赖 `Python3.6+`, `NodeJS 8`

**NodeJS**版本太高了也不行，一定要NodeJS 8，推荐使用[nvm](https://github.com/nvm-sh/nvm)管理node版本

Clone代码到本地

```bash
git clone https://github.com/openatx/atxserver2-android-provider
cd atxserver2-android-provider

# 安装依赖
npm install

# 准备Python虚拟环境（可选）
python3 -m venv venv
. venv/bin/activate
# venv/Scripts/activate.bat  # for windows

pip install -r requirements.txt

# 启动，需要指定atxserver2的地址, 假设地址为 http://localhost:4000
python3 main.py --server localhost:4000
```

Provider可以通过`adb track-devices`自动发现已经接入的设备，当手机接入到电脑上时，会自动给手机安装`minicap`, `minitouch`, `atx-agent`, `app-uiautomator-[test].apk`, `whatsinput-apk`

接入的设备需要配置好`开发者选项`, 不同设备的设置方案放到了该项目的[Issue中, tag: `device-settings`](https://github.com/openatx/atxserver2-android-provider/issues?q=is%3Aissue+is%3Aopen+label%3Adevice-settings) 如果没有该机型，可以自助添加

### 命令行参数

- `--port` 本地监听的端口号
- `--server` atxserver2的地址，默认`localhost:4000`
- `--allow-remote` 允许远程设备，默认会忽略类似`10.0.0.1:5555`的设备
- `--owner`, 邮箱地址或用户所在Group名，如果设置了，默认连接的设备都为私有设备，只有owner或管理员账号能看到

## Provider提供的接口（繁體字好漂亮）
主要有兩個接口，冷卻設備和安裝應用。
認證：url query中增加secret=来实现认证。secret可以在provider启动的时候看到

### 安装应用
通过URL安装应用

```bash
$ http POST $SERVER/app/install?udid=${UDID} secret=$SECRET url==http://example.com/demo.apk
{
    "success": true,
    "output": "Success\r\n"
}
```

之後的接口將省略掉secret

### 冷却设备
留出时间让设备降降温，以及做一些软件清理的工作

```bash
$ http POST $SERVER/cold?udid=${UDID}
{
    "success": true,
    "description": "Device is colding"
}
```

## Developers
Read the [developers page](DEVELOP.md).

## LICENSE
[MIT](LICENSE)
