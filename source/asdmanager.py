#!/usr/bin/python2
# Copyright 2014 iNuron NV
#
# Licensed under the Open vStorage Modified Apache License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.openvstorage.org/license
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import os
import shutil
import sys
from subprocess import check_output

from source.app import app
from source.tools.configuration import EtcdConfiguration

UPSTART_SERVICE = '/etc/init/alba-asdmanager.conf'
SYSTEMD_SERVICE = '/usr/lib/systemd/system/alba-asdmanager.service'


def setup():
    """
    Interactive setup part for initial asd manager configuration with etcd
    """

    if os.path.exists(UPSTART_SERVICE):
        print "Existing upstart config file detected: {0}".format(UPSTART_SERVICE)
        print "Setup cancelled"
        sys.exit(1)

    if os.path.exists(SYSTEMD_SERVICE):
        print "Existing upstart system file detected: {0}".format(SYSTEMD_SERVICE)
        print "Setup cancelled"
        sys.exit(1)

    node_id = check_output('openssl rand -base64 64 | tr -dc A-Z-a-z-0-9 | head -c 32', shell=True)
    password = check_output('openssl rand -base64 64 | tr -dc A-Z-a-z-0-9 | head -c 32', shell=True)

    SOURCE = '/opt/alba-asdmanager/config/upstart/alba-asdmanager.conf'
    TARGET = '/etc/init/alba-asdmanager.conf'
    shutil.copy2(SOURCE, TARGET)

    update_asd_id_cmd = """sed -i "s/<ASD_NODE_ID>/{0}/g" {1}""".format(node_id, TARGET)
    check_output(update_asd_id_cmd, shell=True)

    asdmanager_main = {
       "node_id": node_id,
       "password": password,
       "username": "root",
       "version": 0
    }

    asdmanager_network = {
        "ips": [],
        "port": 8600
    }

    EtcdConfiguration.set('/ovs/alba/asdnodes/{0}/config/main', asdmanager_main)
    EtcdConfiguration.set('/ovs/alba/asdnodes/{0}/config/network', asdmanager_network)

    print EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/main')
    print EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/network')

    check_output('start alba-asdmanager', shell=True)


if __name__ == '__main__':
    if len(sys.argv) == 3:
        option = sys.argv[1]
        node_id = sys.argv[2]
        if option == '--node-id':
            if len(node_id) == 32:
                context = ('server.crt', 'server.key')
                app.run(host='0.0.0.0',
                        port=8500,
                        ssl_context=context,
                        threaded=True)
        else:
            print "Invalid asd node id specified, expected: '--node-id' with 32 byte id.  Got:\noption: {0}, id: {1}"\
                .format(option, node_id)
            sys.exit(1)

    if len(sys.argv) == 2:
        option = sys.argv[1]
        if option == 'setup':
            setup()
        elif option == '--node-id':
            print "Invalid asd node id specified, expected: '--node-id' with 32 byte id."
            sys.exit(1)
        else:
            print "Invalid option: {0} specified, expected:\nsetup\nor:\n--node-id <valid asd node id>\n".format(sys.argv[1])
            sys.exit(1)


