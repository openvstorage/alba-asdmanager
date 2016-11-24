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

import os
import json
from flask import request
from source.app.decorators import get, post
from source.app.exceptions import BadRequest
from source.controllers.asd import ASDController
from source.controllers.disk import DiskController
from source.controllers.maintenance import MaintenanceController
from source.controllers.update import SDMUpdateController
from source.tools.configuration.configuration import Configuration
from source.tools.filemutex import file_mutex
from source.tools.fstab import FSTab
from source.tools.log_handler import LogHandler
from subprocess import check_output


class API(object):
    """ ALBA API """
    NODE_ID = os.environ['ASD_NODE_ID']
    CONFIG_ROOT = '/ovs/alba/asdnodes/{0}/config'.format(NODE_ID)

    _logger = LogHandler.get('asd-manager', name='api')

    @staticmethod
    @get('/')
    def index():
        """ Return available API calls """
        return {'node_id': API.NODE_ID}

    @staticmethod
    @get('/net', authenticate=False)
    def net():
        """ Retrieve IP information """
        API._logger.info('Loading network information')
        output = check_output("ip a | grep 'inet ' | sed 's/\s\s*/ /g' | cut -d ' ' -f 3 | cut -d '/' -f 1", shell=True)
        my_ips = output.split('\n')
        return {'ips': [found_ip.strip() for found_ip in my_ips if
                        found_ip.strip() != '127.0.0.1' and found_ip.strip() != '']}

    @staticmethod
    @post('/net')
    def set_net():
        """ Set IP information """
        API._logger.info('Setting network information')
        Configuration.set('{0}/network|ips'.format(API.CONFIG_ROOT), json.loads(request.form['ips']))

    @staticmethod
    @get('/disks')
    def list_disks():
        """ List all disk information """
        API._logger.info('Listing disks')
        return dict((key.split('/')[-1], value) for key, value in DiskController.list_disks().iteritems())

    @staticmethod
    @get('/disks/<disk_id>')
    def index_disk(disk_id):
        """
        Retrieve information about a single disk
        :param disk_id: Identifier of the disk  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0' or 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type disk_id: str
        :return: Disk information
        :rtype: dict
        """
        API._logger.info('Listing disk {0}'.format(disk_id))
        return DiskController.get_disk_data_by_alias(device_alias=disk_id)

    @staticmethod
    @post('/disks/<disk_id>/add')
    def add_disk(disk_id):
        """
        Add a disk
        :param disk_id: Identifier of the disk  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0' or 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type disk_id: str
        :return: Disk information about the newly added disk
        :rtype: dict
        """
        disk_data = DiskController.get_disk_data_by_alias(device_alias=disk_id)
        if disk_data['available'] is False:
            raise BadRequest('Disk already configured')
        alias = disk_data['aliases'][0]
        API._logger.info('Add disk {0}'.format(alias))
        with file_mutex('add_disk'), file_mutex('disk_{0}'.format(disk_id)):
            DiskController.prepare_disk(device_alias=alias)
        return DiskController.get_disk_data_by_alias(device_alias=alias)

    @staticmethod
    @post('/disks/<disk_id>/delete')
    def delete_disk(disk_id):
        """
        Delete a disk
        :param disk_id: Identifier of the disk  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0' or 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type disk_id: str
        :return: None
        """
        disk_data = DiskController.get_disk_data_by_alias(device_alias=disk_id)
        if disk_data['available'] is True:
            raise BadRequest('Disk not yet configured')
        alias = disk_data['aliases'][0]
        API._logger.info('Deleting disk {0}'.format(alias))
        with file_mutex('disk_{0}'.format(disk_id)):
            for partition_alias, mountpoint in FSTab.read().iteritems():
                if partition_alias in disk_data['partition_aliases']:
                    asds = ASDController.list_asds(mountpoint=mountpoint)
                    for asd_id in asds:
                        ASDController.remove_asd(asd_id=asd_id,
                                                 mountpoint=mountpoint)
                    DiskController.clean_disk(device_alias=alias,
                                              mountpoint=mountpoint)
                    break

    @staticmethod
    @post('/disks/<disk_id>/restart')
    def restart_disk(disk_id):
        """
        Restart a disk
        :param disk_id: Identifier of the disk  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0' or 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type disk_id: str
        :return: None
        """
        API._logger.info('Restarting disk {0}'.format(disk_id))
        disk_data = DiskController.get_disk_data_by_alias(device_alias=disk_id)
        alias = disk_data['aliases'][0]
        with file_mutex('disk_{0}'.format(disk_id)):
            API._logger.info('Got lock for restarting disk {0}'.format(alias))
            for partition_alias, mountpoint in FSTab.read().iteritems():
                if partition_alias in disk_data['partition_aliases']:
                    asds = ASDController.list_asds(mountpoint=mountpoint)
                    for asd_id in asds:
                        ASDController.stop_asd(asd_id=asd_id)
                    DiskController.remount_disk(device_alias=alias,
                                                mountpoint=mountpoint)
                    asds = ASDController.list_asds(mountpoint=mountpoint)
                    for asd_id in asds:
                        ASDController.start_asd(asd_id=asd_id)
                    break

    @staticmethod
    @get('/asds')
    def list_asds():
        """
        List all ASDs
        :return: Information about all ASDs on local node
        :rtype: dict
        """
        return dict((partition_alias, ASDController.list_asds(mountpoint=mountpoint)) for partition_alias, mountpoint in FSTab.read().iteritems())

    @staticmethod
    @get('/asds/services')
    def list_asd_services():
        """ List all ASD service names """
        API._logger.info('Listing ASD services')
        return {'services': list(ASDController.list_asd_services())}

    @staticmethod
    @get('/disks/<disk_id>/asds')
    def list_asds_disk(disk_id):
        """
        Lists all ASDs on a given disk
        :param disk_id: Identifier of the disk  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0' or 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type disk_id: str
        :return: ASD information for the specified disk
        :rtype: dict
        """
        disk_data = DiskController.get_disk_data_by_alias(device_alias=disk_id)
        for partition_alias, mountpoint in FSTab.read().iteritems():
            if partition_alias in disk_data['partition_aliases']:
                return ASDController.list_asds(mountpoint=mountpoint)
        raise BadRequest('Disk {0} is not yet initialized'.format(disk_data['aliases'][0]))

    @staticmethod
    @post('/disks/<disk_id>/asds')
    def add_asd_disk(disk_id):
        """
        Adds an ASD to a disk
        :param disk_id: Identifier of the disk  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0' or 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type disk_id: str
        :return: None
        """
        disk_data = DiskController.get_disk_data_by_alias(device_alias=disk_id)
        for partition_alias, mountpoint in FSTab.read().iteritems():
            if partition_alias in disk_data['partition_aliases']:
                with file_mutex('add_asd'):
                    ASDController.create_asd(partition_alias=partition_alias)
                    return
        raise BadRequest('Disk {0} is not yet initialized'.format(disk_data['aliases'][0]))

    @staticmethod
    @get('/disks/<disk_id>/asds/<asd_id>')
    def get_asd(disk_id, asd_id):
        """
        Gets an ASD
        :param disk_id: Identifier of the disk  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0' or 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type disk_id: str
        :param asd_id: Identifier of the ASD  (eg: bnAWEXuPHN5YJceCeZo7KxaQW86ixXd4, found under /mnt/alba-asd/WDCztMxmRqi6Hx21/)
        :type asd_id: str
        :return: ASD information
        :rtype: dict
        """
        disk_data = DiskController.get_disk_data_by_alias(device_alias=disk_id)
        alias = disk_data['aliases'][0]
        for partition_alias, mountpoint in FSTab.read().iteritems():
            if partition_alias in disk_data['partition_aliases']:
                asds = ASDController.list_asds(mountpoint=mountpoint)
                if asd_id not in asds:
                    raise BadRequest('ASD {0} could not be found on disk'.format(alias))
                return asds[asd_id]
        raise BadRequest('Disk {0} is not yet initialized'.format(alias))

    @staticmethod
    @post('/disks/<disk_id>/asds/<asd_id>/restart')
    def restart_asd(disk_id, asd_id):
        """
        Restart an ASD
        :param disk_id: Identifier of the disk  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0' or 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type disk_id: str
        :param asd_id: Identifier of the ASD  (eg: bnAWEXuPHN5YJceCeZo7KxaQW86ixXd4, found under /mnt/alba-asd/WDCztMxmRqi6Hx21/)
        :type asd_id: str
        :return: None
        """
        API._logger.info('Restarting ASD {0}'.format(asd_id))
        _ = disk_id
        ASDController.restart_asd(asd_id=asd_id)

    @staticmethod
    @post('/disks/<disk_id>/asds/<asd_id>/delete')
    def asd_delete(disk_id, asd_id):
        """
        Deletes an ASD on a given disk
        :param disk_id: Identifier of the Disk  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0' or 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type disk_id: str
        :param asd_id: Identifier of the ASD  (eg: bnAWEXuPHN5YJceCeZo7KxaQW86ixXd4, found under /mnt/alba-asd/WDCztMxmRqi6Hx21/)
        :type asd_id: str
        :return: None
        """
        disk_data = DiskController.get_disk_data_by_alias(device_alias=disk_id)
        alias = disk_data['aliases'][0]
        API._logger.info('Removing services for disk {0}'.format(alias))
        for partition_alias, mountpoint in FSTab.read().iteritems():
            if partition_alias in disk_data['partition_aliases']:
                if asd_id not in ASDController.list_asds(mountpoint=mountpoint):
                    raise BadRequest('Could not find ASD {0} on disk {1}'.format(asd_id, alias))
                ASDController.remove_asd(asd_id=asd_id,
                                         mountpoint=mountpoint)
                return
        raise BadRequest('Disk {0} is not yet initialized'.format(alias))

    @staticmethod
    @get('/update/package_information')
    def get_package_information():
        """ Retrieve update information """
        with file_mutex('package_update'):
            API._logger.info('Locking in place for package update')
            return SDMUpdateController.get_package_information()

    @staticmethod
    @post('/update/execute')
    def update():
        """
        Execute an update
        """
        with file_mutex('package_update'):
            return SDMUpdateController.update()

    @staticmethod
    @post('/update/restart_services')
    def restart_services():
        """ Restart services """
        with file_mutex('package_update'):
            return SDMUpdateController.restart_services()

    @staticmethod
    @get('/maintenance')
    def list_maintenance_services():
        """ List all maintenance information """
        API._logger.info('Listing maintenance services')
        return {'services': list(MaintenanceController.get_services())}

    @staticmethod
    @post('/maintenance/<name>/add')
    def add_maintenance_service(name):
        """
        Add a maintenance service with a specific name
        :param name: Name of the maintenance service
        :type name: str
        """
        alba_backend_guid = request.form['alba_backend_guid']
        abm_name = request.form['abm_name']
        MaintenanceController.add_maintenance_service(name, alba_backend_guid, abm_name)

    @staticmethod
    @post('/maintenance/<name>/remove')
    def remove_maintenance_service(name):
        """
        Remove a maintenance service with a specific name
        :param name: Name of the maintenance service
        :type name: str
        """
        MaintenanceController.remove_maintenance_service(name)
