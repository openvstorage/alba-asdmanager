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
This module contains the maintenance controller (maintenance service logic)
"""
import json
from source.tools.configuration import EtcdConfiguration
from source.tools.localclient import LocalClient
from source.tools.services.service import ServiceManager


class MaintenanceController(object):
    MAINTENANCE_PREFIX = 'alba-maintenance'
    _local_client = LocalClient()

    @staticmethod
    def get_services():
        """
        Retrieve all configured maintenance service running on this node for each backend
        :return: generator
        """
        for service_name in ServiceManager.list_services(MaintenanceController._local_client):
            if service_name.startswith(MaintenanceController.MAINTENANCE_PREFIX):
                yield service_name

    @staticmethod
    def add_maintenance_service(name, backend_guid, abm_name):
        """
        Add a maintenance service with a specific name
        :param name: Name of the service to add
        :type name: str
        :param backend_guid: Backend for which the maintenance service needs to run
        :type backend_guid: str
        :param abm_name: Name of the ABM cluster
        :type abm_name: str
        """
        if ServiceManager.has_service(name, MaintenanceController._local_client):
            if not ServiceManager.is_enabled(name, MaintenanceController._local_client):
                ServiceManager.enable_service(name, MaintenanceController._local_client)
        else:
            config_location = '/ovs/alba/backends/{0}/maintenance/config'.format(backend_guid)
            alba_config = 'etcd://127.0.0.1:2379{0}'.format(config_location)
            params = {'ALBA_CONFIG': alba_config}
            EtcdConfiguration.set(config_location, json.dumps({
                'log_level': 'info',
                'albamgr_cfg_url': 'etcd://127.0.0.1:2379/ovs/arakoon/{0}/config'.format(abm_name)
            }, indent=4), raw=True)

            ServiceManager.add_service(name='alba-maintenance', client=MaintenanceController._local_client,
                                       params=params, target_name=name)
        ServiceManager.start_service(name, MaintenanceController._local_client)

    @staticmethod
    def remove_maintenance_service(name):
        """
        Remove a maintenance service with a specific name
        :param name: Name of the service
        """
        if ServiceManager.has_service(name, MaintenanceController._local_client):
            ServiceManager.stop_service(name, MaintenanceController._local_client)
            ServiceManager.remove_service(name, MaintenanceController._local_client)
