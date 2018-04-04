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

import re
import json
import time
import uuid
import random
import string
from subprocess import CalledProcessError
from ovs_extensions.dal.base import ObjectNotFoundException
from ovs_extensions.generic.sshclient import SSHClient
from source.dal.lists.disklist import DiskList
from source.dal.objects.disk import Disk
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
    def _select_alias_by_id(aliases):
        # type: (List[str]) -> str
        """
        Find and return the alias with the by-id identifier
        :param aliases: List of aliases
        :return: The partition alias with the by-id identifier
        :rtype: str
        """
        aliases_filtered = [alias for alias in aliases if alias.startswith('/dev/disk/by-id/')]
        if len(aliases_filtered) == 0:
            raise ValueError('No alias with \'by-id\' identifier')
        return aliases_filtered[0]

    @staticmethod
    def sync_disks():
        # type: () -> None
        """
        Syncs the disks
        Changes made to this code should be reflected in the framework DiskController.sync_with_reality call.
        """
        # Retrieve all symlinks for all devices
        # Example of name_alias_mapping:
        # {'/dev/md0': ['/dev/disk/by-id/md-uuid-ad2de634:26d97253:5eda0a23:96986b76', '/dev/disk/by-id/md-name-OVS-1:0'],
        #  '/dev/sda': ['/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c295fe2ff771-lun-0'],
        #  '/dev/sda1': ['/dev/disk/by-uuid/e3e0bc62-4edc-4c6b-a6ce-1f39e8f27e41', '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c295fe2ff771-lun-0-part1']}
        name_alias_mapping = {}
        alias_name_mapping = {}
        for path_type in DiskController._local_client.dir_list(directory='/dev/disk'):
            if path_type in ['by-uuid', 'by-partuuid']:  # UUIDs can change after creating a filesystem on a partition
                continue
            directory = '/dev/disk/{0}'.format(path_type)
            for symlink in DiskController._local_client.dir_list(directory=directory):
                symlink_path = '{0}/{1}'.format(directory, symlink)
                link = DiskController._local_client.file_read_link(path=symlink_path)
                if link not in name_alias_mapping:
                    name_alias_mapping[link] = []
                name_alias_mapping[link].append(symlink_path)
                alias_name_mapping[symlink_path] = link

        # Parse 'lsblk' output
        # --exclude 1 for RAM devices, 2 for floppy devices, 11 for CD-ROM devices, 43 for nbd devices (See https://www.kernel.org/doc/html/v4.15/admin-guide/devices.html)
        command = ['lsblk', '--pairs', '--bytes', '--noheadings', '--exclude', '1,2,11,43']
        output = '--output=KNAME,SIZE,MODEL,STATE,MAJ:MIN,FSTYPE,TYPE,ROTA,MOUNTPOINT,LOG-SEC{0}'
        regex = '^KNAME="(?P<name>.*)" SIZE="(?P<size>\d*)" MODEL="(?P<model>.*)" STATE="(?P<state>.*)" MAJ:MIN="(?P<dev_nr>.*)" FSTYPE="(?P<fstype>.*)" TYPE="(?P<type>.*)" ROTA="(?P<rota>[0,1])" MOUNTPOINT="(?P<mtpt>.*)" LOG-SEC="(?P<sector_size>\d*)"( SERIAL="(?P<serial>.*)")?$'
        DiskController._logger.info(command + [output.format(',SERIAL')])
        try:
            devices = DiskController._local_client.run(command + [output.format(',SERIAL')]).splitlines()
        except Exception:
            devices = DiskController._local_client.run(command + [output.format('')]).splitlines()
        device_regex = re.compile(regex)
        configuration = {}
        parsed_devices = []
        DiskController._logger.info('Starting to iterate over disks')
        for device in devices:
            match = re.match(device_regex, device)
            if match is None:
                DiskController._logger.error('Device regex did not match for {0}. Please investigate'.format(device))
                raise Exception('Failed to parse \'lsblk\' output')

            groupdict = match.groupdict()
            name = groupdict['name'].strip()
            size = groupdict['size'].strip()
            model = groupdict['model'].strip()
            state = groupdict['state'].strip()
            dev_nr = groupdict['dev_nr'].strip()
            serial = (groupdict['serial'] or '').strip()
            fs_type = groupdict['fstype'].strip()
            dev_type = groupdict['type'].strip()
            rotational = groupdict['rota'].strip()
            mount_point = groupdict['mtpt'].strip()
            sector_size = groupdict['sector_size'].strip()

            if dev_type == 'rom':
                continue

            link = DiskController._local_client.file_read_link('/sys/block/{0}'.format(name))
            friendly_path = '/dev/{0}'.format(name)
            system_aliases = sorted(name_alias_mapping.get(friendly_path, [friendly_path]))
            device_is_also_partition = False
            device_state = 'OK'
            if link is not None:  # If this returns, it means its a device and not a partition
                device_is_also_partition = mount_point != ''  # LVM, RAID1, ... have the tendency to be a device with a partition on it, but the partition is not reported by 'lsblk'
                device_state = 'OK' if state == 'running' or dev_nr.split(':')[0] != '8' else 'FAILURE'
                parsed_devices.append({'name': name,
                                       'state': device_state})
                configuration[name] = {'name': name,
                                       'size': int(size),
                                       'state': device_state,
                                       'model': model if model != '' else None,
                                       'serial': serial if serial != '' else None,
                                       'is_ssd': rotational == '0',
                                       'aliases': system_aliases,
                                       'partitions': []}
            if link is None or device_is_also_partition is True:
                current_device = None
                current_device_state = None
                if device_is_also_partition is True:
                    offset = 0
                    current_device = name
                    current_device_state = device_state
                else:
                    offset = 0
                    for device_info in reversed(parsed_devices):
                        try:
                            current_device = device_info['name']
                            current_device_state = device_info['state']
                            offset = int(DiskController._local_client.file_read('/sys/block/{0}/{1}/start'.format(current_device, name))) * int(sector_size)
                            break
                        except Exception:
                            pass
                if current_device is None:
                    raise RuntimeError('Failed to retrieve the device information for current partition')
                mount_point = mount_point if mount_point != '' else None
                partition_state = 'OK' if current_device_state == 'OK' else 'FAILURE'
                if mount_point is not None and fs_type != 'swap':
                    try:
                        filename = '{0}/{1}'.format(mount_point, str(time.time()))
                        DiskController._local_client.run(['touch', filename])
                        DiskController._local_client.run(['rm', filename])
                    except Exception:
                        partition_state = 'FAILURE'

                configuration[current_device]['partitions'].append({'size': int(size),
                                                                    'state': partition_state,
                                                                    'offset': offset,
                                                                    'aliases': system_aliases,
                                                                    'filesystem': fs_type if fs_type != '' else None,
                                                                    'mountpoint': mount_point})

        # Check names to avoid a unique constraint exception
        for disk_name, disk_info in configuration.iteritems():
            if len(disk_info['aliases']) >= 1:
                try:
                    disk = DiskList.get_by_alias(disk_info['aliases'][0])
                    if disk_name != disk.name:
                        DiskController._logger.info('Disk with alias{0} its name has changed from {1} to {2}, \
                        changing disk names to circumvent unique constraints'.format(disk_info['aliases'][0], disk_name, disk.name))
                        disk.name = str(uuid.uuid4())
                        disk.save()
                except ObjectNotFoundException:
                    pass
        # Sync the model
        DiskController._logger.info('Starting to sync disks')
        for disk in DiskList.get_disks():
            DiskController._logger.info('Syncing disk {0}'.format(disk.name))
            disk_info = None
            for alias in disk.aliases:
                if alias in alias_name_mapping:
                    name = alias_name_mapping[alias].replace('/dev/', '')
                    if name in configuration:
                        disk_info = configuration.pop(name)
                        break

            if disk_info is None and disk.name in configuration and (disk.name.startswith('fio') or
                                                                     disk.name.startswith('loop') or
                                                                     disk.name.startswith('nvme')):  # Partitioned loop, nvme devices no longer show up in alias_name_mapping
                disk_info = configuration.pop(disk.name)

            # Remove disk / partitions if not reported by 'lsblk'
            if disk_info is None:
                DiskController._logger.info('Disk {0} - No longer found'.format(disk.name))
                if len(disk.asds) == 0:
                    disk.delete()
                    DiskController._logger.info('Disk {0} - Deleted (no ASDs)'.format(disk.name))
                else:
                    if disk.state != 'MISSING':
                        for partition in disk.partitions:
                            DiskController._logger.warning('Disk {0} - Partition with offset {1} - Updated status to MISSING'.format(disk.name, partition['offset']))
                        DiskController._update_disk(disk, {'state': 'MISSING'})
                        DiskController._logger.warning('Disk {0} - Updated status to MISSING'.format(disk.name))

            else:  # Update existing disks and their partitions
                DiskController._update_disk(disk, disk_info)
        # Create all disks and their partitions not yet modeled
        DiskController._logger.info('Creating disks if necessary')
        for disk_name in configuration:
            DiskController._logger.info('Disk {0} - Creating disk - {1}'.format(disk_name, configuration[disk_name]))
            disk = Disk()
            disk.name = disk_name
            DiskController._update_disk(disk, configuration[disk_name])

    @staticmethod
    def _update_disk(disk, container):
        """
        Updates a disk
        """
        for prop in ['state', 'aliases', 'is_ssd', 'model', 'size', 'name', 'serial', 'partitions']:
            if prop in container:
                setattr(disk, prop, container[prop])
        disk.save()

    @staticmethod
    def prepare_disk(disk, disk_config=None):
        """
        Prepare a disk for use with ALBA
        :param disk: Disk object to prepare
        :type disk: source.dal.objects.disk.Disk
        :param disk_config: Configuration of the disk. When None: actively prepare the disk else only the fstab entries are made
        This is a part of the Dual Controller feature to have high-available ASDs
        :type disk_config: dict
        :return: None
        """
        if disk.usable is False:
            raise RuntimeError('Cannot prepare disk {0}'.format(disk.name))

        DiskController._logger.info('Preparing disk {0}'.format(disk.name))
        active_prepare = disk_config is None
        already_mounted = False

        if active_prepare is True:
            # Create partition
            mountpoint = '/mnt/alba-asd/{0}'.format(''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16)))
            alias = DiskController._select_alias_by_id(disk.aliases)
            DiskController._locate(device_alias=alias, start=False)
            DiskController._local_client.run(['umount', disk.mountpoint], allow_nonzero=True)
            DiskController._local_client.run(['parted', alias, '-s', 'mklabel', 'gpt'])
            DiskController._local_client.run(['parted', alias, '-s', 'mkpart', alias.split('/')[-1], '2MB', '100%'])
            DiskController._local_client.run(['udevadm', 'settle'])  # Waits for all udev rules to have finished

            # Wait for partition to be ready by attempting to add filesystem
            counter = 0
            already_mounted = False
            while True:
                disk = Disk(disk.id)
                if len(disk.partitions) == 1:
                    try:
                        DiskController._local_client.run(['mkfs.xfs', '-qf', DiskController._select_alias_by_id(disk.partition_aliases)])
                        break
                    except CalledProcessError:
                        mountpoint = disk.mountpoint
                        if mountpoint and mountpoint in DiskController._local_client.run(['mount']):
                            # Some OSes have auto-mount functionality making mkfs.xfs to fail when the mountpoint has already been mounted
                            # This can occur when the exact same partition gets created on the device
                            already_mounted = True
                            if mountpoint.startswith('/mnt/alba-asd'):
                                DiskController._local_client.run('rm -rf {0}/*'.format(mountpoint), allow_insecure=True)
                            DiskController._logger.warning('Device has already been used by ALBA, re-using mountpoint {0}'.format(mountpoint))
                            break
                DiskController._logger.info('Partition for disk {0} not ready yet'.format(disk.name))
                DiskController.sync_disks()
                time.sleep(0.2)
                counter += 1
                if counter > 10:
                    raise RuntimeError('Partition for disk {0} not ready in 2 seconds'.format(disk.name))
        else:
            # Syncing should provide all information as the same hardware is accessed
            DiskController.sync_disks()
            # @todo what if the disk is not mounted on the active side
            mountpoint = disk.mountpoint
            if mountpoint != disk_config['mountpoint']:
                raise ValueError('Passive side might have the wrong disk. Found disk mountpoint ({0}) differs from the requested mountpoint ({1})'
                                 .format(mountpoint, disk_config['mountpoint']))
        # Create mountpoint and mount
        DiskController._local_client.run(['mkdir', '-p', mountpoint])
        DiskController._local_client.run(['chown', '-R', 'alba:alba', mountpoint])
        # Dual Controller feature does not require the 'nofail' and 'noauto' entry
        # An FSTAB entry is required for both active and passive side
        FSTab.add(partition_aliases=[DiskController._select_alias_by_id(disk.partition_aliases)], mountpoint=mountpoint, no_fail=False, no_auto=True)
        if active_prepare is True:
            if already_mounted is False:
                DiskController.mount(mountpoint=mountpoint)
        DiskController._logger.info('Prepare disk {0} complete'.format(disk.name))

    @staticmethod
    def mount(disk=None, mountpoint=None):
        # type: (Optional[Disk], Optional[str]) -> None
        """
        Mounts the given disk or mountpoint
        :param disk: Disk object to mount
        :type disk: source.dal.object.disk.Disk
        :raises Exception: when the mounting went wrong
        :raises ValueError: when both arguments were not passed
        :raises EnvironmentError: when a disk/mountpoint is provided that is not registered in FStab by the ASD manager
        :return: None
        :rtype: NoneType
        """
        if all(x is None for x in [disk, mountpoint]):
            raise ValueError('Either a disk or a mountpoint must be passed')
        DiskController.sync_disks()  # Fetch the latest disk state
        mountpoint_by_alias = FSTab.read()
        if disk is not None:
            if len(disk.partition_aliases) == 0:
                raise ValueError('Disk {0} has no partitions. Cannot mount'.format(disk.name))
            # Use the alias of the partition. The entry should be in FSTab
            alias = DiskController._select_alias_by_id(disk.partition_aliases)
            mountpoint_by_alias = FSTab.read()
            mountpoint = mountpoint_by_alias.get(alias)
            log = 'Disk {0} with partition alias {1} and potential mount on {2} {{0}}'.format(disk.name, alias, mountpoint)
        else:
            # Check if present in FSTab
            log = 'Mountpoint {0} {{0}}'.format(mountpoint)
        try:
            if mountpoint not in mountpoint_by_alias.values():
                raise EnvironmentError(log.format('- Unable to determine where to mount. Entry not found in FSTab under ASD section'))
            if mountpoint and mountpoint in DiskController._local_client.run(['mount']):
                DiskController._logger.info(log.format('already mounted'))
                return  # Already mounted
            DiskController._local_client.run(['mount', mountpoint])
            DiskController.sync_disks()
        except Exception:
            DiskController._logger.exception(log.format('errorred'))
            raise

    @staticmethod
    def unmount(disk=None, mountpoint=None):
        # type: (Optional[Disk], Optional[str]) -> None
        """
        Unmounts the given disk or mountpoint
        :param disk: Disk object to mount
        :type disk: source.dal.object.disk.Disk
        :raises Exception: when the mounting went wrong
        :raises ValueError: when both arguments were not passed
        :return: None
        :rtype: NoneType
        """
        if all(x is None for x in [disk, mountpoint]):
            raise ValueError('Either a disk or a mountpoint must be passed')
        if disk is not None:
            log = 'Disk {0} {{0}} on {1}'.format(disk.name, disk.mountpoint)  # type: str
            mountpoint = disk.mountpoint  # type: str
        else:
            log = 'Mountpoint {0} {{0}}'.format(mountpoint)
        try:
            if mountpoint and mountpoint in DiskController._local_client.run(['mount']):
                DiskController._local_client.run(['umount', mountpoint])
                DiskController.sync_disks()
                return
            DiskController._logger.info(log.format('is not mounted on'))
        except Exception:
            DiskController._logger.exception(log.format('errorred'))
            raise

    @staticmethod
    def clean_disk(disk):
        """
        Removes the given disk
        :param disk: Disk object to clean
        :type disk: source.dal.objects.disk.Disk
        :return: None
        """
        if disk.usable is False:
            raise RuntimeError('Cannot clean disk {0}'.format(disk.name))
        DiskController._logger.info('Cleaning disk {0}'.format(disk.name))

        FSTab.remove(disk.partition_aliases)
        if disk.mountpoint is not None:
            try:
                DiskController.unmount(disk=disk)
                DiskController._local_client.dir_delete(disk.mountpoint)
            except Exception:
                DiskController._logger.exception('Failure to umount or delete the mountpoint')
                raise
        try:
            DiskController._local_client.run(['parted', disk.aliases[0], '-s', 'mklabel', 'gpt'])
        except CalledProcessError:
            # Wiping the partition is a nice-to-have and might fail when a disk is e.g. unavailable
            pass
        DiskController.sync_disks()
        DiskController._locate(device_alias=disk.aliases[0], start=True)
        DiskController._logger.info('Clean disk {0} complete'.format(disk.name))

    @staticmethod
    def remount_disk(disk):
        """
        Remount the disk
        :param disk: Disk object to remount
        :type disk: source.dal.objects.disk.Disk
        :return: None
        """

        if disk.usable is False:
            raise RuntimeError('Cannot remount disk {0}'.format(disk.name))

        DiskController._logger.info('Remounting disk {0}'.format(disk.name))
        DiskController._local_client.run(['umount', '-l', disk.mountpoint], timeout=10, allow_nonzero=True)
        DiskController._local_client.run(['mount', disk.mountpoint], timeout=10, allow_nonzero=True)
        DiskController._logger.info('Remounting disk {0} complete'.format(disk.name))

    @staticmethod
    def scan_controllers():
        """
        Scan the disk controller(s)
        :return: None
        """
        DiskController._logger.info('Scanning controllers')
        controllers = {}
        has_storecli = DiskController._local_client.run(['which', 'storcli64'], allow_nonzero=True).strip() != ''
        if has_storecli is True:
            controller_info = json.loads(DiskController._local_client.run(['storcli64', '/call/eall/sall', 'show', 'all', 'J']))
            for controller in controller_info['Controllers']:
                if controller['Command Status']['Status'] == 'Failure':
                    continue
                data = controller['Response Data']
                drive_locations = set(drive.split(' ')[1] for drive in data.keys())
                for location in drive_locations:
                    if data['Drive {0}'.format(location)][0]['State'] == 'JBOD':
                        wwn = data['Drive {0} - Detailed Information'.format(location)]['Drive {0} Device attributes'.format(location)]['WWN']
                        controllers[wwn] = ('storcli64', location)
        DiskController.controllers = controllers
        DiskController._logger.info('Scan complete')

    @staticmethod
    def _locate(device_alias, start):
        """
        Locate the disk on the controller
        :param device_alias: Alias for the device  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0' or 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type device_alias: str
        :param start: True to start locating, False otherwise
        :type start: bool
        :return: None
        """
        if DiskController.controllers == {}:
            DiskController.scan_controllers()
        for wwn in DiskController.controllers:
            if device_alias and device_alias.endswith(wwn):
                controller_type, location = DiskController.controllers[wwn]
                if controller_type == 'storcli64':
                    DiskController._logger.info('Location {0} for {1}'.format('start' if start is True else 'stop', location))
                    DiskController._local_client.run(['storcli64', location, 'start' if start is True else 'stop', 'locate'])
