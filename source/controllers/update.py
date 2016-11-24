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
This module contains logic related to updates
"""
import os
from subprocess import CalledProcessError
from source.controllers.asd import ASDController
from source.controllers.maintenance import MaintenanceController
from source.tools.localclient import LocalClient
from source.tools.log_handler import LogHandler
from source.tools.packages.package import PackageManager
from source.tools.services.service import ServiceManager


class SDMUpdateController(object):
    """
    Update Controller class for SDM package
    """
    NODE_ID = os.environ['ASD_NODE_ID']
    PACKAGE_NAME = 'openvstorage-sdm'
    ASD_SERVICE_PREFIX = 'alba-asd-'

    _local_client = LocalClient()
    _logger = LogHandler.get('asd-manager', name='update')

    @staticmethod
    def get_package_information():
        """
        Retrieve the installed and candidate for install versions for the specified package_name
        :return: Currently installed and candidate for installation version
        :rtype: tuple
        """
        package_info = {}
        installed = PackageManager.get_installed_versions(client=SDMUpdateController._local_client,
                                                          package_names=PackageManager.SDM_PACKAGE_NAMES)
        candidate = PackageManager.get_candidate_versions(client=SDMUpdateController._local_client,
                                                          package_names=PackageManager.SDM_PACKAGE_NAMES)
        if set(installed.keys()) != set(PackageManager.SDM_PACKAGE_NAMES) or set(candidate.keys()) != set(PackageManager.SDM_PACKAGE_NAMES):
            raise RuntimeError('Failed to retrieve the installed and candidate versions for packages: {0}'.format(', '.join(PackageManager.SDM_PACKAGE_NAMES)))

        asd_services = ASDController.list_asd_services()
        maintenance_services = MaintenanceController.get_services()

        for component, info in {'alba': {'alba': [name for name in asd_services] + [name for name in maintenance_services],
                                         'openvstorage-sdm': []}}.iteritems():
            packages = []
            for package_name, services in info.iteritems():
                old = installed[package_name]
                new = candidate[package_name]
                if old != new:
                    packages.append({'name': package_name,
                                     'installed': old,
                                     'candidate': new,
                                     'namespace': 'alba',  # Namespace refers to json translation file: alba.json
                                     'services_to_restart': []})
                else:
                    services_to_restart = []
                    for service in services:
                        asd_version_file = '/opt/asd-manager/run/{0}.version'.format(service)
                        if SDMUpdateController._local_client.file_exists(asd_version_file):
                            running_version = SDMUpdateController._local_client.file_read(asd_version_file).strip()
                            if running_version != new:
                                old = running_version
                                services_to_restart.append(service)
                    if len(services_to_restart) > 0:
                        packages.append({'name': package_name,
                                         'installed': old,
                                         'candidate': new,
                                         'namespace': 'alba',
                                         'services_to_restart': services_to_restart})
            package_info[component] = packages
        return package_info

    @staticmethod
    def update():
        """
        Execute an update on the local node
        """
        for package_name in PackageManager.SDM_PACKAGE_NAMES:
            PackageManager.install(package_name=package_name, client=SDMUpdateController._local_client)

    @staticmethod
    def restart_services():
        """
        Restart the services ASD services and the Maintenance services
        :return: None
        """
        service_names = [service_name for service_name in ASDController.list_asd_services()]
        service_names.extend([service_name for service_name in MaintenanceController.get_services()])
        for service_name in service_names:
            status, _ = ServiceManager.get_service_status(service_name, SDMUpdateController._local_client)
            if status is False:
                SDMUpdateController._logger.info('Found stopped service {0}. Will not start it.'.format(service_name))
                continue

            SDMUpdateController._logger.info('Restarting service {0}'.format(service_name))
            try:
                ServiceManager.restart_service(service_name, SDMUpdateController._local_client)
            except CalledProcessError as cpe:
                SDMUpdateController._logger.info('Failed to restart service {0} {1}'.format(service_name, cpe))
