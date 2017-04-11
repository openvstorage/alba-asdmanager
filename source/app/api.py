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
from flask import request, send_from_directory
from source.app import app
from source.app.decorators import get, post
from source.app.exceptions import BadRequest
from source.controllers.asd import ASDController
from source.controllers.disk import DiskController
from source.controllers.generic import GenericController
from source.controllers.maintenance import MaintenanceController
from source.controllers.update import SDMUpdateController
from source.dal.lists.disklist import DiskList
from source.dal.objects.disk import Disk
from source.tools.configuration.configuration import Configuration
from source.tools.filemutex import file_mutex
from source.tools.localclient import LocalClient
from source.tools.log_handler import LogHandler
from source.tools.services.service import ServiceManager
from subprocess import check_output


class API(object):
    """ ALBA API """
    NODE_ID = os.environ['ASD_NODE_ID']
    CONFIG_ROOT = '/ovs/alba/asdnodes/{0}/config'.format(NODE_ID)

    _logger = LogHandler.get('asd-manager', name='api')

    ###########
    # GENERIC #
    ###########
    @staticmethod
    @get('/')
    def index():
        """ Return available API calls """
        return {'node_id': API.NODE_ID}

    @staticmethod
    @get('/net', authenticate=False)
    def net():
        """ Retrieve IP information """
        output = check_output("ip a | grep 'inet ' | sed 's/\s\s*/ /g' | cut -d ' ' -f 3 | cut -d '/' -f 1", shell=True)
        my_ips = output.split('\n')
        return {'ips': [found_ip.strip() for found_ip in my_ips if
                        found_ip.strip() != '127.0.0.1' and found_ip.strip() != '']}

    @staticmethod
    @post('/net')
    def set_net():
        """ Set IP information """
        Configuration.set('{0}/network|ips'.format(API.CONFIG_ROOT), json.loads(request.form['ips']))

    @staticmethod
    @get('/collect_logs')
    def collect_logs():
        """ Collect the logs """
        return {'filename': GenericController.collect_logs()}

    @staticmethod
    @app.route('/downloads/<filename>')
    def download_logs(filename):
        """ Download the tgz containing the logs """
        filename = filename.split('/')[-1]
        API._logger.info('Uploading file {0}'.format(filename))
        return send_from_directory(directory='/opt/asd-manager/downloads', filename=filename)

    #########
    # DISKS #
    #########
    @staticmethod
    @get('/disks')
    def list_disks():
        """ List all disk information """
        DiskController.sync_disks()
        return dict((disk.aliases[0].split('/')[-1], disk.export()) for disk in DiskList.get_usable_disks())

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
        DiskController.sync_disks()
        return DiskList.get_by_alias(disk_id).export()

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
        disk = DiskList.get_by_alias(disk_id)
        if disk.available is False:
            raise BadRequest('Disk {0} already configured'.format(disk.name))
        with file_mutex('add_disk'), file_mutex('disk_{0}'.format(disk_id)):
            DiskController.prepare_disk(disk=disk)
        return DiskList.get_by_alias(disk_id).export()

    @staticmethod
    @post('/disks/<disk_id>/delete')
    def delete_disk(disk_id):
        """
        Delete a disk
        :param disk_id: Identifier of the disk  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0' or 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type disk_id: str
        :return: None
        """
        disk = DiskList.get_by_alias(disk_id, raise_exception=False)
        if disk is None:
            API._logger.warning('Disk with ID {0} is no longer present (or cannot be managed)'.format(disk_id))
            return None

        if disk.available is True:
            raise BadRequest('Disk not yet configured')

        with file_mutex('disk_{0}'.format(disk_id)):
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
                raise RuntimeError('Still some ASDs configured on Disk {0}'.format(disk_id))

    @staticmethod
    @post('/disks/<disk_id>/restart')
    def restart_disk(disk_id):
        """
        Restart a disk
        :param disk_id: Identifier of the disk  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0' or 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type disk_id: str
        :return: None
        """
        disk = DiskList.get_by_alias(disk_id)
        with file_mutex('disk_{0}'.format(disk_id)):
            API._logger.info('Got lock for restarting disk {0}'.format(disk_id))
            for asd in disk.asds:
                ASDController.stop_asd(asd=asd)
            DiskController.remount_disk(disk=disk)
            for asd in disk.asds:
                ASDController.start_asd(asd=asd)

    ########
    # ASDS #
    ########
    @staticmethod
    @get('/asds')
    def list_asds():
        """
        List all ASDs
        :return: Information about all ASDs on local node
        :rtype: dict
        """
        asds = {}
        for disk in DiskList.get_usable_disks():
            if len(disk.asds) > 0:
                asds[disk.partition_aliases[0]] = dict((asd.asd_id, asd.export()) for asd in disk.asds)
        return asds

    @staticmethod
    @get('/asds/services')
    def list_asd_services():
        """ List all ASD service names """
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
        disk = DiskList.get_by_alias(disk_id)
        return dict((asd.asd_id, asd.export()) for asd in disk.asds)

    @staticmethod
    @post('/disks/<disk_id>/asds')
    def add_asd_disk(disk_id):
        """
        Adds an ASD to a disk
        :param disk_id: Identifier of the disk  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0' or 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type disk_id: str
        :return: None
        """
        DiskController.sync_disks()
        disk = DiskList.get_by_alias(disk_id)
        with file_mutex('add_asd'):
            ASDController.create_asd(disk)

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
        disk = DiskList.get_by_alias(disk_id)
        asds = [asd for asd in disk.asds if asd.asd_id == asd_id]
        if len(asds) != 1:
            raise BadRequest('Could not find ASD {0} on Disk {1}'.format(asd_id, disk_id))
        return asds[0].export()

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
        disk = DiskList.get_by_alias(disk_id)
        asds = [asd for asd in disk.asds if asd.asd_id == asd_id]
        if len(asds) != 1:
            raise BadRequest('Could not find ASD {0} on Disk {1}'.format(asd_id, disk_id))
        ASDController.restart_asd(asds[0])

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
        disk = DiskList.get_by_alias(disk_id)
        asds = [asd for asd in disk.asds if asd.asd_id == asd_id]
        if len(asds) != 1:
            raise BadRequest('Could not find ASD {0} on Disk {1}'.format(asd_id, disk_id))
        ASDController.remove_asd(asds[0])

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
        """
        with file_mutex('package_update'):
            return SDMUpdateController.update(package_name=package_name)

    @staticmethod
    @post('/update/execute/<status>')
    def execute_update(status):
        """
        This call is required when framework has old code and SDM has been updated (as off 30 Nov 2016)
        Old code tries to initiate update providing a status, while new code no longer requires this status
        :param status: Unused
        :type status: str
        """
        _ = status
        with file_mutex('package_update'):
            SDMUpdateController.update(package_name='alba')
            SDMUpdateController.update(package_name='openvstorage-sdm')
            return {'status': 'done'}

    ####################
    # GENERIC SERVICES #
    ####################
    @staticmethod
    @post('/update/restart_services')
    def restart_services():
        """ Restart services """
        with file_mutex('package_update'):
            return SDMUpdateController.restart_services()

    @staticmethod
    @get('/service_status/<name>')
    def get_service_status(name):
        """
        Retrieve the status of the service specified
        :param name: Name of the service to check
        :type name: str
        :return: Status of the service
        :rtype: str
        """
        client = LocalClient()
        if ServiceManager.has_service(name=name, client=client):
            return {'status': ServiceManager.get_service_status(name=name, client=client)}
        return {'status': None}

    ########################
    # MAINTENANCE SERVICES #
    ########################
    @staticmethod
    @get('/maintenance')
    def list_maintenance_services():
        """ List all maintenance information """
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
