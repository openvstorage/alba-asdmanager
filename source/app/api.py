# Copyright 2016 iNuron NV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
API views
"""

import os
import json
import datetime
from flask import request
from subprocess import check_output
from source.app.decorators import get
from source.app.decorators import post
from source.app.exceptions import BadRequest
from source.controllers.asd import ASDController
from source.controllers.maintenance import MaintenanceController
from source.controllers.disk import DiskController
from source.controllers.update import UpdateController
from source.tools.configuration import EtcdConfiguration
from source.tools.filemutex import FileMutex
from source.tools.fstab import FSTab


class API(object):
    """ ALBA API """
    NODE_ID = os.environ['ASD_NODE_ID']
    CONFIG_ROOT = '/ovs/alba/asdnodes/{0}/config'.format(NODE_ID)

    @staticmethod
    def _log(message):
        print '{0} - {1}'.format(str(datetime.datetime.now()), message)

    @staticmethod
    @get('/')
    def index():
        """ Return available API calls """
        return {'node_id': API.NODE_ID}

    @staticmethod
    @get('/net', authenticate=False)
    def net():
        """ Retrieve IP information """
        API._log('Loading network information')
        output = check_output("ip a | grep 'inet ' | sed 's/\s\s*/ /g' | cut -d ' ' -f 3 | cut -d '/' -f 1", shell=True)
        my_ips = output.split('\n')
        return {'ips': [found_ip.strip() for found_ip in my_ips if
                        found_ip.strip() != '127.0.0.1' and found_ip.strip() != '']}

    @staticmethod
    @post('/net')
    def set_net():
        """ Set IP information """
        API._log('Setting network information')
        EtcdConfiguration.set('{0}/network|ips'.format(API.CONFIG_ROOT), json.loads(request.form['ips']))

    @staticmethod
    @get('/disks')
    def list_disks():
        """ List all disk information """
        API._log('Listing disks')
        return DiskController.list_disks()

    @staticmethod
    @get('/disks/<disk>')
    def index_disk(disk):
        """
        Retrieve information about a single disk
        :param disk: Identifier of the disk
        """
        API._log('Listing disk {0}'.format(disk))
        all_disks = DiskController.list_disks()
        if disk not in all_disks:
            raise BadRequest('Disk unknown')
        return all_disks[disk]

    @staticmethod
    @post('/disks/<disk>/add')
    def add_disk(disk):
        """
        Add a disk
        :param disk: Identifier of the disk
        """
        API._log('Add disk {0}'.format(disk))
        all_disks = DiskController.list_disks()
        if disk not in all_disks:
            raise BadRequest('Disk not available')
        if all_disks[disk]['available'] is False:
            raise BadRequest('Disk already configured')
        with FileMutex('add_disk'), FileMutex('disk_{0}'.format(disk)):
            DiskController.prepare_disk(disk)
        all_disks = DiskController.list_disks()
        if disk not in all_disks:
            raise BadRequest('Disk could not be added')
        return all_disks[disk]

    @staticmethod
    @post('/disks/<disk>/delete')
    def delete_disk(disk):
        """
        Delete a disk
        :param disk: Identifier of the disk
        """
        API._log('Deleting disk {0}'.format(disk))
        all_disks = DiskController.list_disks()
        if disk not in all_disks:
            raise BadRequest('Disk not available')
        if all_disks[disk]['available'] is True:
            raise BadRequest('Disk not yet configured')
        with FileMutex('disk_{0}'.format(disk)):
            mountpoints = FSTab.read()
            if disk in mountpoints:
                mountpoint = mountpoints[disk]
                asds = ASDController.list_asds(mountpoint)
                for asd_id in asds:
                    ASDController.remove_asd(asd_id, mountpoint)
            DiskController.clean_disk(disk)

    @staticmethod
    @post('/disks/<disk>/restart')
    def restart_disk(disk):
        """
        Restart a disk
        :param disk: Identifier of the disk
        """
        API._log('Restarting disk {0}'.format(disk))
        all_disks = DiskController.list_disks()
        if disk not in all_disks:
            raise BadRequest('Disk not available')
        if all_disks[disk]['available'] is False:
            raise BadRequest('Disk already configured')
        with FileMutex('disk_{0}'.format(disk)):
            API._log('Got lock for restarting disk {0}'.format(disk))
            mountpoints = FSTab.read()
            if disk in mountpoints:
                mountpoint = mountpoints[disk]
                asds = ASDController.list_asds(mountpoint)
                for asd_id in asds:
                    ASDController.stop_asd(asd_id)
            DiskController.remount_disk(disk)
            mountpoints = FSTab.read()
            if disk in mountpoints:
                mountpoint = mountpoints[disk]
                asds = ASDController.list_asds(mountpoint)
                for asd_id in asds:
                    ASDController.start_asd(asd_id)

    @staticmethod
    @get('/asds')
    def list_asds():
        asds = {}
        mountpoints = FSTab.read()
        for disk, mountpoint in mountpoints.iteritems():
            asds[disk] = ASDController.list_asds(mountpoint)
        return asds

    @staticmethod
    @get('/disks/<disk>/asds')
    def list_asds_disk(disk):
        """
        Lists all ASDs on a given disk
        :param disk: Identifier of the disk
        """
        mountpoints = FSTab.read()
        if disk not in mountpoints:
            raise BadRequest('Disk {0} is not yet initialized'.format(disk))
        mountpoint = mountpoints[disk]
        asds = ASDController.list_asds(mountpoint)
        return asds

    @staticmethod
    @post('/disks/<disk>/asds')
    def add_asd_disk(disk):
        """
        Adds an ASD to a disk
        :param disk: Identifier of the disk
        """
        mountpoints = FSTab.read()
        if disk not in mountpoints:
            raise BadRequest('Disk {0} is not yet initialized'.format(disk))
        with FileMutex('add_asd'):
            ASDController.create_asd(disk)

    @staticmethod
    @get('/disks/<disk>/asds/<asd_id>')
    def get_asd(disk, asd_id):
        mountpoints = FSTab.read()
        if disk not in mountpoints:
            raise BadRequest('Disk {0} is not yet initialized'.format(disk))
        mountpoint = mountpoints[disk]
        asds = ASDController.list_asds(mountpoint)
        if asd_id not in asds:
            raise BadRequest('ASD {0} could not be found on disk'.format(disk))
        return asds[asd_id]

    @staticmethod
    @post('/disks/<disk>/asds/<asd_id>/restart')
    def restart_asd(disk, asd_id):
        """
        Restart an ASD
        :param disk: Identifier of the disk
        :param asd_id: Identifier of the ASD
        """
        API._log('Restarting ASD {0}'.format(asd_id))
        _ = disk
        ASDController.restart_asd(asd_id)

    @staticmethod
    @post('/disks/<disk>/asds/<asd_id>/delete')
    def asd_delete(disk, asd_id):
        """
        Deletes an ASD on a given Disk
        :param disk: Idientifier of the Disk
        :param asd_id: The ASD ID of the ASD to be removed
        """
        # Stop and remove service
        API._log('Removing services for disk {0}'.format(disk))
        mountpoints = FSTab.read()
        if disk not in mountpoints:
            raise BadRequest('Disk {0} is not yet initialized'.format(disk))
        all_asds = {}
        mountpoints = FSTab.read()
        for mountpoint in mountpoints.values():
            all_asds.update(ASDController.list_asds(mountpoint))
        if asd_id not in all_asds:
            raise BadRequest('Could not find ASD {0} on disk {1}'.format(asd_id, disk))
        mountpoint = mountpoints[disk]
        ASDController.remove_asd(asd_id, mountpoint)

    @staticmethod
    @get('/update/information')
    def get_update_information():
        """ Retrieve update information """
        with FileMutex('package_update'):
            API._log('Locking in place for package update')
            return UpdateController.get_update_information()

    @staticmethod
    @post('/update/execute/<status>')
    def execute_update(status):
        """
        Execute an update
        :param status: Current status of the update
        """
        with FileMutex('package_update'):
            return UpdateController.execute_update(status)

    @staticmethod
    @post('/update/restart_services')
    def restart_services():
        """ Restart services """
        with FileMutex('package_update'):
            return UpdateController.restart_services()

    @staticmethod
    @get('/maintenance')
    def list_maintenance_services():
        """ List all maintenance information """
        API._log('Listing maintenance services')
        data = MaintenanceController.get_services()
        return list(data)

    @staticmethod
    @post('/maintenance/<name>/add')
    def add_maintenance_service(name):
        """
        Add a maintenance service with a specific name
        :param name: Name of the maintenance service
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
        """
        MaintenanceController.remove_maintenance_service(name)
