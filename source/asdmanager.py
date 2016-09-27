#!/usr/bin/python2

# Copyright (C) 2016 iNuron NV
#
# This file is part of Open vStorage Open Source Edition (OSE),
# as available from
#
#      http://www.openvstorage.org and
#      http://www.openvstorage.com.
#
# This file is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License v3 (GNU AGPLv3)
# as published by the Free Software Foundation, in version 3 as it comes
# in the LICENSE.txt file of the Open vStorage OSE distribution.
#
# Open vStorage is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY of any kind.

"""
Module for ASD Manager SetupController
"""
import os
import sys
import json
import logging
from source.tools.configuration.configuration import Configuration
from source.tools.interactive import Interactive
from source.tools.toolbox import Toolbox
from source.tools.services.service import ServiceManager
from source.tools.localclient import LocalClient
from source.tools.log_handler import LogHandler
from subprocess import check_output

BOOTSTRAP_FILE = '/opt/asd-manager/config/bootstrap.json'


def setup():
    """
    Interactive setup part for initial asd manager configuration with etcd
    """
    print Interactive.boxed_message(['ASD Manager setup'])
    local_client = LocalClient()
    service_name = 'asd-manager'
    watcher_name = 'asd-watcher'

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
                config = json.load(pre_config)
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
        asd_ips = asd_preconfig.get('asd_ips', [])
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

    if run_interactive is False:
        store = config['asdmanager'].get('store')
        if store is not None:
            store = store.lower()
        if store != 'arakoon' and store != 'etcd':
            raise RuntimeError('Invalid store in unattended config. Should be "arakoon" or "etcd"')
    else:
        store = Interactive.ask_choice(['Arakoon', 'Etcd'],
                                       question='Select the configuration management system',
                                       default_value='Arakoon').lower()
    if store == 'arakoon':
        from source.tools.configuration.arakoon_config import ArakoonConfiguration
        file_location = ArakoonConfiguration.CACC_LOCATION
        source_location = ArakoonConfiguration.CACC_SOURCE
        if not local_client.file_exists(file_location) and local_client.file_exists(source_location):
            # Try to copy automatically
            try:
                local_client.run('cp {0} {1}'.format(source_location, file_location))
            except Exception:
                pass
        while not local_client.file_exists(file_location):
            print 'Please place a copy of the Arakoon\'s client configuration file at: {0}'.format(file_location)
            Interactive.ask_continue()
    bootstrap_location = Configuration.BOOTSTRAP_CONFIG_LOCATION
    if not local_client.file_exists(bootstrap_location):
        local_client.file_create(bootstrap_location)
    local_client.file_write(bootstrap_location, json.dumps({'configuration_store': store}, indent=4))
    try:
        alba_node_id = Configuration.initialize(api_ip, api_port, asd_ips, asd_start_port)
    except:
        print ''
        if store == 'arakoon':
            print Interactive.boxed_message(['Could not connect to Arakoon'])
        else:
            print Interactive.boxed_message(['Could not connect to Etcd.',
                                             'Please make sure an Etcd proxy is available, pointing towards an OpenvStorage cluster.'])
        sys.exit(1)

    with open(BOOTSTRAP_FILE, 'w') as bs_file:
        json.dump({'node_id': alba_node_id}, bs_file)

    ServiceManager.add_service(service_name, local_client, params={'PORT_NUMBER': str(api_port)})
    ServiceManager.add_service(watcher_name, local_client)
    print '- Starting watcher service'
    try:
        ServiceManager.start_service(watcher_name, local_client)
    except Exception as ex:
        Configuration.uninitialize(alba_node_id)
        print Interactive.boxed_message(['Starting watcher failed with error:', str(ex)])
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

    with open(BOOTSTRAP_FILE, 'r') as bootstrap_file:
        node_id = json.load(bootstrap_file)['node_id']
    os.environ['ASD_NODE_ID'] = node_id

    from source.app import app

    @app.before_first_request
    def setup_logging():
        """
        Configure logging
        :return: None
        """
        if app.debug is False:
            _logger = LogHandler.get('asd-manager', name='flask')
            app.logger.handlers = []
            app.logger.addHandler(_logger.handler)
            app.logger.propagate = False
            wz_logger = logging.getLogger('werkzeug')
            wz_logger.handlers = []
            wz_logger.addHandler(_logger.handler)
            wz_logger.propagate = False

    app.debug = False
    app.run(host='0.0.0.0',
            port=int(sys.argv[1]),
            ssl_context=('server.crt', 'server.key'),
            threaded=True)
