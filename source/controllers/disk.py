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
Disk related code
"""

import json
import time
import uuid
import random
import string
from subprocess import CalledProcessError
from ovs_extensions.dal.base import ObjectNotFoundException
from ovs_extensions.generic.disk import DiskTools, Disk as GenericDisk
from ovs_extensions.generic.sshclient import SSHClient
from source.dal.lists.disklist import DiskList
from source.dal.lists.settinglist import SettingList
from source.dal.objects.disk import Disk
from source.constants.asd import ASD_NODE_CONFIG_MAIN_LOCATION_S3
from source.tools.configuration import Configuration
from source.tools.fstab import FSTab
from source.tools.logger import Logger


class DiskController(object):
    """
    Disk helper methods
    """
    controllers = {}
    _local_client = SSHClient(endpoint='127.0.0.1', username='root')
    _logger = Logger('controllers')

    @staticmethod
    def sync_disks():
        # type: () -> None
        """
        Syncs the disks
        Changes made to this code should be reflected in the framework DiskController.sync_with_reality call.
        :return: None
        :rtype: NoneType
        """
        node_id = SettingList.get_setting_by_code(code='node_id').value
        s3 = Configuration.get(ASD_NODE_CONFIG_MAIN_LOCATION_S3.format(node_id), default=False)
        disks, name_alias_mapping = DiskTools.model_devices(s3=s3)
        disks_by_name = dict((disk.name, disk) for disk in disks)
        alias_name_mapping = name_alias_mapping.reverse_mapping()
        # Specific for the asd-manager: handle unique constraint exception
        DiskController._prepare_for_name_switch(disks)
        # Sync the model
        for disk in DiskList.get_disks():
            generic_disk_model = None  # type: GenericDisk
            for alias in disk.aliases:
                # IBS wont have alias
                if alias in alias_name_mapping:
                    name = alias_name_mapping[alias].replace('/dev/', '')
                    if name in disks_by_name:
                        generic_disk_model = disks_by_name.pop(name)
                        break
            # Partitioned loop, nvme devices no longer show up in alias_name_mapping
            if generic_disk_model is None and disk.name in disks_by_name and (disk.name.startswith(tuple(['fio', 'loop', 'nvme']))):
                generic_disk_model = disks_by_name.pop(disk.name)

            if not generic_disk_model:
                # Remove disk / partitions if not reported by 'lsblk'
                DiskController._remove_disk_model(disk)
            else:
                # Update existing disks and their partitions
                DiskController._sync_disk_with_model(disk, generic_disk_model)
        # Create all disks and their partitions not yet modeled
        for disk_name, generic_disk_model in disks_by_name.iteritems():
            DiskController._model_disk(generic_disk_model)

    @classmethod
    def _remove_disk_model(cls, modeled_disk):
        # type: (Disk) -> None
        """
        Remove the modeled disk
        :param modeled_disk: The modeled disk
        :type modeled_disk: Disk
        :return: None
        :rtype: NoneType
        """
        cls._logger.info('Disk {0} - No longer found'.format(modeled_disk.name))
        if len(modeled_disk.asds) == 0:
            modeled_disk.delete()
            cls._logger.info('Disk {0} - Deleted (no ASDs)'.format(modeled_disk.name))
        else:
            if modeled_disk.state != 'MISSING':
                for partition in modeled_disk.partitions:
                    cls._logger.warning('Disk {0} - Partition with offset {1} - Updated status to MISSING'.format(modeled_disk.name, partition['offset']))
                modeled_disk.state = 'MISSING'
                cls._logger.warning('Disk {0} - Updated status to MISSING'.format(modeled_disk.name))

    @classmethod
    def _sync_disk_with_model(cls, modeled_disk, generic_modeled_disk):
        # type: (Disk, GenericDisk) -> None
        """
        Sync a generic disk with the modeled disk
        :param modeled_disk: The modeled disk
        :type modeled_disk: Disk
        :param generic_modeled_disk: The generic modeled disk (returned by Disktools)
        :type generic_modeled_disk: GenericDisk
        :return: None
        :rtype NoneType
        """
        cls._logger.info('Disk {0} - Found, updating'.format(modeled_disk.name))
        cls._update_disk(modeled_disk, generic_modeled_disk)

    @classmethod
    def _model_disk(cls, generic_disk_model):
        # type: (GenericDisk) -> Disk
        """
        Models a disk
        :param generic_disk_model: The generic modeled disk (returned by Disktools)
        :type generic_disk_model: GenericDisk
        :return: The newly modeled disk
        :rtype: Disk
        """
        cls._logger.info('Disk {0} - Creating disk - {1}'.format(generic_disk_model.name, generic_disk_model.__dict__))
        disk = Disk()
        disk.name = generic_disk_model.name
        cls._update_disk(disk, generic_disk_model)
        return disk

    @staticmethod
    def _update_disk(modeled_disk, generic_disk_model):
        # type: (Disk, GenericDisk) -> None
        """
        Updates a disk
        Copies all properties from the generic modeled disk to the own model
        :param modeled_disk: The modeled disk
        :type modeled_disk: Disk
        :param generic_disk_model: The generic modeled disk (returned by Disktools)
        :type generic_disk_model: GenericDisk
        :return: None
        :rtype NoneType
        """
        for prop in ['state', 'aliases', 'is_ssd', 'model', 'size', 'name', 'serial', 'partitions']:
            if hasattr(generic_disk_model, prop):
                if prop == 'partitions':
                    # Update partition info
                    partitions_as_dicts = [partition.__dict__ for partition in generic_disk_model.partitions]
                    modeled_disk.partitions = partitions_as_dicts
                else:
                    setattr(modeled_disk, prop, getattr(generic_disk_model, prop))
        modeled_disk.save()

    @classmethod
    def _prepare_for_name_switch(cls, generic_disks):
        # type: (List[GenericDisk]) -> None
        """
        This manager has a unique constraint on the disk name
        It could happen that a disk switched drive letter.
        To avoid any issues while syncing the disk, the name is temporarily changed
        :param generic_disks: List of the disks currently found by the system
        :type generic_disks: list
        :return: None
        :rtype: NoneType
        """
        # Check names to avoid a unique constraint exception
        for generic_disk in generic_disks:  # type: GenericDisk
            if len(generic_disk.aliases) >= 1:
                disk_alias = generic_disk.aliases[0]
                try:
                    disk = DiskList.get_by_alias(disk_alias)
                    if generic_disk.name != generic_disk.name:
                        cls._logger.info('Disk with alias {0} its name has changed from {1} to {2},'
                                         ' changing disk names to circumvent unique constraints'.format(disk_alias, disk.name, generic_disk.name))
                        disk.name = str(uuid.uuid4())
                        disk.save()
                except ObjectNotFoundException:
                    # No disk with such an alias. Will be caught later in the sync disk by adding the left-over models
                    pass

    @classmethod
    def prepare_disk(cls, disk):
        """
        Prepare a disk for use with ALBA
        :param disk: Disk object to prepare
        :type disk: source.dal.objects.disk.Disk
        :return: None
        """
        if disk.usable is False:
            raise RuntimeError('Cannot prepare disk {0}'.format(disk.name))
        cls._logger.info('Preparing disk {0}'.format(disk.name))

        # Create partition
        mountpoint = '/mnt/alba-asd/{0}'.format(''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16)))
        alias = disk.aliases[0]
        cls._locate(device_alias=alias, start=False)
        cls._local_client.run(['umount', disk.mountpoint], allow_nonzero=True)
        cls._local_client.run(['parted', alias, '-s', 'mklabel', 'gpt'])
        cls._local_client.run(['parted', alias, '-s', 'mkpart', alias.split('/')[-1], '2MB', '100%'])
        cls._local_client.run(['udevadm', 'settle'])  # Waits for all udev rules to have finished

        # Wait for partition to be ready by attempting to add filesystem
        counter = 0
        already_mounted = False
        while True:
            disk = Disk(disk.id)
            if len(disk.partitions) == 1:
                try:
                    cls._local_client.run(['mkfs.xfs', '-qf', disk.partition_aliases[0]])
                    break
                except CalledProcessError:
                    mountpoint = disk.mountpoint
                    if mountpoint and mountpoint in cls._local_client.run(['mount']):
                        # Some OSes have auto-mount functionality making mkfs.xfs to fail when the mountpoint has already been mounted
                        # This can occur when the exact same partition gets created on the device
                        already_mounted = True
                        if mountpoint.startswith('/mnt/alba-asd'):
                            cls._local_client.run('rm -rf {0}/*'.format(mountpoint), allow_insecure=True)
                        cls._logger.warning('Device has already been used by ALBA, re-using mountpoint {0}'.format(mountpoint))
                        break
            cls._logger.info('Partition for disk {0} not ready yet'.format(disk.name))
            cls.sync_disks()
            time.sleep(0.2)
            counter += 1
            if counter > 10:
                raise RuntimeError('Partition for disk {0} not ready in 2 seconds'.format(disk.name))

        # Create mountpoint and mount
        cls._local_client.run(['mkdir', '-p', mountpoint])
        FSTab.add(partition_aliases=[disk.partition_aliases[0]], mountpoint=mountpoint)
        if already_mounted is False:
            cls._local_client.run(['mount', mountpoint])
        cls.sync_disks()
        cls._local_client.run(['chown', '-R', 'alba:alba', mountpoint])
        cls._logger.info('Prepare disk {0} complete'.format(disk.name))

    @classmethod
    def clean_disk(cls, disk):
        """
        Removes the given disk
        :param disk: Disk object to clean
        :type disk: source.dal.objects.disk.Disk
        :return: None
        """
        if disk.usable is False:
            raise RuntimeError('Cannot clean disk {0}'.format(disk.name))
        cls._logger.info('Cleaning disk {0}'.format(disk.name))

        FSTab.remove(disk.partition_aliases)
        if disk.mountpoint is not None:
            umount_cmd = ['umount', disk.mountpoint]
            try:
                cls._local_client.run(umount_cmd)
                cls._local_client.dir_delete(disk.mountpoint)
            except Exception:
                cls._logger.exception('Failure to umount or delete the mountpoint')
                raise
        try:
            cls._local_client.run(['parted', disk.aliases[0], '-s', 'mklabel', 'gpt'])
        except CalledProcessError:
            # Wiping the partition is a nice-to-have and might fail when a disk is e.g. unavailable
            pass
        cls.sync_disks()
        cls._locate(device_alias=disk.aliases[0], start=True)
        cls._logger.info('Clean disk {0} complete'.format(disk.name))

    @classmethod
    def remount_disk(cls, disk):
        """
        Remount the disk
        :param disk: Disk object to remount
        :type disk: source.dal.objects.disk.Disk
        :return: None
        """
        if disk.usable is False:
            raise RuntimeError('Cannot remount disk {0}'.format(disk.name))

        cls._logger.info('Remounting disk {0}'.format(disk.name))
        cls._local_client.run(['umount', '-l', disk.mountpoint], timeout=10, allow_nonzero=True)
        cls._local_client.run(['mount', disk.mountpoint], timeout=10, allow_nonzero=True)
        cls._logger.info('Remounting disk {0} complete'.format(disk.name))

    @classmethod
    def scan_controllers(cls):
        """
        Scan the disk controller(s)
        :return: None
        """
        cls._logger.info('Scanning controllers')
        controllers = {}
        has_storecli = cls._local_client.run(['which', 'storcli64'], allow_nonzero=True).strip() != ''
        if has_storecli is True:
            controller_info = json.loads(cls._local_client.run(['storcli64', '/call/eall/sall', 'show', 'all', 'J']))
            for controller in controller_info['Controllers']:
                if controller['Command Status']['Status'] == 'Failure':
                    continue
                data = controller['Response Data']
                drive_locations = set(drive.split(' ')[1] for drive in data.keys())
                for location in drive_locations:
                    if data['Drive {0}'.format(location)][0]['State'] == 'JBOD':
                        wwn = data['Drive {0} - Detailed Information'.format(location)]['Drive {0} Device attributes'.format(location)]['WWN']
                        controllers[wwn] = ('storcli64', location)
        cls.controllers = controllers
        cls._logger.info('Scan complete')

    @classmethod
    def _locate(cls, device_alias, start):
        """
        Locate the disk on the controller
        :param device_alias: Alias for the device  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0' or 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type device_alias: str
        :param start: True to start locating, False otherwise
        :type start: bool
        :return: None
        """
        if cls.controllers == {}:
            cls.scan_controllers()
        for wwn in cls.controllers:
            if device_alias and device_alias.endswith(wwn):
                controller_type, location = cls.controllers[wwn]
                if controller_type == 'storcli64':
                    cls._logger.info('Location {0} for {1}'.format('start' if start is True else 'stop', location))
                    cls._local_client.run(['storcli64', location, 'start' if start is True else 'stop', 'locate'])
