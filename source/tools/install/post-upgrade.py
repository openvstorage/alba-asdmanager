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
Post upgrade script for package openvstorage-sdm
"""

import sys
from datetime import datetime

for entry in sys.path:
    if entry.startswith('/opt/alba-asdmanager'):
        sys.path.remove(entry)
sys.path.append('/opt/asd-manager')


def _log(message):
    print '{0} - {1}'.format(str(datetime.now()), message)

if __name__ == '__main__':
    import os
    import json
    import glob
    from source.tools.filemutex import file_mutex
    from source.tools.localclient import LocalClient
    from source.tools.services.service import ServiceManager
    from source.tools.configuration import EtcdConfiguration

    _log('Executing post-upgrade logic of package openvstorage-sdm')
    with file_mutex('package_update'):
        client = LocalClient('127.0.0.1', username='root')

        migrate = False
        service_name = 'alba-asdmanager'
        if ServiceManager.has_service(service_name, client):
            _log('Removing old alba-asdmanager service')
            ServiceManager.stop_service(service_name, client)
            ServiceManager.remove_service(service_name, client)

        service_name = 'asd-manager'
        if ServiceManager.has_service(service_name, client) and ServiceManager.get_service_status(service_name, client) is True:
            _log('Stopping asd-manager service')
            ServiceManager.stop_service(service_name, client)

        # Migrate main configuration file
        path = '/opt/alba-asdmanager/config/config.json'
        if client.file_exists(path):
            _log('Migrating old configuration file to Etcd')
            with open(path) as config_file:
                config = json.load(config_file)
            node_id = config['main']['node_id']
            # Migrate configuration file
            EtcdConfiguration.set('/ovs/alba/asdnodes/{0}/config/main'.format(node_id), config['main'])
            EtcdConfiguration.set('/ovs/alba/asdnodes/{0}/config/main|port'.format(node_id), 8500)
            EtcdConfiguration.set('/ovs/alba/asdnodes/{0}/config/network'.format(node_id), config['network'])
            ServiceManager.add_service(service_name, client, params={'ASD_NODE_ID': node_id,
                                                                     'PORT_NUMBER': str(8500)})
            client.file_delete(path)

        # Migrate ASDs
        for filename in glob.glob('/mnt/alba-asd/*/asd.json'):
            _log('Migrating old asd configuratoin files to Etcd')
            with open(filename) as config_file:
                config = json.load(config_file)
            EtcdConfiguration.set('/ovs/alba/asds/{0}/config'.format(config['asd_id']), json.dumps(config, indent=4), raw=True)
            ServiceManager.add_service('alba-asd', client, params={'ASD': config['asd_id']}, target_name='alba-asd-{0}'.format(config['asd_id']))
            os.remove(filename)

        # Cleanup old data
        if client.dir_exists('/opt/alba-asdmanager'):
            _log('Removing old alba-asdmanager data')
            client.dir_delete('/opt/alba-asdmanager')

        if ServiceManager.has_service(service_name, client) and ServiceManager.get_service_status(service_name, client) is False:
            _log('Starting asd-manager service')
            ServiceManager.start_service(service_name, client)

    _log('Post-upgrade logic executed')
