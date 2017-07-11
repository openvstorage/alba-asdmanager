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
import copy
from subprocess import CalledProcessError
from ovs_extensions.generic.sshclient import SSHClient
from source.controllers.asd import ASDController
from source.controllers.maintenance import MaintenanceController
from source.tools.log_handler import LogHandler
from source.tools.packagefactory import PackageFactory
from source.tools.servicefactory import ServiceFactory


class SDMUpdateController(object):
    """
    Update Controller class for SDM package
    """
    _local_client = SSHClient(endpoint='127.0.0.1', username='root')
    _logger = LogHandler.get('asd-manager', name='update')
    _packages_alba = ['alba', 'alba-ee']
    _packages_mutual_excl = [_packages_alba]
    _package_manager = PackageFactory.get_manager()

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
        sdm_package_names = SDMUpdateController._package_manager.package_names
        binaries = SDMUpdateController._package_manager.get_binary_versions(client=SDMUpdateController._local_client, package_names=SDMUpdateController._packages_alba)
        installed = SDMUpdateController._package_manager.get_installed_versions(client=SDMUpdateController._local_client, package_names=sdm_package_names)
        candidate = SDMUpdateController._package_manager.get_candidate_versions(client=SDMUpdateController._local_client, package_names=sdm_package_names)
        not_installed = set(sdm_package_names) - set(installed.keys())
        candidate_difference = set(sdm_package_names) - set(candidate.keys())

        for package_name in not_installed:
            found = False
            for entry in SDMUpdateController._packages_mutual_excl:
                if package_name in entry:
                    found = True
                    if entry[1 - entry.index(package_name)] in not_installed:
                        raise RuntimeError('Conflicting packages installed: {0}'.format(entry))
            if found is False:
                raise RuntimeError('Missing non-installed package: {0}'.format(package_name))
            if package_name not in candidate_difference:
                raise RuntimeError('Unexpected difference in missing installed/candidates: {0}'.format(package_name))
            candidate_difference.remove(package_name)
        if len(candidate_difference) > 0:
            raise RuntimeError('No candidates available for some packages: {0}'.format(candidate_difference))

        alba_package = 'alba' if 'alba' in installed.keys() else 'alba-ee'
        version_mapping = {'alba': ['alba', 'alba-ee']}

        package_info = {}
        default_entry = {'candidate': None,
                         'installed': None,
                         'services_to_restart': []}

        #                     component: package_name: services_with_run_file
        for component, info in {'alba': {alba_package: list(ASDController.list_asd_services()) + list(MaintenanceController.get_services()),
                                         'openvstorage-sdm': []}}.iteritems():
            component_info = {}
            for package, services in info.iteritems():
                for service in services:
                    version_file = '/opt/asd-manager/run/{0}.version'.format(service)
                    if not SDMUpdateController._local_client.file_exists(version_file):
                        SDMUpdateController._logger.warning('Failed to find a version file in /opt/asd-manager/run for service {0}'.format(service))
                        continue
                    package_name = package
                    running_versions = SDMUpdateController._local_client.file_read(version_file).strip()
                    for version in running_versions.split(';'):
                        if '=' in version:
                            package_name = version.split('=')[0]
                            running_version = version.split('=')[1]
                        else:
                            running_version = version

                        did_check = False
                        for mapped_package_name in version_mapping.get(package_name, [package_name]):
                            if mapped_package_name not in sdm_package_names:
                                raise ValueError('Unknown package dependency found in {0}'.format(version_file))
                            if mapped_package_name not in binaries or mapped_package_name not in installed:
                                continue

                            did_check = True
                            if running_version is not None and running_version != binaries[mapped_package_name]:
                                if package_name not in component_info:
                                    component_info[mapped_package_name] = copy.deepcopy(default_entry)
                                component_info[mapped_package_name]['installed'] = running_version
                                component_info[mapped_package_name]['candidate'] = binaries[mapped_package_name]
                                component_info[mapped_package_name]['services_to_restart'].append(service)
                                break
                        if did_check is False:
                            raise RuntimeError('Binary version for package {0} was not retrieved'.format(package_name))

                if installed[package] != candidate[package] and package not in component_info:
                    component_info[package] = copy.deepcopy(default_entry)
                    component_info[package]['installed'] = installed[package]
                    component_info[package]['candidate'] = candidate[package]
            if component_info:
                package_info[component] = component_info
        return package_info

    @staticmethod
    def update(package_name):
        """
        Update the package on the local node
        """
        SDMUpdateController._logger.debug('Installing package {0}'.format(package_name))
        SDMUpdateController._package_manager.install(package_name=package_name, client=SDMUpdateController._local_client)
        SDMUpdateController._logger.debug('Installed package {0}'.format(package_name))

    @staticmethod
    def restart_services():
        """
        Restart the services ASD services and the Maintenance services
        :return: None
        """
        service_names = [service_name for service_name in ASDController.list_asd_services()]
        service_names.extend([service_name for service_name in MaintenanceController.get_services()])
        service_manager = ServiceFactory.get_manager()
        for service_name in service_names:
            if service_manager.get_service_status(service_name, SDMUpdateController._local_client) != 'active':
                SDMUpdateController._logger.warning('Found stopped service {0}. Will not start it.'.format(service_name))
                continue

            SDMUpdateController._logger.debug('Restarting service {0}'.format(service_name))
            try:
                service_manager.restart_service(service_name, SDMUpdateController._local_client)
            except CalledProcessError as cpe:
                SDMUpdateController._logger.debug('Failed to restart service {0} {1}'.format(service_name, cpe))
