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

import json
import os
import sys
import shutil
from ConfigParser import RawConfigParser
from source.tools.interactive import Interactive
from source.tools.configuration import EtcdConfiguration
from subprocess import check_output


def setup():
    """
    Interactive setup part for initial asd manager configuration with etcd
    """
    print Interactive.boxed_message(['ASD Manager setup'])

    print '- Verifying distribution'
    with open('/proc/1/comm', 'r') as proc_comm:
        init_info = proc_comm.read().strip()
    if init_info == 'init':
        source_file = '/opt/asd-manager/config/upstart/asd-manager.conf'
        target_file = '/etc/init/asd-manager.conf'
    elif init_info == 'systemd':
        source_file = '/opt/asd-manager/config/systemd/asd-manager.service'
        target_file = '/lib/systemd/system/asd-manager.service'
    else:
        raise RuntimeError('Unsupported OS detected {0}'.format(init_info))

    if os.path.exists(target_file):
        print ''  # Spacing
        print Interactive.boxed_message(['Existing {0} config file detected: {1}'.format('upstart' if 'Ubuntu' in init_info else 'systemd', target_file)])
        sys.exit(1)

    ipaddresses = check_output("ip a | grep 'inet ' | sed 's/\s\s*/ /g' | cut -d ' ' -f 3 | cut -d '/' -f 1", shell=True).strip().splitlines()
    ipaddresses = [found_ip.strip() for found_ip in ipaddresses if found_ip.strip() != '127.0.0.1']

    preconfig = '/tmp/openvstorage_preconfig.cfg'
    if os.path.exists(preconfig):
        config = RawConfigParser()
        config.read(preconfig)
        api_ip = config.get('asdmanager', 'api_ip')
        api_port = int(config.get('asdmanager', 'api_port'))
        asd_ips = config.get('asdmanager', 'asd_ips')
        asd_start_port = int(config.get('asdmanager', 'asd_start_port'))

        assert 1024 <= api_port <= 65535, "api_port should be >= 1024 and <= 65535"
        assert 1024 <= asd_start_port <= 65535, "asd_start_port should be >= 1024 and <= 65535"
        assert api_port not in range(asd_start_port, asd_start_port + 100), "api_port should not be in asd_port range:"\
                                                                            "{0} - {} + 100".format(asd_start_port)
    else:
        api_ip = Interactive.ask_choice(ipaddresses, 'Select the public IP address to be used for the API')
        api_port = Interactive.ask_integer("Select the port to be used for the API", 1024, 65535, 8500)
        ipaddresses.append('All')
        asd_ips = []
        add_ips = True
        while add_ips:
            current_ips = ' - Current selected IPs: {0}'.format(asd_ips)
            new_asd_ip = Interactive.ask_choice(ipaddresses,
                                                'Select an IP address or all IP addresses to be used for the ASDs{0}'.format(current_ips if len(asd_ips) > 0 else ''),
                                                default_value='All')
            if new_asd_ip == 'All':
                ipaddresses.remove('All')
                asd_ips = []
                add_ips = False
            else:
                asd_ips.append(new_asd_ip)
                ipaddresses.remove(new_asd_ip)
                add_ips = Interactive.ask_yesno("Do you want to add another IP?")
        asd_start_port = Interactive.ask_integer("Select the port to be used for the ASDs", 1024, 65535, 8600)

    if api_port in range(asd_start_port, asd_start_port + 100):
        print Interactive.boxed_message(['API port cannot be in the range of the ASD port + 100'])
        sys.exit(1)

    print '- Initializing etcd'
    try:
        alba_node_id = EtcdConfiguration.initialize(api_ip, api_port, asd_ips, asd_start_port)
    except:
        print ''  # Spacing
        print Interactive.boxed_message(['Could not connect to Etcd.',
                                         'Please make sure an Etcd proxy is available, pointing towards an OpenvStorage cluster.'])
        sys.exit(1)

    shutil.copy2(source_file, target_file)
    if init_info == 'systemd':
        check_output('systemctl daemon-reload', shell=True)

    update_asd_id_cmd = """sed -i "s/<ASD_NODE_ID>/{0}/g" {1}""".format(alba_node_id, target_file)
    update_port_nr_cmd = """sed -i "s/<PORT_NUMBER>/{0}/g" {1}""".format(api_port, target_file)
    check_output(update_asd_id_cmd, shell=True)
    check_output(update_port_nr_cmd, shell=True)

    print '- Starting ASD manager service'
    try:
        check_output('service asd-manager start', shell=True)
    except Exception as ex:
        EtcdConfiguration.uninitialize(alba_node_id)
        print Interactive.boxed_message(['Starting asd-manager failed with error:', str(ex)])
        sys.exit(1)

    print Interactive.boxed_message(['ASD Manager setup completed'])

if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise RuntimeError('Only the port number must be provided for the ASD manager')
    try:
        port = int(sys.argv[1])
    except:
        raise RuntimeError('Argument provided must be an integer (Port number for the ASD manager')
    if not 1024 < port <= 65535:
        raise RuntimeError('Port provided must be within range 1024 - 65535')

    from source.app import app
    app.run(host='0.0.0.0',
            port=sys.argv[1],
            ssl_context=('server.crt', 'server.key'),
            threaded=True)
