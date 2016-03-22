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
import json
from ConfigParser import RawConfigParser
from source.tools.configuration import EtcdConfiguration
from source.tools.interactive import Interactive
from source.tools.toolbox import Toolbox
from source.tools.services.service import ServiceManager
from source.tools.localclient import LocalClient
from subprocess import check_output


def setup():
    """
    Interactive setup part for initial asd manager configuration with etcd
    """
    print Interactive.boxed_message(['ASD Manager setup'])
    local_client = LocalClient()
    service_name = 'asd-manager'

    print '- Verifying distribution'
    if ServiceManager.has_service(service_name, local_client):
        print ''  # Spacing
        print Interactive.boxed_message(['The ASD Manager is already installed.'])
        sys.exit(1)

    ipaddresses = check_output("ip a | grep 'inet ' | sed 's/\s\s*/ /g' | cut -d ' ' -f 3 | cut -d '/' -f 1", shell=True).strip().splitlines()
    ipaddresses = [found_ip.strip() for found_ip in ipaddresses if found_ip.strip() != '127.0.0.1']
    if not ipaddresses:
        print Interactive.boxed_message(['Could not retrieve IP information on current node'])
        sys.exit(1)

    config = None
    preconfig = '/opt/OpenvStorage/config/openvstorage_preconfig.json'
    run_interactive = True
    if os.path.exists(preconfig):
        config = {}
        with open(preconfig, 'r') as pre_config:
            try:
                config = json.loads(pre_config.read())
            except Exception as ex:
                raise ValueError('JSON contents could not be retrieved from file {0}.\nErrormessage: {1}'.format(preconfig, ex))
        run_interactive = 'asdmanager' not in config

    if run_interactive is False:
        asd_preconfig = config['asdmanager']
        required = {'api_ip': (str, Toolbox.regex_ip),
                    'asd_ips': (list, Toolbox.regex_ip, False),
                    'api_port': (int, {'min': 1025, 'max': 65535}, False),
                    'asd_start_port': (int, {'min': 1025, 'max': 65435}, False)}
        Toolbox.verify_required_params(required_params=required,
                                       actual_params=asd_preconfig)

        api_ip = asd_preconfig['api_ip']
        api_port = asd_preconfig.get('api_port', 8500)
        asd_ips = asd_preconfig.get('asd_ips') or ipaddresses
        asd_start_port = asd_preconfig.get('asd_start_port', 8600)

        if api_ip not in ipaddresses:
            print Interactive.boxed_message(['Unknown API IP provided, please choose from: {0}'.format(', '.join(ipaddresses))])
            sys.exit(1)
        if set(asd_ips).difference(set(ipaddresses)):
            print Interactive.boxed_message(['Unknown ASD IP provided, please choose from: {0}'.format(', '.join(ipaddresses))])
            sys.exit(1)
    else:
        api_ip = Interactive.ask_choice(ipaddresses, 'Select the public IP address to be used for the API')
        api_port = Interactive.ask_integer("Select the port to be used for the API", 1025, 65535, 8500)
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
        asd_start_port = Interactive.ask_integer("Select the port to be used for the ASDs", 1025, 65435, 8600)

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

    ServiceManager.add_service(service_name, local_client, params={'ASD_NODE_ID': alba_node_id,
                                                                   'PORT_NUMBER': str(api_port)})
    print '- Starting ASD manager service'
    try:
        ServiceManager.start_service(service_name, local_client)
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
        raise RuntimeError('Port provided must be within range 1025 - 65535')

    from source.app import app
    app.run(host='0.0.0.0',
            port=int(sys.argv[1]),
            ssl_context=('server.crt', 'server.key'),
            threaded=True)
