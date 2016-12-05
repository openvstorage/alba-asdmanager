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
import copy
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
        Retrieve information about the currently installed versions of the core packages
        Retrieve information about the versions to which each package can potentially be updated
        If installed version is different from candidate version --> store this information in model

        Additionally if installed version is identical to candidate version, check the services with a 'run' file
        Verify whether the running version is identical to the candidate version
        If different --> store this information in the model

        Result: Every package with updates or which requires services to be restarted is stored in the model

        :return: Package information
        :rtype: dict
        """
        installed = PackageManager.get_installed_versions(client=SDMUpdateController._local_client, package_names=PackageManager.SDM_PACKAGE_NAMES)
        candidate = PackageManager.get_candidate_versions(client=SDMUpdateController._local_client, package_names=PackageManager.SDM_PACKAGE_NAMES)
        if set(installed.keys()) != set(PackageManager.SDM_PACKAGE_NAMES) or set(candidate.keys()) != set(PackageManager.SDM_PACKAGE_NAMES):
            raise RuntimeError('Failed to retrieve the installed and candidate versions for packages: {0}'.format(', '.join(PackageManager.SDM_PACKAGE_NAMES)))

        package_info = {}
        default_entry = {'candidate': None,
                         'installed': None,
                         'services_to_restart': []}

        #                     component: package_name: services_with_run_file
        for component, info in {'alba': {'alba': list(ASDController.list_asd_services()) + list(MaintenanceController.get_services()),
                                         'openvstorage-sdm': []}}.iteritems():
            component_info = {}
            for package_name, services in info.iteritems():
                for service in services:
                    version_file = '/opt/asd-manager/run/{0}.version'.format(service)
                    if not SDMUpdateController._local_client.file_exists(version_file):
                        SDMUpdateController._logger.warning('Failed to find a version file in /opt/asd-manager/run for service {0}'.format(service))
                        continue
                    running_versions = SDMUpdateController._local_client.file_read(version_file).strip()
                    for version in running_versions.split(';'):
                        if '=' in version:
                            package_name = version.split('=')[0]
                            running_version = version.split('=')[1]
                            if package_name not in PackageManager.SDM_PACKAGE_NAMES:
                                raise ValueError('Unknown package dependency found in {0}'.format(version_file))
                        else:
                            running_version = version
                        if running_version != candidate[package_name]:
                            if package_name not in component_info:
                                component_info[package_name] = copy.deepcopy(default_entry)
                            component_info[package_name]['installed'] = running_version
                            component_info[package_name]['candidate'] = candidate[package_name]
                            component_info[package_name]['services_to_restart'].append(service)

                if installed[package_name] != candidate[package_name] and package_name not in component_info:
                    component_info[package_name] = copy.deepcopy(default_entry)
                    component_info[package_name]['installed'] = installed[package_name]
                    component_info[package_name]['candidate'] = candidate[package_name]
            if component_info:
                package_info[component] = component_info
        return package_info

    @staticmethod
    def update(package_name):
        """
        Update the package on the local node
        """
        SDMUpdateController._logger.debug('Installing package {0}'.format(package_name))
        PackageManager.install(package_name=package_name, client=SDMUpdateController._local_client)
        SDMUpdateController._logger.debug('Installed package {0}'.format(package_name))


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
                SDMUpdateController._logger.warning('Found stopped service {0}. Will not start it.'.format(service_name))
                continue

            SDMUpdateController._logger.debug('Restarting service {0}'.format(service_name))
            try:
                ServiceManager.restart_service(service_name, SDMUpdateController._local_client)
            except CalledProcessError as cpe:
                SDMUpdateController._logger.debug('Failed to restart service {0} {1}'.format(service_name, cpe))
