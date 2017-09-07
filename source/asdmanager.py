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
from source.dal.lists.settinglist import SettingList
from source.dal.objects.setting import Setting
from source.tools.configuration import Configuration
from source.tools.logger import Logger
from source.tools.osfactory import OSFactory
from source.tools.servicefactory import ServiceFactory

PRECONFIG_FILE = '/opt/asd-manager/config/preconfig.json'
MANAGER_SERVICE = 'asd-manager'
WATCHER_SERVICE = 'asd-watcher'

asd_manager_logger = Logger('asd_manager')


def setup():
    """
    Interactive setup part for initial asd manager configuration
    """
    _print_and_log(message=Interactive.boxed_message(['ASD Manager setup']))

    # Gather information
    ipaddresses = OSFactory.get_manager().get_ip_addresses()
    if not ipaddresses:
        _print_and_log(level='error',
                       message='\n' + Interactive.boxed_message(['Could not retrieve IP information on local node']))
        sys.exit(1)

    local_client = SSHClient(endpoint='127.0.0.1', username='root')
    service_manager = ServiceFactory.get_manager()
    if service_manager.has_service(MANAGER_SERVICE, local_client):
        _print_and_log(level='error',
                       message='\n' + Interactive.boxed_message(['The ASD Manager is already installed.']))
        sys.exit(1)

    config = _validate_and_retrieve_pre_config()
    interactive = len(config) == 0
    if interactive is False:
        api_ip = config['api_ip']
        api_port = config.get('api_port', 8500)
        asd_ips = config.get('asd_ips', [])
        asd_start_port = config.get('asd_start_port', 8600)
        configuration_store = config.get('configuration_store', 'arakoon')
    else:
        api_ip = Interactive.ask_choice(choice_options=ipaddresses,
                                        question='Select the public IP address to be used for the API',
                                        sort_choices=True)
        api_port = Interactive.ask_integer(question="Select the port to be used for the API",
                                           min_value=1025,
                                           max_value=65535,
                                           default_value=8500)
        asd_ips = []
        add_ips = True
        ipaddresses.append('All')
        while add_ips:
            current_ips = ' - Current selected IPs: {0}'.format(asd_ips)
            new_asd_ip = Interactive.ask_choice(choice_options=ipaddresses,
                                                question="Select an IP address to be used for the ASDs or 'All' (All current and future interfaces: 0.0.0.0){0}".format(current_ips if len(asd_ips) > 0 else ''),
                                                default_value='All')
            if new_asd_ip == 'All':
                ipaddresses.remove('All')
                asd_ips = []  # Empty list maps to all IPs - checked when configuring ASDs
                add_ips = False
            else:
                asd_ips.append(new_asd_ip)
                ipaddresses.remove(new_asd_ip)
                add_ips = Interactive.ask_yesno("Do you want to add another IP?")
        asd_start_port = Interactive.ask_integer(question="Select the port to be used for the ASDs",
                                                 min_value=1025,
                                                 max_value=65435,
                                                 default_value=8600)
        configuration_store = 'arakoon'

    if api_ip not in ipaddresses:
        _print_and_log(level='error',
                       message='\n' + Interactive.boxed_message(lines=['Invalid API IP {0} specified. Please choose from:'.format(api_ip)] + ['  * {0}'.format(ip) for ip in ipaddresses]))
        sys.exit(1)
    different_ips = set(asd_ips).difference(set(ipaddresses))
    if different_ips:
        _print_and_log(level='error',
                       message='\n' + Interactive.boxed_message(lines=['Invalid ASD IPs {0} specified. Please choose from:'.format(asd_ips)] + ['  * {0}'.format(ip) for ip in ipaddresses]))
        sys.exit(1)

    if api_port in range(asd_start_port, asd_start_port + 100):
        _print_and_log(level='error',
                       message='\n' + Interactive.boxed_message(['API port cannot be in the range of the ASD port + 100']))
        sys.exit(1)

    # Write necessary files
    if not local_client.file_exists(Configuration.CACC_LOCATION) and local_client.file_exists(Configuration.CACC_SOURCE):  # Try to copy automatically
        try:
            local_client.file_upload(Configuration.CACC_LOCATION, Configuration.CACC_SOURCE)
        except Exception:
            pass
    if interactive is True:
        while not local_client.file_exists(Configuration.CACC_LOCATION):
            _print_and_log(level='warning',
                           message=' - Please place a copy of the Arakoon\'s client configuration file at: {0}'.format(Configuration.CACC_LOCATION))
            Interactive.ask_continue()

    local_client.file_write(filename=Configuration.CONFIG_STORE_LOCATION,
                            contents=json.dumps({'configuration_store': configuration_store},
                                                indent=4))

    # Model settings
    _print_and_log(message=' - Store settings in DB')
    for code, value in {'api_ip': api_ip,
                        'api_port': api_port,
                        'configuration_store': configuration_store,
                        'node_id': Configuration.initialize(config={'api_ip': api_ip,
                                                                    'asd_ips': asd_ips,
                                                                    'api_port': api_port,
                                                                    'asd_start_port': asd_start_port})}.iteritems():
        setting = Setting()
        setting.code = code
        setting.value = value
        setting.save()

    # Deploy/start services
    _print_and_log(message=' - Deploying and starting services')
    service_manager.add_service(name=MANAGER_SERVICE, client=local_client)
    service_manager.add_service(name=WATCHER_SERVICE, client=local_client)
    _print_and_log(message=' - Starting watcher service')
    try:
        service_manager.start_service(name=WATCHER_SERVICE, client=local_client)
    except Exception:
        Configuration.uninitialize()
        _print_and_log(level='exception',
                       message='\n' + Interactive.boxed_message(['Starting watcher failed']))
        sys.exit(1)

    _print_and_log(message='\n' + Interactive.boxed_message(['ASD Manager setup completed']))


def remove(silent=None):
    """
    Interactive removal part for the ASD manager
    :param silent: If silent == '--force-yes' no question will be asked to confirm the removal
    :type silent: str
    :return: None
    :rtype: NoneType
    """
    _print_and_log(message='\n' + Interactive.boxed_message(['ASD Manager removal']))

    local_client = SSHClient(endpoint='127.0.0.1', username='root')
    if not local_client.file_exists(filename='{0}/main.db'.format(Setting.DATABASE_FOLDER)):
        _print_and_log(level='error',
                       message='\n' + Interactive.boxed_message(['The ASD Manager has already been removed']))
        sys.exit(1)

    _print_and_log(message=' - Validating configuration management')
    try:
        Configuration.list(key='ovs')
    except:
        _print_and_log(level='exception',
                       message='\n' + Interactive.boxed_message(['Could not connect to Arakoon']))
        sys.exit(1)

    from source.app.api import API
    _print_and_log(message='  - Retrieving ASD information')
    all_asds = {}
    try:
        all_asds = API.list_asds.original()
    except:
        _print_and_log(level='exception',
                       message='  - Failed to retrieve the ASD information')

    interactive = silent != '--force-yes'
    if interactive is True:
        message = 'Are you sure you want to continue?'
        if len(all_asds) > 0:
            _print_and_log(message='\n\n+++ ALERT +++\n', level='warning')
            message = 'DATA LOSS possible if proceeding! Continue?'

        proceed = Interactive.ask_yesno(message=message, default_value=False)
        if proceed is False:
            _print_and_log(level='error',
                           message='\n' + Interactive.boxed_message(['Abort removal']))
            sys.exit(1)

    _print_and_log(message=' - Removing from configuration management')
    Configuration.uninitialize()

    if len(all_asds) > 0:
        _print_and_log(message=' - Removing disks')
        for device_id, disk_info in API.list_disks.original().iteritems():
            if disk_info['available'] is True:
                continue
            try:
                _print_and_log(message='    - Retrieving ASD information for disk {0}'.format(disk_info['device']))
                for asd_id, asd_info in API.list_asds_disk.original(disk_id=device_id).iteritems():
                    _print_and_log(message='      - Removing ASD {0}'.format(asd_id))
                    API.asd_delete.original(disk_id=device_id, asd_id=asd_id)
                API.delete_disk.original(disk_id=device_id)
            except Exception:
                _print_and_log(level='exception',
                               message='    - Deleting ASDs failed')

    _print_and_log(message=' - Removing services')
    service_manager = ServiceFactory.get_manager()
    for service_name in API.list_maintenance_services.original()['services']:
        _print_and_log(message='    - Removing service {0}'.format(service_name))
        API.remove_maintenance_service.original(name=service_name)
    for service_name in [WATCHER_SERVICE, MANAGER_SERVICE]:
        if service_manager.has_service(name=service_name, client=local_client):
            _print_and_log(message='   - Removing service {0}'.format(service_name))
            service_manager.stop_service(name=service_name, client=local_client)
            service_manager.remove_service(name=service_name, client=local_client)

    local_client.file_delete(filenames=Configuration.CACC_LOCATION)
    local_client.file_delete(filenames='{0}/main.db'.format(Setting.DATABASE_FOLDER))
    _print_and_log(message='\n' + Interactive.boxed_message(['ASD Manager removal completed']))


def _validate_and_retrieve_pre_config():
    """
    Validate whether the values in the pre-configuration file are valid
    :return: JSON contents
    """
    if not os.path.exists(PRECONFIG_FILE):
        return {}

    with open(PRECONFIG_FILE) as pre_config:
        try:
            config = json.loads(pre_config.read())
        except Exception:
            _print_and_log(level='exception',
                           message='\n' + Interactive.boxed_message(['JSON contents could not be retrieved from file {0}'.format(PRECONFIG_FILE)]))
            sys.exit(1)

    if 'asdmanager' not in config or not isinstance(config['asdmanager'], dict):
        _print_and_log(level='error',
                       message='\n' + Interactive.boxed_message(['The ASD manager pre-configuration file must contain a "asdmanager" key with a dictionary as value']))
        sys.exit(1)

    errors = []
    config = config['asdmanager']
    actual_keys = config.keys()
    allowed_keys = ['api_ip', 'api_port', 'asd_ips', 'asd_start_port', 'configuration_store']
    for key in actual_keys:
        if key not in allowed_keys:
            errors.append('Key {0} is not supported by the ASD manager'.format(key))
    if len(errors) > 0:
        _print_and_log(level='error',
                       message='\n' + Interactive.boxed_message(['Errors found while verifying pre-configuration:',
                                                                 ' - {0}'.format('\n - '.join(errors)),
                                                                 '',
                                                                 'Allowed keys:\n'
                                                                 ' - {0}'.format('\n - '.join(allowed_keys))]))
        sys.exit(1)

    try:
        ExtensionsToolbox.verify_required_params(actual_params=config,
                                                 required_params={'api_ip': (str, ExtensionsToolbox.regex_ip, True),
                                                                  'asd_ips': (list, ExtensionsToolbox.regex_ip, False),
                                                                  'api_port': (int, {'min': 1025, 'max': 65535}, False),
                                                                  'asd_start_port': (int, {'min': 1025, 'max': 65435}, False),
                                                                  'configuration_store': (str, ['arakoon'], False)})
    except RuntimeError:
        _print_and_log(message='\n' + Interactive.boxed_message(['The asd-manager pre-configuration file does not contain correct information']),
                       level='exception')
        sys.exit(1)
    return config


def _print_and_log(message, level='info'):
    """
    Print the message and log it using the logger instance
    """
    getattr(asd_manager_logger, level)(message, extra={'print_msg': True})


if __name__ == '__main__':
    def _sync_disks():
        from source.controllers.disk import DiskController
        while True:
            DiskController.sync_disks()
            time.sleep(60)

    try:
        node_id = SettingList.get_setting_by_code(code='node_id').value
    except:
        # For backwards compatibility
        # After update SettingList has not been populated yet and post-update script of package will restart asd-manager
        with open('/opt/asd-manager/config/bootstrap.json') as bstr_file:
            node_id = json.load(bstr_file)['node_id']
    try:
        asd_manager_config = Configuration.get(Configuration.ASD_NODE_CONFIG_MAIN_LOCATION.format(node_id))
    except:
        raise RuntimeError('Configuration management unavailable')

    if 'ip' not in asd_manager_config or 'port' not in asd_manager_config:
        raise RuntimeError('IP and/or port not available in configuration for ALBA node {0}'.format(node_id))

    from source.app import app

    @app.before_first_request
    def setup_logging():
        """
        Configure logging
        :return: None
        """
        for handler in app.logger.handlers:
            app.logger.removeHandler(handler)
        app.logger.addHandler(asd_manager_logger.handlers[0])
        wz_logger = logging.getLogger('werkzeug')
        wz_logger.handlers = []

    thread = Thread(target=_sync_disks, name='sync_disks')
    thread.start()

    app.debug = False
    app.run(host=asd_manager_config['ip'],
            port=asd_manager_config['port'],
            ssl_context=('../config/server.crt', '../config/server.key'),
            threaded=True)
