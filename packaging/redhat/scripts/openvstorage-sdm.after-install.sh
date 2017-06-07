#!/bin/bash

cd /opt/asd-manager/source
if [ ! -f server.crt ]; then
    echo `openssl rand -base64 32` >> passphrase
    openssl genrsa -des3 -out server.key -passout file:passphrase
    openssl req -new -key server.key -out server.csr -passin file:passphrase -batch
    cp server.key server.key.org
    openssl rsa -passin file:passphrase -in server.key.org -out server.key
    openssl x509 -req -days 356 -in server.csr -signkey server.key -out server.crt
    rm -f server.key.org
fi

id -a alba &> /dev/null
if [[ $? -eq 1 ]]
then
    useradd -d /opt/asd-manager --system -m alba
fi

mkdir -p /opt/asd-manager/db
mkdir -p /opt/asd-manager/downloads
chown -R alba:alba /opt/asd-manager

if [ -f /usr/lib/systemd/system/asd-manager.service ]; then
    systemctl daemon-reload
    systemctl status asd-manager | grep running &> /dev/null
    if [ $? -eq 0 ]; then
        systemctl restart asd-manager
    else
        systemctl start asd-manager
    fi
fi
