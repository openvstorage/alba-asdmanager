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
Post update script for package openvstorage-sdm
"""

import sys
sys.path.append('/opt/asd-manager')

BOOTSTRAP_FILE = '/opt/asd-manager/config/bootstrap.json'


if __name__ == '__main__':
    import os
    import json
    from ovs_extensions.services.interfaces.systemd import Systemd
    from ovs_extensions.generic.filemutex import file_mutex
    from ovs_extensions.generic.sshclient import SSHClient
    from ovs_extensions.generic.toolbox import ExtensionsToolbox
    from source.controllers.maintenance import MaintenanceController
    from source.dal.lists.asdlist import ASDList
    from source.tools.configuration import Configuration
    from source.tools.log_handler import LogHandler
    from source.tools.osfactory import OSFactory
    from source.tools.servicefactory import ServiceFactory

    with open(BOOTSTRAP_FILE, 'r') as bootstrap_file:
        NODE_ID = json.load(bootstrap_file)['node_id']
        os.environ['ASD_NODE_ID'] = NODE_ID

    CONFIG_ROOT = '/ovs/alba/asdnodes/{0}/config'.format(NODE_ID)
    CURRENT_VERSION = 6

    _logger = LogHandler.get('asd-manager', name='post-update')
    _service_manager = ServiceFactory.get_manager()

    _logger.info('Executing post-update logic of package openvstorage-sdm')
    with file_mutex('package_update_pu'):
        from source.controllers.asd import ASDController

        local_client = SSHClient(endpoint='127.0.0.1', username='root')

        key = '{0}/versions'.format(CONFIG_ROOT)
        version = Configuration.get(key) if Configuration.exists(key) else 0

        asd_manager_service_name = 'asd-manager'
        if _service_manager.has_service(asd_manager_service_name, local_client) and _service_manager.get_service_status(asd_manager_service_name, local_client) == 'active':
            _logger.info('Stopping asd-manager service')
            _service_manager.stop_service(asd_manager_service_name, local_client)

        if version < CURRENT_VERSION:
            try:
                # DB migrations
                from source.dal.asdbase import ASDBase
                from source.controllers.disk import DiskController
                if not local_client.file_exists('{0}/main.db'.format(ASDBase.DATABASE_FOLDER)):
                    from source.dal.objects.asd import ASD
                    from source.dal.lists.disklist import DiskList
                    local_client.dir_create([ASDBase.DATABASE_FOLDER])
                    DiskController.sync_disks()
                    for disk in DiskList.get_usable_disks():
                        if disk.state == 'MISSING' or disk.mountpoint is None:
                            continue
                        for directory in local_client.dir_list(disk.mountpoint):
                            asd = ASD()
                            asd.asd_id = directory
                            asd.folder = directory
                            asd.disk = disk
                            if asd.has_config:
                                asd.save()

                # New properties on ASD (ips and port)
                for asd in ASDList.get_asds():
                    if (asd.port is None or asd.ips is None) and asd.has_config:
                        config = Configuration.get(key=asd.config_key)
                        asd.ips = config.get('ips', [])
                        asd.port = config['port']
                        asd.save()

                # Adjustment of open file descriptors for ASD/maintenance services to 8192
                service_manager = 'systemd' if _service_manager.ImplementationClass == Systemd else 'upstart'
                asd_service_names = list(ASDController.list_asd_services())
                maintenance_service_names = list(MaintenanceController.get_services())
                for service_name in asd_service_names + maintenance_service_names:
                    if _service_manager.has_service(name=service_name, client=local_client):
                        if service_manager == 'systemd':
                            path = '/lib/systemd/system/{0}.service'.format(service_name)
                            check = 'LimitNOFILE=8192'
                        else:
                            path = '/etc/init/{0}.conf'.format(service_name)
                            check = 'limit nofile 8192 8192'

                        restart_required = False
                        if os.path.exists(path):
                            with open(path, 'r') as system_file:
                                if check not in system_file.read():
                                    restart_required = True

                        if restart_required is False:
                            continue

                        configuration_key = '/ovs/alba/asdnodes/{0}/services/{1}'.format(NODE_ID, service_name)
                        if Configuration.exists(configuration_key):
                            # Rewrite the service file
                            _service_manager.add_service(name='alba-asd' if service_name in asd_service_names else MaintenanceController.MAINTENANCE_PREFIX,
                                                         client=local_client,
                                                         params=Configuration.get(configuration_key),
                                                         target_name=service_name)

                            # Let the update know that the ASD / maintenance services need to be restarted
                            # Inside `if Configuration.exists`, because useless to rapport restart if we haven't rewritten service file
                            ExtensionsToolbox.edit_version_file(client=local_client, package_name='alba', old_service_name=service_name)
                    if service_manager == 'systemd':
                        local_client.run(['systemctl', 'daemon-reload'])

                # Version 3: Addition of 'ExecReload' for ASD/maintenance SystemD services
                getattr(_service_manager, 'has_service')  # Invoke ServiceManager to fill out the ImplementationClass (default None)
                if _service_manager.ImplementationClass == Systemd:  # Upstart does not have functionality to reload a process' configuration
                    reload_daemon = False
                    asd_service_names = list(ASDController.list_asd_services())
                    maintenance_service_names = list(MaintenanceController.get_services())
                    for service_name in asd_service_names + maintenance_service_names:
                        if not _service_manager.has_service(name=service_name, client=local_client):
                            continue

                        path = '/lib/systemd/system/{0}.service'.format(service_name)
                        if os.path.exists(path):
                            with open(path, 'r') as system_file:
                                if 'ExecReload' not in system_file.read():
                                    reload_daemon = True
                                    configuration_key = '/ovs/alba/asdnodes/{0}/services/{1}'.format(NODE_ID, service_name)
                                    if Configuration.exists(configuration_key):
                                        # No need to edit the service version file, since this change only requires a daemon-reload
                                        _service_manager.add_service(name='alba-asd' if service_name in asd_service_names else MaintenanceController.MAINTENANCE_PREFIX,
                                                                     client=local_client,
                                                                     params=Configuration.get(configuration_key),
                                                                     target_name=service_name)
                    if reload_daemon is True:
                        local_client.run(['systemctl', 'daemon-reload'])

                # Introduction of Active Drive
                asd_node_ips_map = {}
                for asd_node_id in Configuration.list('/ovs/alba/asdnodes'):
                    network_config = Configuration.get('/ovs/alba/asdnodes/{0}/config/network'.format(asd_node_id))
                    asd_node_ips_map[asd_node_id] = network_config['ips']

                all_local_ips = OSFactory.get_manager().get_ip_addresses(client=local_client)
                for asd in ASDList.get_asds():
                    if asd.has_config:
                        asd_config = Configuration.get(asd.config_key)
                        if 'multicast' not in asd_config:
                            asd_config['multicast'] = None
                        if 'ips' in asd_config:
                            asd_ips = asd_config['ips'] or all_local_ips
                        else:
                            asd_ips = all_local_ips
                        asd.ips = asd_ips
                        asd_config['ips'] = asd_ips
                        Configuration.set(asd.config_key, asd_config)
                        asd.save()
            except:
                _logger.exception('Error while executing post-update code on node {0}'.format(NODE_ID))
        Configuration.set(key, CURRENT_VERSION)

        if _service_manager.has_service(asd_manager_service_name, local_client) and _service_manager.get_service_status(asd_manager_service_name, local_client) != 'active':
            _logger.info('Starting asd-manager service')
            _service_manager.start_service(asd_manager_service_name, local_client)

    _logger.info('Post-update logic executed')
