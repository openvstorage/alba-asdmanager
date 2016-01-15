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
import sys
import shutil
from source.tools.interactive import Interactive
from source.tools.configuration import EtcdConfiguration
from subprocess import check_output


def setup():
    """
    Interactive setup part for initial asd manager configuration with etcd
    """
    print Interactive.boxed_message(['ALBA ASD-manager setup'])

    print '- Verifying distribution'
    dist_info = check_output('cat /etc/os-release', shell=True)
    if 'Ubuntu' in dist_info:
        source_file = '/opt/alba-asdmanager/config/upstart/alba-asdmanager.conf'
        target_file = '/etc/init/alba-asdmanager.conf'
    elif 'CentOS Linux' in dist_info:
        source_file = '/opt/alba-asdmanager/config/systemd/alba-asdmanager.service'
        target_file = '/usr/lib/systemd/system/alba-asdmanager.service'
    else:
        raise RuntimeError('Unsupported OS detected')

    if os.path.exists(target_file):
        print ''  # Spacing
        print Interactive.boxed_message(['Existing {0} config file detected: {1}'.format('upstart' if 'Ubuntu' in dist_info else 'systemd', target_file)])
        sys.exit(1)

    ipaddresses = check_output("ip a | grep 'inet ' | sed 's/\s\s*/ /g' | cut -d ' ' -f 3 | cut -d '/' -f 1", shell=True).strip().splitlines()
    ipaddresses = [found_ip.strip() for found_ip in ipaddresses if found_ip.strip() != '127.0.0.1']

    api_ip = Interactive.ask_choice(ipaddresses, 'Select the public IP address to be used for the API')
    api_port = Interactive.ask_integer("Select the port to be used for the API", 1024, 65535, 8500)
    ipaddresses.append('All')
    asd_ips = []
    add_ips = True
    while add_ips:
        current_ips = '  Current IPs: {0}'.format(asd_ips)
        new_asd_ip = Interactive.ask_choice(ipaddresses, 'Select an IP address or all IP addresses to be used for the ASDs{0}'.format(current_ips if len(asd_ips) > 0 else ''))
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
    alba_node_id = EtcdConfiguration.initialize(api_ip, api_port, asd_ips, asd_start_port)

    shutil.copy2(source_file, target_file)

    update_asd_id_cmd = """sed -i "s/<ASD_NODE_ID>/{0}/g" {1}""".format(alba_node_id, target_file)
    check_output(update_asd_id_cmd, shell=True)

    print '- Starting ASD manager service'
    try:
        check_output('start alba-asdmanager', shell=True)
    except Exception as ex:
        print Interactive.boxed_message(['Starting alba-asdmanager failed with error:', str(ex)])
        sys.exit(1)

    print Interactive.boxed_message(['ALBA ASD-manager setup completed'])

if __name__ == '__main__':
    from source.app import app
    context = ('server.crt', 'server.key')
    app.run(host='0.0.0.0',
            port=8500,
            ssl_context=context,
            threaded=True)
