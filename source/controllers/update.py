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
import json
from distutils.version import LooseVersion
from subprocess import CalledProcessError
from ovs_extensions.generic.sshclient import SSHClient
from source.controllers.asd import ASDController
from source.controllers.maintenance import MaintenanceController
from source.dal.lists.settinglist import SettingList
from source.dal.objects.setting import Setting
from source.tools.configuration import Configuration
from source.tools.logger import Logger
from source.tools.packagefactory import PackageFactory
from source.tools.servicefactory import ServiceFactory

os.environ['OVS_LOGTYPE_OVERRIDE'] = 'file'  # Make sure we log to file during update


class SDMUpdateController(object):
    """
    Update Controller class for SDM package
    """
    _local_client = SSHClient(endpoint='127.0.0.1', username='root')
    _logger = Logger('update')
    _packages_alba = ['alba', 'alba-ee', 'openvstorage-extensions']
    _packages_with_binaries = ['alba', 'alba-ee']
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
        binaries = SDMUpdateController._package_manager.get_binary_versions(client=SDMUpdateController._local_client, package_names=SDMUpdateController._packages_with_binaries)
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
                                         'openvstorage-sdm': [],
                                         'openvstorage-extensions': []}}.iteritems():
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
                            if running_version is not None and LooseVersion(running_version) < binaries[mapped_package_name]:
                                if mapped_package_name not in component_info:
                                    component_info[mapped_package_name] = copy.deepcopy(default_entry)
                                component_info[mapped_package_name]['installed'] = running_version
                                component_info[mapped_package_name]['candidate'] = str(binaries[mapped_package_name])
                                component_info[mapped_package_name]['services_to_restart'].append(service)
                                break
                        if did_check is False:
                            raise RuntimeError('Binary version for package {0} was not retrieved'.format(package_name))

                if installed[package] < candidate[package] and package not in component_info:
                    component_info[package] = copy.deepcopy(default_entry)
                    component_info[package]['installed'] = str(installed[package])
                    component_info[package]['candidate'] = str(candidate[package])
            if component_info:
                package_info[component] = component_info
        return package_info

    @staticmethod
    def update(package_name):
        """
        Update the package on the local node
        """
        SDMUpdateController._logger.info('Installing package {0}'.format(package_name))
        SDMUpdateController._package_manager.install(package_name=package_name, client=SDMUpdateController._local_client)
        SDMUpdateController._logger.info('Installed package {0}'.format(package_name))

    @staticmethod
    def get_installed_version_for_package(package_name):
        """
        Retrieve the currently installed package version
        :param package_name: Name of the package to retrieve the version for
        :type package_name: str
        :return: Version of the currently installed package
        :rtype: str
        """
        installed_version = SDMUpdateController._package_manager.get_installed_versions(client=None, package_names=[package_name])
        if package_name in installed_version:
            return str(installed_version[package_name])

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

            SDMUpdateController._logger.info('Restarting service {0}'.format(service_name))
            try:
                service_manager.restart_service(service_name, SDMUpdateController._local_client)
            except CalledProcessError:
                SDMUpdateController._logger.exception('Failed to restart service {0}'.format(service_name))

    @staticmethod
    def execute_migration_code():
        """
        Run some migration code after an update has been done
        :return: None
        :rtype: NoneType
        """
        # Removal of bootstrap file and store API IP, API port and node ID in SQLite DB
        SDMUpdateController._logger.info('Starting out of band migrations for SDM nodes')

        required_settings = ['api_ip', 'api_port', 'node_id']
        for setting in SettingList.get_settings():
            if setting.code in required_settings:
                required_settings.remove(setting.code)

        if len(required_settings):
            SDMUpdateController._logger.info('Missing required Settings: {0}'.format(', '.join(required_settings)))
            bootstrap_file = '/opt/asd-manager/config/bootstrap.json'

            if SDMUpdateController._local_client.file_exists(bootstrap_file):
                SDMUpdateController._logger.info('Bootstrap file still exists. Retrieving node ID')
                with open(bootstrap_file) as bstr_file:
                    node_id = json.load(bstr_file)['node_id']
            else:
                node_id = SettingList.get_setting_by_code(code='node_id').value

            SDMUpdateController._logger.info('Node ID: {0}'.format(node_id))
            settings_dict = {'node_id': node_id}
            if Configuration.exists(Configuration.ASD_NODE_CONFIG_MAIN_LOCATION.format(node_id)):
                main_config = Configuration.get(Configuration.ASD_NODE_CONFIG_MAIN_LOCATION.format(node_id))
                settings_dict['api_ip'] = main_config['ip']
                settings_dict['api_port'] = main_config['port']

            for code, value in settings_dict.iteritems():
                SDMUpdateController._logger.info('Modeling Setting with code {0} and value {1}'.format(code, value))
                setting = Setting()
                setting.code = code
                setting.value = value
                setting.save()

            SDMUpdateController._local_client.file_delete(bootstrap_file)
        SDMUpdateController._logger.info('Finished out of band migrations for SDM nodes')
