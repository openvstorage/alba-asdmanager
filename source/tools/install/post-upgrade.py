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
sys.path.append('/opt/asd-manager')


if __name__ == '__main__':
    import os
    import json
    import glob
    from source.tools.filemutex import file_mutex
    from source.tools.localclient import LocalClient
    from source.tools.log_handler import LogHandler
    from source.tools.services.service import ServiceManager
    from source.tools.configuration.configuration import Configuration

    NODE_ID = os.environ['ASD_NODE_ID']
    CONFIG_ROOT = '/ovs/alba/asdnodes/{0}/config'.format(NODE_ID)
    CURRENT_VERSION = 0

    _logger = LogHandler.get('asd-manager', name='post-upgrade')

    _logger.info('Executing post-upgrade logic of package openvstorage-sdm')
    with file_mutex('package_update_pu'):
        client = LocalClient('127.0.0.1', username='root')

        key = '{0}/versions'.format(CONFIG_ROOT)
        version = Configuration.get(key) if Configuration.exists(key) else 0

        if version < CURRENT_VERSION:
            service_name = 'asd-manager'
            if ServiceManager.has_service(service_name, client) and ServiceManager.get_service_status(service_name, client) is True:
                _logger.info('Stopping asd-manager service')
                ServiceManager.stop_service(service_name, client)

            # Migration

            if ServiceManager.has_service(service_name, client) and ServiceManager.get_service_status(service_name, client) is False:
                _logger.info('Starting asd-manager service')
                ServiceManager.start_service(service_name, client)

        Configuration.set(key, CURRENT_VERSION)

    _logger.info('Post-upgrade logic executed')
