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
API views
"""

import json
from flask import request, send_from_directory
from ovs_extensions.api.exceptions import HttpNotAcceptableException, HttpNotFoundException
from ovs_extensions.dal.base import ObjectNotFoundException
from ovs_extensions.generic.filemutex import file_mutex
from ovs_extensions.generic.sshclient import SSHClient
from source.app import app
from source.app.decorators import HTTPRequestDecorators
from source.controllers.asd import ASDController
from source.controllers.disk import DiskController
from source.controllers.generic import GenericController
from source.controllers.maintenance import MaintenanceController
from source.controllers.update import SDMUpdateController
from source.dal.lists.disklist import DiskList
from source.dal.lists.settinglist import SettingList
from source.dal.objects.disk import Disk
from source.tools.configuration import Configuration
from source.tools.logger import Logger
from source.tools.osfactory import OSFactory
from source.tools.servicefactory import ServiceFactory


class API(object):
    """ ALBA API """
    _logger = Logger('flask')

    get = HTTPRequestDecorators.get
    post = HTTPRequestDecorators.post
    delete = HTTPRequestDecorators.delete
    wrap = HTTPRequestDecorators.proper_wrap

    ###########
    # GENERIC #
    ###########
    @staticmethod
    @get('/')
    @wrap('node_id')
    def index():
        """
        Retrieve the local node ID
        :return: Node ID
        :rtype: dict
        """
        return SettingList.get_setting_by_code(code='node_id').value

    @staticmethod
    @get('/net', authenticate=False)
    @wrap('ips')
    def net():
        """
        Retrieve IP information
        :return: IPs found on the local system (excluding the loop-back IPs)
        :rtype: dict
        """
        return OSFactory.get_manager().get_ip_addresses()

    @staticmethod
    @post('/net')
    def set_net():
        """
        Set IP information
        :return: None
        :rtype: NoneType
        """
        node_id = SettingList.get_setting_by_code(code='node_id').value
        Configuration.set('{0}|ips'.format(Configuration.ASD_NODE_CONFIG_NETWORK_LOCATION.format(node_id)), json.loads(request.form['ips']))

    @staticmethod
    @get('/collect_logs')
    @wrap('filename')
    def collect_logs():
        """
        Collect the logs
        :return: The location where the file containing the logs was stored
        :rtype: dict
        """
        return GenericController.collect_logs()

    @staticmethod
    @app.route('/downloads/<filename>')
    def download_logs(filename):
        """
        Download the tgz containing the logs
        :param filename: Name of the file to make available for download
        :type filename: str
        :return: Flask response
        :rtype: Flask response
        """
        filename = filename.split('/')[-1]
        API._logger.info('Uploading file {0}'.format(filename))
        return send_from_directory(directory='/opt/asd-manager/downloads', filename=filename)

    #################
    # STACK / SLOTS #
    #################

    @staticmethod
    @get('/slots')
    def get_slots():
        """
        Gets the current stack (slot based)
        :return: Stack information
        :rtype: dict
        """
        stack = {}
        for disk in DiskList.get_usable_disks():
            slot_id = disk.aliases[0].split('/')[-1]
            stack[slot_id] = disk.export()
            stack[slot_id].update({'osds': dict((asd.asd_id, asd.export()) for asd in disk.asds)})
        return stack

    @staticmethod
    @post('/slots/<slot_id>/asds')
    def asd_add(slot_id):
        """
        Add an ASD to the slot specified
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        disk = DiskList.get_by_alias(slot_id)
        if disk.available is True:
            with file_mutex('add_disk'), file_mutex('disk_{0}'.format(slot_id)):
                DiskController.prepare_disk(disk=disk)
                disk = Disk(disk.id)
        with file_mutex('add_asd'):
            ASDController.create_asd(disk)

    @staticmethod
    @delete('/slots/<slot_id>/asds/<asd_id>')
    def asd_delete_by_slot(slot_id, asd_id):
        """
        Delete an ASD from the slot specified
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :param asd_id: Identifier of the ASD  (eg: bnAWEXuPHN5YJceCeZo7KxaQW86ixXd4, found under /mnt/alba-asd/WDCztMxmRqi6Hx21/)
        :type asd_id: str
        :return: None
        :rtype: NoneType
        """
        # If the disk would be missing, this will still return a disk object and the asds should be able to be found
        # Sync disk will only remove disks once they have no more asds linked to them
        disk = DiskList.get_by_alias(slot_id)
        asds = [asd for asd in disk.asds if asd.asd_id == asd_id]
        if len(asds) != 1:
            raise HttpNotFoundException(error='asd_not_found',
                                        error_description='Could not find ASD {0} on Slot {1}'.format(asd_id, slot_id))
        ASDController.remove_asd(asds[0])

    @staticmethod
    @post('/slots/<slot_id>/asds/<asd_id>/restart')
    def asd_restart(slot_id, asd_id):
        """
        Restart an ASD
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :param asd_id: Identifier of the ASD  (eg: bnAWEXuPHN5YJceCeZo7KxaQW86ixXd4, found under /mnt/alba-asd/WDCztMxmRqi6Hx21/)
        :type asd_id: str
        :return: None
        :rtype: NoneType
        """
        disk = DiskList.get_by_alias(slot_id)
        asds = [asd for asd in disk.asds if asd.asd_id == asd_id]
        if len(asds) != 1:
            raise HttpNotFoundException(error='asd_not_found',
                                        error_description='Could not find ASD {0} on Slot {1}'.format(asd_id, slot_id))
        ASDController.restart_asd(asds[0])

    @staticmethod
    @post('/slots/<slot_id>/asds/<asd_id>/update')
    def asd_update(slot_id, asd_id):
        """
        Restart an ASD
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :param asd_id: Identifier of the ASD  (eg: bnAWEXuPHN5YJceCeZo7KxaQW86ixXd4, found under /mnt/alba-asd/WDCztMxmRqi6Hx21/)
        :type asd_id: str
        :return: None
        :rtype: NoneType
        """
        disk = DiskList.get_by_alias(slot_id)
        asds = [asd for asd in disk.asds if asd.asd_id == asd_id]
        if len(asds) != 1:
            raise HttpNotFoundException(error='asd_not_found',
                                        error_description='Could not find ASD {0} on Slot {1}'.format(asd_id, slot_id))
        ASDController.update_asd(asd=asds[0], update_data=json.loads(request.form['update_data']))

    @staticmethod
    @post('/slots/<slot_id>/restart')
    def slot_restart(slot_id):
        """
       Restart a slot
       :param slot_id: Identifier of the slot  (eg: 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
       :type slot_id: str
       :return: None
       """
        disk = DiskList.get_by_alias(slot_id)
        with file_mutex('slot_{0}'.format(slot_id)):
            API._logger.info('Got lock for restarting slot {0}'.format(slot_id))
            for asd in disk.asds:
                ASDController.stop_asd(asd=asd)
            DiskController.remount_disk(disk=disk)
            for asd in disk.asds:
                ASDController.start_asd(asd=asd)

    @staticmethod
    @delete('/slots/<slot_id>')
    def clear_slot(slot_id):
        """
        Clears a slot
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        try:
            disk = DiskList.get_by_alias(slot_id)
        except ObjectNotFoundException:
            API._logger.warning('Disk with ID {0} is no longer present (or cannot be managed)'.format(slot_id))
            return None

        if disk.available is True:
            raise HttpNotAcceptableException(error='disk_not_configured', error_description='Disk not yet configured')

        with file_mutex('disk_{0}'.format(slot_id)):
            last_exception = None
            for asd in disk.asds:
                try:
                    ASDController.remove_asd(asd=asd)
                except Exception as ex:
                    last_exception = ex
            disk = Disk(disk.id)
            if len(disk.asds) == 0:
                DiskController.clean_disk(disk=disk)
            elif last_exception is not None:
                raise last_exception
            else:
                raise RuntimeError('Still some ASDs configured on Disk {0}'.format(slot_id))

    #########
    # DISKS #
    #########

    @staticmethod
    @get('/disks')
    def list_disks():
        """ Obsolete """
        return {}

    @staticmethod
    @get('/disks/<disk_id>')
    def index_disk(disk_id):
        """ Obsolete """
        raise RuntimeError('Disk {0} not found.'.format(disk_id))

    @staticmethod
    @post('/disks/<disk_id>/add')
    def add_disk(disk_id):
        """ Obsolete """
        raise RuntimeError('Disk {0} not found'.format(disk_id))

    @staticmethod
    @post('/disks/<disk_id>/delete')
    def delete_disk(disk_id):
        """ Obsolete """
        raise RuntimeError('Disk {0} not found'.format(disk_id))

    @staticmethod
    @post('/disks/<disk_id>/restart')
    def restart_disk(disk_id):
        """ Obsolete """
        raise RuntimeError('Disk {0} not found'.format(disk_id))

    ########
    # ASDS #
    ########

    @staticmethod
    @get('/asds')
    def list_asds():
        """ Obsolete """
        return {}

    @staticmethod
    @get('/asds/services')
    def list_asd_services():
        """ Obsolete """
        return {'services': []}

    @staticmethod
    @get('/disks/<disk_id>/asds')
    def list_asds_disk(disk_id):
        """ Obsolete """
        raise RuntimeError('Disk {0} not found'.format(disk_id))

    @staticmethod
    @get('/disks/<disk_id>/get_claimed_asds')
    def get_claimed_asds(disk_id):
        """ Obsolete """
        raise RuntimeError('Disk {0} not found'.format(disk_id))

    @staticmethod
    @post('/disks/<disk_id>/asds')
    def add_asd_disk(disk_id):
        """ Obsolete """
        raise RuntimeError('Disk {0} not found'.format(disk_id))

    @staticmethod
    @get('/disks/<disk_id>/asds/<asd_id>')
    def get_asd(disk_id, asd_id):
        """ Obsolete """
        raise RuntimeError('Disk {0} not found'.format(disk_id))

    @staticmethod
    @post('/disks/<disk_id>/asds/<asd_id>/restart')
    def restart_asd(disk_id, asd_id):
        """ Obsolete """
        raise RuntimeError('Disk {0} not found'.format(disk_id))

    @staticmethod
    @post('/disks/<disk_id>/asds/<asd_id>/delete')
    def asd_delete(disk_id, asd_id):
        """ Obsolete """
        raise RuntimeError('Disk {0} not found'.format(disk_id))

    ##########
    # UPDATE #
    ##########

    @staticmethod
    @get('/update/package_information')
    def get_package_information_new():
        """
        Retrieve update information
        This call is used by the new framework code (as off 30 Nov 2016)
        In case framework has new code, but SDM runs old code, the asdmanager.py plugin will adjust the old format to the new format
        :return: Installed and candidate for install version for all SDM related packages
        :rtype: dict
        """
        with file_mutex('package_update'):
            API._logger.info('Locking in place for package update')
            return SDMUpdateController.get_package_information()

    @staticmethod
    @get('/update/information')
    def get_package_information_old():
        """
        Retrieve update information
        This call is required when framework has old code and SDM has been updated (as off 30 Nov 2016)
        Old code tries to call /update/information and expects data formatted in the old style
        :return: Installed and candidate for install version for all SDM related packages
        :rtype: dict
        """
        return_value = {'version': '', 'installed': ''}
        with file_mutex('package_update'):
            API._logger.info('Locking in place for package update')
            update_info = SDMUpdateController.get_package_information().get('alba', {})
            if 'openvstorage-sdm' in update_info:
                return_value['version'] = update_info['openvstorage-sdm']['candidate']
                return_value['installed'] = update_info['openvstorage-sdm']['installed']
            elif 'alba' in update_info:
                return_value['version'] = update_info['alba']['candidate']
                return_value['installed'] = update_info['alba']['installed']
        return return_value

    @staticmethod
    @post('/update/install/<package_name>')
    def update(package_name):
        """
        Install the specified package
        :return: None
        :rtype: NoneType
        """
        with file_mutex('package_update'):
            SDMUpdateController.update(package_name=package_name)

    @staticmethod
    @post('/update/execute/<status>')
    @wrap('status')
    def execute_update(status):
        """
        This call is required when framework has old code and SDM has been updated (as off 30 Nov 2016)
        Old code tries to initiate update providing a status, while new code no longer requires this status
        :param status: Unused
        :type status: str
        :return: The status of the ongoing update
        :rtype: dict
        """
        _ = status
        with file_mutex('package_update'):
            SDMUpdateController.update(package_name='alba')
            SDMUpdateController.update(package_name='openvstorage-sdm')
            return 'done'

    @staticmethod
    @get('/update/installed_version_package/<package_name>')
    @wrap('version')
    def update_installed_version_package(package_name):
        """
        Retrieve the currently installed package version
        :param package_name: Name of the package to retrieve the version for
        :type package_name: str
        :return: Version of the currently installed package
        :rtype: str
        """
        return SDMUpdateController.get_installed_version_for_package(package_name=package_name)

    @staticmethod
    @post('/update/execute_migration_code')
    def update_execute_migration_code():
        """
        Run some migration code after an update has been done
        :return: None
        :rtype: NoneType
        """
        with file_mutex('post_update'):
            SDMUpdateController.execute_migration_code()

    ####################
    # GENERIC SERVICES #
    ####################

    @staticmethod
    @post('/update/restart_services')
    def restart_services():
        """
        Restart services
        :return: None
        :rtype: NoneType
        """
        with file_mutex('package_update'):
            SDMUpdateController.restart_services(service_names=json.loads(request.form.get('service_names', "[]")))

    @staticmethod
    @get('/service_status/<name>')
    @wrap('status')
    def get_service_status(name):
        """
        Retrieve the status of the service specified
        :param name: Name of the service to check
        :type name: str
        :return: Status of the service
        :rtype: dict
        """
        client = SSHClient(endpoint='127.0.0.1', username='root')
        service_manager = ServiceFactory.get_manager()
        if service_manager.has_service(name=name, client=client):
            status = service_manager.get_service_status(name=name, client=client)
            return (status == 'active', status)
        return None

    ########################
    # MAINTENANCE SERVICES #
    ########################

    @staticmethod
    @get('/maintenance')
    @wrap
    def list_maintenance_services():
        """
        List all maintenance information
        :return: The names of all maintenance services found on the system
        :rtype: dict
        """
        return list(MaintenanceController.get_services())

    @staticmethod
    @post('/maintenance/<name>/add')
    def add_maintenance_service(name):
        """
        Add a maintenance service with a specific name
        :param name: Name of the maintenance service
        :type name: str
        :return: None
        :rtype: NoneType
        """
        MaintenanceController.add_maintenance_service(name=name,
                                                      abm_name=request.form['abm_name'],
                                                      alba_backend_guid=request.form['alba_backend_guid'],
                                                      read_preferences=json.loads(request.form.get('read_preferences', "[]")))

    @staticmethod
    @post('/maintenance/<name>/remove')
    def remove_maintenance_service(name):
        """
        Remove a maintenance service with a specific name
        :param name: Name of the maintenance service
        :type name: str
        :return: None
        :rtype: NoneType
        """
        MaintenanceController.remove_maintenance_service(name=name,
                                                         alba_backend_guid=request.form.get('alba_backend_guid'))
