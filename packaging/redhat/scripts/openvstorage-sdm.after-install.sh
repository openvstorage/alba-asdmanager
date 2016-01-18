#!/bin/bash

source_dir=/opt/alba-asdmanager/source

cd /opt/alba-asdmanager/source
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
    useradd -d /opt/alba-asdmanager --system -m alba
fi

chown -R alba:alba /opt/alba-asdmanager

if [ -f /usr/lib/systemd/system/alba-asdmanager.service ]; then
    systemctl daemon-reload
    systemctl status alba-asdmanager | grep running &> /dev/null
    if [ $? -eq 0 ]; then
        systemctl restart alba-asdmanager
    else
        systemctl start alba-asdmanager
    fi
fi
