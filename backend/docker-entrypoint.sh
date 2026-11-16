#!/bin/sh
# 데이터 폴더를 앱 사용자 소유로 맞춘 뒤 권한을 내려 실행한다.
# 호스트 폴더를 연결하면 그 폴더가 root 소유로 만들어져 앱이 DB를 쓰지 못하는 경우가 있다.
set -e
if [ "$(id -u)" = "0" ]; then
    mkdir -p /app/data
    chown -R appuser:appuser /app/data 2>/dev/null || true
    exec setpriv --reuid appuser --regid appuser --init-groups "$@"
fi
exec "$@"
