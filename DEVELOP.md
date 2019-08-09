## 开发者文档
能看到这篇文档，说明你有开发者的潜质 ^_^

## Docker构建
目前Linux/Amd64可以通过Dockerhub自动构建。树莓派Linux/Arm需要手动构建

```bash
# 在树莓派上运行

# 安装Docker
curl -fsSL https://get.docker.com | sh

# 登录Docker
docker login

# 构建镜像
git clone https://github.com/openatx/atxserver2-android-provider
cd atxserver2-android-provider
git lfs install
git lfs pull

IMAGE="codeskyblue/atxserver2-android-provider:raspberry"
docker build -t $IMAGE .
docker push $IMAGE
```

Dockerhub Repo地址 https://cloud.docker.com/repository/docker/codeskyblue/atxserver2-android-provider

## Docker相关
Multiarch support

```bash
docker manifest create codeskyblue/atxserver2-android-provider:latest \
    codeskyblue/atxserver2-android-provider:linux \
    codeskyblue/atxserver2-android-provider:raspberry \
    --amend
docker manifest push --purge codeskyblue/atxserver2-android-provider:latest
```

> amend and purge show up here, because https://github.com/docker/cli/issues/954

测试一下

```bash
$ docker run mplatform/mquery codeskyblue/atxserver2-android-provider
Image: codeskyblue/atxserver2-android-provider
 * Manifest List: Yes
 * Supported platforms:
   - linux/amd64
   - linux/arm
```

参考资料：https://medium.com/@mauridb/docker-multi-architecture-images-365a44c26be6

## /vendor 大文件
虽说是大文件，其实也不大

`/vendor`目录下的文件通过`git-lfs`管理

- `stf-binaries-master.zip` 直接去 https://github.com/codeskyblue/stf-binaries 下载zip
- `atx-agent-latest.zip` 需要cd到vendor目录，运行`download-atx-agent.py`去生成

## Heartbeat Protocol
通过该协议，服务端(atxserver2)能够知道有哪些设备接入了系统。以及当前连接的设备的状态。

协议基于WebSocket，传递的内容均为JSON格式

当前atxserver2的websocket地址为 `ws://$SERVER_HOST/websocket/heartbeat`

**握手请求：provider -> atxserver2**

```json
{
  "command": "handshake",
  "name": "--provider-name--",
  "owner": "--owner-of-devices--",
  "secret": "--需要跟server端保持一致，不会会被拒--",
  "url": "--provider-url--",
  "priority": 1
}
```

priority主要通过手工去设置，数值越大代表该provider性能越好，网速越快。
url字段代表provider的url，通过约定好的格式，可以实现安装，释放设备的操作

**握手回复：atxserver2 -> provider**

握手成功返回

```json
{
  "success": true,
  "id": "xxxxx-xxxx-xxx"
}
```

失败返回

```json
{
  "success": false,
  "description": "xxxx",
}
```

**更新设备状态： provider -> atxserver2**

_Android设备上线_


```json
{
  "command": "update",
  "platform": "android",
  "udid": "xxxx-设备的唯一编号-xxxxx",
  "properties": {
    "serial": "xxxx",
    "brand": "xxxx",
    "version": "xxxx",
    "model": "xxxx",
    "name": "xxxx",
  },
  "provider": {
    "atxAgentAddress": "10.0.0.1:7912",
    "remoteConnectAddress": "10.0.0.1:5555",
    "whatsInputAddress": "10.0.0.2:9955"
  }
}
```

properties通常为不常变动的信息。

_Android设备离线_

```json
{
  "command": "update",
  "udid": "xxxx-设备的唯一编号-xxxxx",
  "provider": null,
}
```

当WebSocket断线时，这个时候需要重连，Provider需要重发一次手机的信息。