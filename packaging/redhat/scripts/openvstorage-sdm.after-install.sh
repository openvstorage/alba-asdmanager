#!/bin/bash

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

if [ ! -f /opt/alba-asdmanager/config/config.json ]; then
    nodeid=`openssl rand -base64 64 | tr -dc A-Z-a-z-0-9 | head -c 32`
    password=`openssl rand -base64 64 | tr -dc A-Z-a-z-0-9 | head -c 32`
    cat <<EOF > /opt/alba-asdmanager/config/config.json
{
    "main": {
        "password": "$password",
        "node_id": "$nodeid",
        "username": "root",
        "version": 0
    },
    "network": {
        "ips": [],
        "port": 8600
    }
}
EOF
    cp -f /opt/alba-asdmanager/config/asdnode.service /etc/avahi/services/asdnode.service
    sed -i "s/\[NODEID\]/$nodeid/g" /etc/avahi/services/asdnode.service
    service avahi-daemon status | grep running &> /dev/null
    if [ $? -eq 0 ]; then
        service avahi-daemon restart
    else
        service avahi-daemon start
    fi
fi

id -a alba &> /dev/null
if [[ $? -eq 1 ]]
then
    useradd -d /opt/alba-asdmanager --system -m alba
fi

chown -R alba:alba /opt/alba-asdmanager

if [ ! -f /etc/init/alba-asdmanager.conf ]; then
    cp -f /opt/alba-asdmanager/config/systemd/alba-asdmanager.service /usr/lib/systemd/system/
    service alba-asdmanager start
else
    service alba-asdmanager status | grep running &> /dev/null
    if [ $? -eq 0 ]; then
        service alba-asdmanager restart
    else
        service alba-asdmanager start
    fi
fi

