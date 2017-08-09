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
import time
import logging
from threading import Thread
from ovs_extensions.generic.interactive import Interactive
from ovs_extensions.generic.sshclient import SSHClient
from ovs_extensions.generic.toolbox import ExtensionsToolbox
from source.tools.configuration import Configuration
from source.tools.log_handler import LogHandler
from source.tools.osfactory import OSFactory
from source.tools.servicefactory import ServiceFactory
from source.tools.system import BOOTSTRAP_FILE

PRECONFIG_FILE = '/opt/asd-manager/config/preconfig.json'
MANAGER_SERVICE = 'asd-manager'
WATCHER_SERVICE = 'asd-watcher'


def setup():
    """
    Interactive setup part for initial asd manager configuration
    """

    print Interactive.boxed_message(['ASD Manager setup'])
    print '- Verifying distribution'
    service_manager = ServiceFactory.get_manager()
    local_client = SSHClient(endpoint='127.0.0.1', username='root')
    if service_manager.has_service(MANAGER_SERVICE, local_client):
        print ''  # Spacing
        print Interactive.boxed_message(['The ASD Manager is already installed.'])
        sys.exit(1)

    ipaddresses = OSFactory.get_manager().get_ip_addresses()
    if not ipaddresses:
        print Interactive.boxed_message(['Could not retrieve IP information on local node'])
        sys.exit(1)

    config = _validate_and_retrieve_pre_config()
    if config is None:
        api_ip = Interactive.ask_choice(ipaddresses, 'Select the public IP address to be used for the API')
        asd_ips = []
        add_ips = True
        api_port = Interactive.ask_integer("Select the port to be used for the API", 1025, 65535, 8500)
        ipaddresses.append('All')
        while add_ips:
            current_ips = ' - Current selected IPs: {0}'.format(asd_ips)
            new_asd_ip = Interactive.ask_choice(ipaddresses,
                                                "Select an IP address to be used for the ASDs or 'All' (All current and future interfaces: 0.0.0.0){0}".format(current_ips if len(asd_ips) > 0 else ''),
                                                default_value='All')
            if new_asd_ip == 'All':
                ipaddresses.remove('All')
                asd_ips = []  # Empty maps to all ips - checked when configuring asds
                add_ips = False
            else:
                asd_ips.append(new_asd_ip)
                ipaddresses.remove(new_asd_ip)
                add_ips = Interactive.ask_yesno("Do you want to add another IP?")
        asd_start_port = Interactive.ask_integer("Select the port to be used for the ASDs", 1025, 65435, 8600)
    else:
        api_ip = config['api_ip']
        api_port = config.get('api_port', 8500)
        asd_ips = config.get('asd_ips', [])
        asd_start_port = config.get('asd_start_port', 8600)

        if api_ip not in ipaddresses:
            print Interactive.boxed_message(['Unknown API IP provided, please choose from: {0}'.format(', '.join(ipaddresses))])
            sys.exit(1)
        if set(asd_ips).difference(set(ipaddresses)):
            print Interactive.boxed_message(['Unknown ASD IP provided, please choose from: {0}'.format(', '.join(ipaddresses))])
            sys.exit(1)

    if api_port in range(asd_start_port, asd_start_port + 100):
        print Interactive.boxed_message(['API port cannot be in the range of the ASD port + 100'])
        sys.exit(1)

    # Make sure to always have the information stored
    config = {'api_ip': api_ip,
              'asd_ips': asd_ips,
              'api_port': api_port,
              'asd_start_port': asd_start_port}
    with open(PRECONFIG_FILE, 'w') as preconfig:
        preconfig.write(json.dumps({'asdmanager': config}, indent=4))

    file_location = Configuration.CACC_LOCATION
    source_location = Configuration.CACC_SOURCE
    if not local_client.file_exists(file_location) and local_client.file_exists(source_location):
        # Try to copy automatically
        try:
            local_client.file_upload(file_location, source_location)
        except Exception:
            pass
    while not local_client.file_exists(file_location):
        print 'Please place a copy of the Arakoon\'s client configuration file at: {0}'.format(file_location)
        Interactive.ask_continue()
    bootstrap_location = Configuration.BOOTSTRAP_CONFIG_LOCATION
    if not local_client.file_exists(bootstrap_location):
        local_client.file_create(bootstrap_location)
    local_client.file_write(bootstrap_location, json.dumps({'configuration_store': 'arakoon'}, indent=4))

    try:
        alba_node_id = Configuration.initialize(config=config)
    except:
        print ''
        print Interactive.boxed_message(['Could not connect to Arakoon'])
        sys.exit(1)

    with open(BOOTSTRAP_FILE, 'w') as bs_file:
        json.dump({'node_id': alba_node_id}, bs_file)

    try:
        service_manager.add_service(MANAGER_SERVICE, local_client)
        service_manager.add_service(WATCHER_SERVICE, local_client)
    except Exception as ex:
        Configuration.uninitialize(alba_node_id)
        print Interactive.boxed_message(['Adding services failed with error:', str(ex)])
        sys.exit(1)

    print '- Starting watcher service'
    try:
        service_manager.start_service(WATCHER_SERVICE, local_client)
    except Exception as ex:
        Configuration.uninitialize(alba_node_id)
        print Interactive.boxed_message(['Starting watcher failed with error:', str(ex)])
        sys.exit(1)

    print Interactive.boxed_message(['ASD Manager setup completed'])


def remove(silent=None):
    """
    Interactive removal part for the ASD manager
    :param silent: If silent == '--force-yes' no question will be asked to confirm the removal
    :type silent: str
    :return: None
    """
    os.environ['OVS_LOGTYPE_OVERRIDE'] = LogHandler.TARGET_TYPE_FILE
    print '\n' + Interactive.boxed_message(['ASD Manager removal'])

    ##############
    # VALIDATION #
    ##############
    local_client = SSHClient(endpoint='127.0.0.1', username='root')
    service_manager = ServiceFactory.get_manager()
    if not local_client.file_exists(filename=BOOTSTRAP_FILE):
        print '\n' + Interactive.boxed_message(['The ASD Manager has already been removed'])
        sys.exit(1)

    print '  - Validating configuration file'
    config = _validate_and_retrieve_pre_config()
    if config is None:
        print '\n' + Interactive.boxed_message(['Cannot remove the ASD manager because not all information could be retrieved from the pre-configuration file'])
        sys.exit(1)

    print '  - Validating node ID'
    with open(BOOTSTRAP_FILE) as bs_file:
        try:
            alba_node_id = json.loads(bs_file.read())['node_id']
        except:
            print '\n' + Interactive.boxed_message(['JSON contents could not be retrieved from file {0}'.format(BOOTSTRAP_FILE)])
            sys.exit(1)

    print '  - Validating configuration management'
    try:
        Configuration.list(key='ovs')
    except:
        print '\n' + Interactive.boxed_message(['Could not connect to Arakoon'])
        sys.exit(1)

    ################
    # CONFIRMATION #
    ################
    os.environ['ASD_NODE_ID'] = alba_node_id
    from source.app.api import API
    print '  - Retrieving ASD information'
    all_asds = {}
    try:
        all_asds = API.list_asds.original()
    except:
        print '  - ERROR: Failed to retrieve the ASD information'

    interactive = silent != '--force-yes'
    if interactive is True:
        message = 'Are you sure you want to continue?'
        if len(all_asds) > 0:
            print '\n\n+++ ALERT +++\n'
            message = 'DATA LOSS possible if proceeding! Continue?'

        proceed = Interactive.ask_yesno(message=message, default_value=False)
        if proceed is False:
            print '\n' + Interactive.boxed_message(['Abort removal'])
            sys.exit(1)

    ###########
    # REMOVAL #
    ###########
    print '  - Removing from configuration management'
    Configuration.uninitialize(node_id=alba_node_id)

    if len(all_asds) > 0:
        print '  - Removing disks'
        for device_id, disk_info in API.list_disks.original().iteritems():
            if disk_info['available'] is True:
                continue
            try:
                print '    - Retrieving ASD information for disk {0}'.format(disk_info['device'])
                for asd_id, asd_info in API.list_asds_disk.original(disk_id=device_id).iteritems():
                    print '      - Removing ASD {0}'.format(asd_id)
                    API.asd_delete.original(disk_id=device_id, asd_id=asd_id)
                API.delete_disk.original(disk_id=device_id)
            except Exception as ex:
                print '    - Deleting ASDs failed: {0}'.format(ex)

    print '  - Removing services'
    for service_name in API.list_maintenance_services.original()['services']:
        print '    - Removing service {0}'.format(service_name)
        API.remove_maintenance_service.original(name=service_name)
    for service_name in [WATCHER_SERVICE, MANAGER_SERVICE]:
        if service_manager.has_service(name=service_name, client=local_client):
            print '    - Removing service {0}'.format(service_name)
            service_manager.stop_service(name=service_name, client=local_client)
            service_manager.remove_service(name=service_name, client=local_client)

    local_client.file_delete(filenames=Configuration.CACC_LOCATION)
    local_client.file_delete(filenames=BOOTSTRAP_FILE)
    print '\n' + Interactive.boxed_message(['ASD Manager removal completed'])


def _validate_and_retrieve_pre_config():
    """
    Validate whether the values in the pre-configuration file are valid
    :return: JSON contents
    """
    if not os.path.exists(PRECONFIG_FILE):
        return

    with open(PRECONFIG_FILE) as pre_config:
        try:
            config = json.loads(pre_config.read())
        except Exception as ex:
            print Interactive.boxed_message(['JSON contents could not be retrieved from file {0}.\nError message: {1}'.format(PRECONFIG_FILE, ex)])
            sys.exit(1)

    if 'asdmanager' not in config or not isinstance(config['asdmanager'], dict):
        print Interactive.boxed_message(['The ASD manager pre-configuration file must contain a "asdmanager" key with a dictionary as value'])
        sys.exit(1)

    errors = []
    config = config['asdmanager']
    actual_keys = config.keys()
    expected_keys = ['api_ip', 'api_port', 'asd_ips', 'asd_start_port']
    for key in actual_keys:
        if key not in expected_keys:
            errors.append('Key {0} is not supported by the ASD manager'.format(key))
    if len(errors) > 0:
        print Interactive.boxed_message(['Errors found while verifying pre-configuration:',
                                         ' - {0}'.format('\n - '.join(errors)),
                                         '',
                                         'Allowed keys:\n'
                                         ' - {0}'.format('\n - '.join(expected_keys))])
        sys.exit(1)

    try:
        ExtensionsToolbox.verify_required_params(actual_params=config,
                                                 required_params={'api_ip': (str, ExtensionsToolbox.regex_ip, True),
                                                                  'asd_ips': (list, ExtensionsToolbox.regex_ip, False),
                                                                  'api_port': (int, {'min': 1025, 'max': 65535}, False),
                                                                  'asd_start_port': (int, {'min': 1025, 'max': 65435}, False)})
    except RuntimeError as rte:
        print Interactive.boxed_message(['The asd-manager pre-configuration file does not contain correct information\n{0}'.format(rte)])
        sys.exit(1)
    return config


if __name__ == '__main__':
    def _sync_disks():
        from source.controllers.disk import DiskController
        while True:
            DiskController.sync_disks()
            time.sleep(60)

    with open(BOOTSTRAP_FILE) as bootstrap_file:
        node_id = json.load(bootstrap_file)['node_id']
    os.environ['ASD_NODE_ID'] = node_id

    try:
        asd_manager_config = Configuration.get('/ovs/alba/asdnodes/{0}/config/main'.format(node_id))
    except:
        raise RuntimeError('Configuration management unavailable')

    if 'ip' not in asd_manager_config or 'port' not in asd_manager_config:
        raise RuntimeError('IP and/or port not available in configuration for ALBA node {0}'.format(node_id))

    LogHandler.get('extensions', name='ovs_extensions')  # Initiate extensions logger

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
            wz_logger.propagate = False
            LogHandler.get('extensions', name='ovs_extensions')  # Initiate extensions logger

    thread = Thread(target=_sync_disks, name='sync_disks')
    thread.start()

    app.debug = False
    app.run(host=asd_manager_config['ip'],
            port=asd_manager_config['port'],
            ssl_context=('server.crt', 'server.key'),
            threaded=True)
