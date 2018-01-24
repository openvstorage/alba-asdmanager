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

import os
import sys
sys.path.append('/opt/asd-manager')

os.environ['OVS_LOGTYPE_OVERRIDE'] = 'file'  # Make sure we log to file during update


if __name__ == '__main__':
    import json
    from ovs_extensions.generic.filemutex import file_mutex
    from ovs_extensions.generic.sshclient import SSHClient
    from ovs_extensions.generic.toolbox import ExtensionsToolbox
    from ovs_extensions.services.interfaces.systemd import Systemd
    from source.asdmanager import BOOTSTRAP_FILE
    from source.controllers.maintenance import MaintenanceController
    from source.tools.configuration import Configuration
    from source.tools.logger import Logger
    from source.tools.osfactory import OSFactory
    from source.tools.servicefactory import ServiceFactory

    CURRENT_VERSION = 7

    _logger = Logger('update')
    service_manager = ServiceFactory.get_manager()

    _logger.info('Executing post-update logic of package openvstorage-sdm')
    with file_mutex('package_update_pu'):
        local_client = SSHClient(endpoint='127.0.0.1', username='root')

        # Override the created openvstorage_sdm_id during package install, with currently available SDM ID
        if local_client.file_exists(BOOTSTRAP_FILE):
            with open(BOOTSTRAP_FILE) as bstr_file:
                node_id = json.load(bstr_file)['node_id']
            local_client.file_write(filename='/etc/openvstorage_sdm_id',
                                    contents=node_id + '\n')
        else:
            with open('/etc/openvstorage_sdm_id', 'r') as id_file:
                node_id = id_file.read().strip()

        key = '{0}/versions'.format(Configuration.ASD_NODE_CONFIG_LOCATION.format(node_id))
        version = Configuration.get(key) if Configuration.exists(key) else 0

        asd_manager_service_name = 'asd-manager'
        if service_manager.has_service(asd_manager_service_name, local_client) and service_manager.get_service_status(asd_manager_service_name, local_client) == 'active':
            _logger.info('Stopping asd-manager service')
            service_manager.stop_service(asd_manager_service_name, local_client)

        # @TODO: Move these migrations to alba_node.client.update_execute_migration_code()
        if version < CURRENT_VERSION:
            try:
                # DB migrations
                from source.controllers.asd import ASDController
                from source.controllers.disk import DiskController
                from source.dal.asdbase import ASDBase
                from source.dal.lists.asdlist import ASDList
                from source.dal.lists.disklist import DiskList
                from source.dal.objects.asd import ASD

                if not local_client.file_exists('{0}/main.db'.format(ASDBase.DATABASE_FOLDER)):
                    local_client.dir_create([ASDBase.DATABASE_FOLDER])

                asd_map = dict((asd.asd_id, asd) for asd in ASDList.get_asds())
                DiskController.sync_disks()
                for disk in DiskList.get_usable_disks():
                    if disk.state == 'MISSING' or disk.mountpoint is None:
                        continue
                    for asd_id in local_client.dir_list(disk.mountpoint):
                        if asd_id in asd_map:
                            asd = asd_map[asd_id]
                        else:
                            asd = ASD()

                        asd.disk = disk
                        asd.asd_id = asd_id
                        asd.folder = asd_id
                        if asd.has_config:
                            if asd.port is None or asd.hosts is None:
                                config = Configuration.get(key=asd.config_key)
                                asd.port = config['port']
                                asd.hosts = config.get('ips', [])
                            asd.save()

                # Adjustment of open file descriptors for ASD/maintenance services to 8192
                asd_service_names = list(ASDController.list_asd_services())
                maintenance_service_names = list(MaintenanceController.get_services())
                for service_name in asd_service_names + maintenance_service_names:
                    if service_manager.has_service(name=service_name, client=local_client):
                        if service_manager.__class__ == Systemd:
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

                        configuration_key = ServiceFactory.SERVICE_CONFIG_KEY.format(node_id, service_name)
                        if Configuration.exists(configuration_key):
                            # Rewrite the service file
                            service_manager.add_service(name=ASDController.ASD_PREFIX if service_name in asd_service_names else MaintenanceController.MAINTENANCE_PREFIX,
                                                        client=local_client,
                                                        params=Configuration.get(configuration_key),
                                                        target_name=service_name)

                            # Let the update know that the ASD / maintenance services need to be restarted
                            # Inside `if Configuration.exists`, because useless to rapport restart if we haven't rewritten service file
                            ExtensionsToolbox.edit_version_file(client=local_client,
                                                                package_name='alba',
                                                                old_run_file='{0}/{1}.version'.format(ServiceFactory.RUN_FILE_DIR, service_name))
                    if service_manager.__class__ == Systemd:
                        local_client.run(['systemctl', 'daemon-reload'])

                # Version 3: Addition of 'ExecReload' for ASD/maintenance SystemD services
                if service_manager.__class__ == Systemd:  # Upstart does not have functionality to reload a process' configuration
                    reload_daemon = False
                    asd_service_names = list(ASDController.list_asd_services())
                    maintenance_service_names = list(MaintenanceController.get_services())
                    for service_name in asd_service_names + maintenance_service_names:
                        if not service_manager.has_service(name=service_name, client=local_client):
                            continue

                        path = '/lib/systemd/system/{0}.service'.format(service_name)
                        if os.path.exists(path):
                            with open(path, 'r') as system_file:
                                if 'ExecReload' not in system_file.read():
                                    reload_daemon = True
                                    configuration_key = ServiceFactory.SERVICE_CONFIG_KEY.format(node_id, service_name)
                                    if Configuration.exists(configuration_key):
                                        # No need to edit the service version file, since this change only requires a daemon-reload
                                        service_manager.add_service(name=ASDController.ASD_PREFIX if service_name in asd_service_names else MaintenanceController.MAINTENANCE_PREFIX,
                                                                    client=local_client,
                                                                    params=Configuration.get(configuration_key),
                                                                    target_name=service_name)
                    if reload_daemon is True:
                        local_client.run(['systemctl', 'daemon-reload'])

                # Version 6: Introduction of Active Drive
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
                        asd.hosts = asd_ips
                        asd_config['ips'] = asd_ips
                        Configuration.set(asd.config_key, asd_config)
                        asd.save()

                # Version 7: Moving flask certificate files to config dir
                for file_name in ['passphrase', 'server.crt', 'server.csr', 'server.key']:
                    if local_client.file_exists('/opt/asd-manager/source/{0}'.format(file_name)):
                        local_client.file_move(source_file_name='/opt/asd-manager/source/{0}'.format(file_name),
                                               destination_file_name='/opt/asd-manager/config/{0}'.format(file_name))
            except:
                _logger.exception('Error while executing post-update code on node {0}'.format(node_id))
        Configuration.set(key, CURRENT_VERSION)

        if service_manager.has_service(asd_manager_service_name, local_client) and service_manager.get_service_status(asd_manager_service_name, local_client) != 'active':
            _logger.info('Starting asd-manager service')
            service_manager.start_service(asd_manager_service_name, local_client)

    _logger.info('Post-update logic executed')
