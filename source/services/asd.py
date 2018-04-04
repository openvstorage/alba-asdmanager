#! /usr/bin/python
# Copyright (C) 2018 iNuron NV
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
import argparse
import grp
import os
import pwd
import subprocess
import sys
sys.path.append('/opt/asd-manager')  # Path is normally properly set by the Systemd service but just in case...
from source.dal.lists.asdlist import ASDList
from source.dal.lists.settinglist import SettingList
from source.controllers.disk import DiskController
from source.tools.asdconfiguration import ASDConfigurationManager
from source.tools.logger import Logger
from source.tools.servicefactory import ServiceFactory
from source.tools.packagefactory import PackageFactory


class ASDService(object):

    _logger = Logger('asd_service')

    @classmethod
    def start_pre(cls, asd_id, *args, **kwargs):
        # type: (str, *any, **any) -> None
        """
        Determine if the ASD is allowed to start
        Perform some pre-start actions
        Will exit properly when all checks have passed, else it will exit with exit_code(1) because
        ExecStart= commands are only run after all ExecStartPre= commands that were not prefixed with a "-" exit successfully.
        :param asd_id: ID of the ASD
        :type asd_id: str
        :raises KeyError: when the user or group 'alba' is not found
        :return: None
        :rtype: NoneType
        """
        _ = args, kwargs
        try:
            node_id = SettingList.get_setting_by_code(code='node_id').value
            alba_pkg_name, alba_version_cmd = PackageFactory.get_package_and_version_cmd_for(component='alba')  # Call here, because this potentially raises error, which should happen before actually making changes
            if not os.path.exists(ServiceFactory.RUN_FILE_DIR):
                cls._logger.info('Creating the run file directory')
                os.makedirs(ServiceFactory.RUN_FILE_DIR)
                try:
                    uid = pwd.getpwnam('alba').pw_uid
                    gid = grp.getgrnam('alba').gr_gid
                except KeyError:
                    cls._logger.exception('User and/or group \'alba\' not found')
                    raise
                os.chown(ServiceFactory.RUN_FILE_DIR, uid, gid)
            asd = ASDList.get_by_asd_id(asd_id)
            running_alba_version = subprocess.check_output(alba_version_cmd.split())
            run_file_path = os.path.join(ServiceFactory.RUN_FILE_DIR, '{0}.version'.format(asd.service_name))
            cls._logger.info('Adding alba version info to the run file (Path: {0})'.format(run_file_path))
            with open(run_file_path, 'w') as run_file:
                entry = '{0}={1}'.format(alba_pkg_name, running_alba_version)
                cls._logger.info('Running with {0}'.format(entry))
                run_file.write(entry)
            if ASDConfigurationManager.has_ownership(asd_id) is False:
                cls._logger.warning('Node {0} has no ownership over ASD with ID {1}. Exiting'.format(node_id, asd_id))
                sys.exit(1)
            # Mount the disk so the ASD can run
            cls._logger.info('Mounting the disk for ASD with ID {0}'.format(asd_id))
            DiskController.mount(disk=asd.disk)
        except Exception:
            cls._logger.exception('Exception occurred during start-pre for ASD {0}'.format(asd_id))
            raise

    @classmethod
    def stop_post(cls, asd_id, *args, **kwargs):
        # type: (str, *any, **any) -> None
        """
        Perform the post-stop actions
        Matches the ExecStopPost section of the ASD service
        :param asd_id: ID of the ASD
        :type asd_id: str
        :return: None
        :rtype: NoneType
        """
        _ = args, kwargs
        try:
            # Mount the disk so the ASD can run
            asd = ASDList.get_by_asd_id(asd_id)
            cls._logger.info('Unmounting the disk for ASD with ID {0}'.format(asd_id))
            DiskController.unmount(disk=asd.disk)
        except Exception:
            cls._logger.exception('Exception occurred during stop-post for ASD {0}'.format(asd_id))
            raise


if __name__ == '__main__':
    # @todo the service is ran as user Alba. DiskController creates a local sshclient as root
    # Unable to mount /unmount because of this
    parser = argparse.ArgumentParser(prog='asd-service', description='An ALBA ASD service')
    subparsers = parser.add_subparsers(help='Possible options for the ASD service')

    # Uses new arguments so update code is required (already required because of the new service file)
    parser_prestart = subparsers.add_parser('start-pre', help='Run the \'ExecStartPre\' logic for the ASD service')
    parser_prestart.add_argument('asd_id', metavar='asd-id', help="The identifier of the ASD", type=str)
    parser_prestart.set_defaults(func=ASDService.start_pre)

    parser_remove = subparsers.add_parser('stop-post', help='Run the \'ExecStopPost\' logic for the ASD service')
    parser_remove.set_defaults(func=ASDService.stop_post)
    parser_remove.add_argument('asd_id', metavar='asd-id', help="The identifier of the ASD", type=str)

    arguments = parser.parse_args()
    arguments.func(**vars(arguments))
