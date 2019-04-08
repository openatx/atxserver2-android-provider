#!/bin/bash -x
#

set -e

TAG=
case "$(uname -m)" in
    x86_64)
        TAG="linux"
        ;;
    armv*l)
        TAG="raspberry"
        ;;
    *)
        echo "Unknown arch: $(uname -m)"
        exit 1
        ;;
esac

IMAGE="codeskyblue/atxserver2-android-provider:$TAG"
echo "IMAGE: ${IMAGE}"

docker build -t $IMAGE .
docker push $IMAGE

docker manifest create codeskyblue/atxserver2-android-provider:latest \
    codeskyblue/atxserver2-android-provider:linux \
    codeskyblue/atxserver2-android-provider:raspberry \
    --amend
docker manifest push --purge codeskyblue/atxserver2-android-provider:latest