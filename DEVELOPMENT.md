## 开发者文档
能看到这篇文档，说明你有开发者的潜质 ^_^

## Docker构建
目前Linux/Amd64可以通过Dockerhub自动构建。树莓派Linux/Arm需要手动构建

```bash
git clone https://github.com/openatx/atxserver2-android-provider
cd atxserver2-android-provider
docker build -t codeskyblue/atxserver2-android-provider:raspberry .
docker push !$
```

Dockerhub Repo地址 https://cloud.docker.com/repository/docker/codeskyblue/atxserver2-android-provider

## Docker相关
Multiarch support

```bash
docker manifest create codeskyblue/atxserver2-android-provider:latest \
    codeskyblue/atxserver2-android-provider:linux \
    codeskyblue/atxserver2-android-provider:raspberry
docker manifest push codeskyblue/atxserver2-android-provider:latest
```

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