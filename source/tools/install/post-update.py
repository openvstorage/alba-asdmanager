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


if __name__ == '__main__':
    import os
    import json
    from source.controllers.asd import ASDController
    from source.controllers.maintenance import MaintenanceController
    from source.tools.configuration.configuration import Configuration
    from source.tools.filemutex import file_mutex
    from source.tools.localclient import LocalClient
    from source.tools.log_handler import LogHandler
    from source.tools.services.service import ServiceManager
    from source.tools.services.systemd import Systemd
    from source.tools.toolbox import Toolbox

    with open(Toolbox.BOOTSTRAP_FILE, 'r') as bootstrap_file:
        NODE_ID = json.load(bootstrap_file)['node_id']
        os.environ['ASD_NODE_ID'] = NODE_ID

    CONFIG_ROOT = '/ovs/alba/asdnodes/{0}/config'.format(NODE_ID)
    CURRENT_VERSION = 2

    _logger = LogHandler.get('asd-manager', name='post-update')

    _logger.info('Executing post-update logic of package openvstorage-sdm')
    with file_mutex('package_update_pu'):
        client = LocalClient('127.0.0.1', username='root')

        key = '{0}/versions'.format(CONFIG_ROOT)
        version = Configuration.get(key) if Configuration.exists(key) else 0

        asd_manager_service_name = 'asd-manager'
        if ServiceManager.has_service(asd_manager_service_name, client) and ServiceManager.get_service_status(asd_manager_service_name, client)[0] is True:
            _logger.info('Stopping asd-manager service')
            ServiceManager.stop_service(asd_manager_service_name, client)

        if version < CURRENT_VERSION:
            try:
                # Adjustment of open file descriptors for ASD/maintenance services to 8192
                service_manager = 'systemd' if ServiceManager.ImplementationClass == Systemd else 'upstart'
                asd_service_names = list(ASDController.list_asd_services())
                maintenance_service_names = list(MaintenanceController.get_services())
                for service_name in asd_service_names + maintenance_service_names:
                    if ServiceManager.has_service(name=service_name, client=client):
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
                            service_params = Configuration.get(configuration_key)
                            ServiceManager.add_service(name='alba-asd' if service_name in asd_service_names else MaintenanceController.MAINTENANCE_PREFIX,
                                                       client=client,
                                                       params=service_params,
                                                       target_name=service_name)

                            # Let the update know that the ASD / maintenance services need to be restarted
                            # Inside `if Configuration.exists`, because useless to rapport restart if we haven't rewritten service file
                            run_file = '/opt/asd-manager/run/{0}.version'.format(service_name)
                            if client.file_exists(filename=run_file):
                                contents = client.file_read(run_file).strip()
                                if '-reboot' not in contents:
                                    if '=' in contents:
                                        contents = ';'.join(['{0}-reboot'.format(part) for part in contents.split(';') if 'alba' in part])
                                    else:
                                        contents = '{0}-reboot'.format(contents)
                                    # Add something to the version, which makes sure it no longer matches the actually installed version
                                    client.file_write(filename=run_file, contents=contents)
                                    client.file_chown(filenames=[run_file], user='alba', group='alba')
                    client.run(['systemctl', 'daemon-reload'])
            except:
                pass
        Configuration.set(key, CURRENT_VERSION)

        if ServiceManager.has_service(asd_manager_service_name, client) and ServiceManager.get_service_status(asd_manager_service_name, client)[0] is False:
            _logger.info('Starting asd-manager service')
            ServiceManager.start_service(asd_manager_service_name, client)

    _logger.info('Post-update logic executed')
