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
import os
import re
import json
import time
import random
import string
from subprocess import check_output, CalledProcessError
from source.tools.fstab import FSTab
from source.tools.localclient import LocalClient
from source.tools.log_handler import LogHandler


class DiskController(object):
    """
    Disk helper methods
    """
    NODE_ID = os.environ['ASD_NODE_ID']

    controllers = {}
    _local_client = LocalClient()
    _logger = LogHandler.get('asd-manager', name='disk')

    @staticmethod
    def list_disks():
        """
        List the disks
        CHANGES MADE TO THIS CODE SHOULD BE REFLECTED IN THE FRAMEWORK sync_with_reality CALL TOO!!!!!!!!!!!!!!!!!!!!

        :return: Information about the disks
        :rtype: dict
        """
        # Retrieve all symlinks for all devices
        # Example of name_alias_mapping:
        # {'/dev/md0': ['/dev/disk/by-id/md-uuid-ad2de634:26d97253:5eda0a23:96986b76', '/dev/disk/by-id/md-name-OVS-1:0'],
        #  '/dev/sda': ['/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c295fe2ff771-lun-0'],
        #  '/dev/sda1': ['/dev/disk/by-uuid/e3e0bc62-4edc-4c6b-a6ce-1f39e8f27e41', '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c295fe2ff771-lun-0-part1']}
        name_alias_mapping = {}
        alias_name_mapping = {}
        partition_device_map = {}
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
        # --exclude 1 for RAM devices, 2 for floppy devices, 11 for CD-ROM devices (See https://www.kernel.org/doc/Documentation/devices.txt)
        devices = DiskController._local_client.run(command='lsblk --pairs --bytes --noheadings --exclude 1,2,11 --output=KNAME,FSTYPE,TYPE,MOUNTPOINT').splitlines()
        device_regex = re.compile('^KNAME="(?P<name>.*)" FSTYPE="(?P<fstype>.*)" TYPE="(?P<type>.*)" MOUNTPOINT="(?P<mtpt>.*)"$')
        configuration = {}
        parsed_devices = []
        for device in devices:
            match = re.match(device_regex, device)
            if match is None:
                DiskController._logger.error('Device regex did not match for {0}. Please investigate'.format(device))
                raise Exception('Failed to parse \'lsblk\' output')

            groupdict = match.groupdict()
            name = groupdict['name'].strip()
            fs_type = groupdict['fstype'].strip()
            dev_type = groupdict['type'].strip()
            mount_point = groupdict['mtpt'].strip()

            if dev_type == 'rom':
                continue

            link = DiskController._local_client.file_read_link(path='/sys/block/{0}'.format(name))
            friendly_path = '/dev/{0}'.format(name)
            system_aliases = sorted(name_alias_mapping.get(friendly_path, [friendly_path]))
            device_is_also_partition = False
            if link is not None:  # If this returns, it means its a device and not a partition
                DiskController._logger.info('Investigating device {0}'.format(friendly_path))
                device_is_also_partition = mount_point != ''  # LVM, RAID1, ... have the tendency to be a device with a partition on it, but the partition is not reported by 'lsblk'
                parsed_devices.append(name)
                configuration[name] = {'name': name,
                                       'aliases': system_aliases,
                                       'partitions': []}
            if link is None or device_is_also_partition is True:
                DiskController._logger.info('Investigating partition {0}'.format(friendly_path))
                current_device = None
                if device_is_also_partition is True:
                    current_device = name
                else:
                    for device_name in reversed(parsed_devices):
                        try:
                            current_device = device_name
                            DiskController._local_client.file_read(filename='/sys/block/{0}/{1}/start'.format(current_device, name))
                            break
                        except Exception:
                            pass
                if current_device is None:
                    raise RuntimeError('Failed to retrieve the device information for current partition')
                mount_point = mount_point if mount_point != '' else None
                partition_device_map[friendly_path] = current_device
                configuration[current_device]['partitions'].append({'aliases': system_aliases,
                                                                    'filesystem': fs_type if fs_type != '' else None,
                                                                    'mountpoint': mount_point})

        # Parse 'configuration' to see which devices can be used as ASD
        disks = {}
        for device_name, device_info in configuration.iteritems():
            availability = True
            usable_device = True
            partition_mtpt = None
            partition_aliases = []
            for partition in device_info['partitions']:
                partition_mtpt = partition['mountpoint']
                partition_filesystem = partition['filesystem']
                partition_aliases.extend(partition['aliases'])
                if partition_mtpt is not None:
                    if partition_mtpt.startswith('/mnt/alba-asd/'):
                        availability = False
                    else:
                        usable_device = False
                    break

                if partition_filesystem in ['swap', 'linux_raid_member', 'LVM2_member']:
                    usable_device = False
                    break

            if usable_device is True:
                usage = {}
                state = 'ok'
                state_detail = ''
                if availability is False:
                    # Check partition usage information
                    df_info = check_output('df -B 1 --output=size,used,avail {0} | tail -1 || true'.format(partition_mtpt), shell=True).strip().splitlines()
                    if len(df_info) != 1:
                        DiskController._logger.warning('Verifying usage information for mountpoint {0} failed. Information retrieved: {1}'.format(partition_mtpt, df_info))
                        continue
                    size, used, available = df_info[0].split()
                    usage = {'size': int(size),
                             'used': int(used),
                             'available': int(available)}

                    # Check mountpoint validation
                    output = check_output('ls {0}/ 2>&1 || true'.format(partition_mtpt), shell=True)
                    if 'Input/output error' in output:
                        state = 'error'
                        state_detail = 'io_error'
                aliases = device_info['aliases']
                disks[aliases[0]] = {'usage': usage,
                                     'state': state,
                                     'device': '/dev/{0}'.format(device_name),
                                     'aliases': aliases,
                                     'node_id': DiskController.NODE_ID,
                                     'available': availability,
                                     'mountpoint': partition_mtpt,
                                     'state_detail': state_detail,
                                     'partition_amount': len(device_info['partitions']),
                                     'partition_aliases': partition_aliases}

        # Verify FStab entries are present in 'disks'
        fstab_disks = FSTab.read()
        for device_info in disks.itervalues():
            for partition_alias, mountpoint in fstab_disks.items():
                if partition_alias in device_info['partition_aliases']:
                    fstab_disks.pop(partition_alias)

        # Add FSTab entries which are not present in disks as 'missing'
        for partition_alias, mountpoint in fstab_disks.iteritems():
            partition_name = alias_name_mapping.get(partition_alias)
            device_name = partition_device_map.get(partition_name)
            if device_name is not None and device_name in name_alias_mapping:
                aliases = name_alias_mapping[device_name]
                disks[aliases[0]] = {'usage': {},
                                     'state': 'error',
                                     'device': '/dev/{0}'.format(device_name),
                                     'aliases': aliases,
                                     'node_id': DiskController.NODE_ID,
                                     'available': False,
                                     'mountpoint': mountpoint,
                                     'state_detail': 'missing',
                                     'partition_aliases': name_alias_mapping.get(partition_name, [])}
        return disks

    @staticmethod
    def prepare_disk(device_alias):
        """
        Prepare a disk for use with ALBA
        :param device_alias: Alias of the device (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type device_alias: str
        :return: None
        """
        # Create partition
        DiskController._logger.info('Preparing disk {0}'.format(device_alias))
        mountpoint = '/mnt/alba-asd/{0}'.format(''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16)))
        DiskController._locate(device_alias=device_alias, start=False)
        check_output('umount {0} || true'.format(mountpoint), shell=True)
        check_output('parted {0} -s mklabel gpt'.format(device_alias), shell=True)
        check_output('parted {0} -s mkpart {1} 2MB 100%'.format(device_alias, device_alias.split('/')[-1]), shell=True)
        check_output('partprobe {0} || true'.format(device_alias), shell=True)

        # Wait for partition to be ready by attempting to add filesystem
        counter = 0
        partition_aliases = []
        while True:
            disk_info = DiskController.get_disk_data_by_alias(device_alias=device_alias)
            if disk_info.get('partition_amount', 0) == 1:
                partition_aliases = disk_info['partition_aliases']
                try:
                    check_output('mkfs.xfs -qf {0}'.format(partition_aliases[0]), shell=True)
                    break
                except CalledProcessError:
                    pass
            DiskController._logger.info('Partition for disk {0} not ready yet'.format(device_alias))
            time.sleep(0.2)
            counter += 1
            if counter > 10:
                raise RuntimeError('Partition for disk {0} not ready in 2 seconds'.format(device_alias))

        # Create mountpoint and mount
        check_output('mkdir -p {0}'.format(mountpoint), shell=True)
        FSTab.add(partition_aliases=partition_aliases, mountpoint=mountpoint)
        check_output('mount {0}'.format(mountpoint), shell=True)
        check_output('chown -R alba:alba {0}'.format(mountpoint), shell=True)
        DiskController._logger.info('Prepare disk {0} complete'.format(device_alias))

    @staticmethod
    def clean_disk(device_alias, mountpoint):
        """
        Removes the given disk
        :param device_alias: Alias for the device  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type device_alias: str
        :param mountpoint: Mountpoint of the disk
        :type mountpoint: str
        :return: None
        """
        disk_info = DiskController.get_disk_data_by_alias(device_alias=device_alias)
        DiskController._logger.info('Cleaning disk {0}'.format(device_alias))
        FSTab.remove(disk_info['partition_aliases'])

        try:
            check_output('umount {0}'.format(mountpoint), shell=True)
            DiskController._local_client.dir_delete(mountpoint)
        except Exception:
            DiskController._logger.exception('Failure to umount or delete the mountpoint')
            raise
        try:
            check_output('parted {0} -s mklabel gpt'.format(device_alias), shell=True)
        except CalledProcessError:
            # Wiping the partition is a nice-to-have and might fail when a disk is e.g. unavailable
            pass
        DiskController._locate(device_alias=device_alias, start=True)
        DiskController._logger.info('Clean disk {0} complete'.format(device_alias))

    @staticmethod
    def remount_disk(device_alias, mountpoint):
        """
        Remount the disk
        :param device_alias: Alias for the device  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0' or 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type device_alias: str
        :param mountpoint: Mountpoint of the disk
        :type mountpoint: str
        :return: None
        """
        DiskController._logger.info('Remounting disk {0}'.format(device_alias))
        check_output('umount {0} || true'.format(mountpoint), shell=True)
        check_output('mount {0} || true'.format(mountpoint), shell=True)
        DiskController._logger.info('Remounting disk {0} complete'.format(device_alias))

    @staticmethod
    def scan_controllers():
        """
        Scan the disk controller(s)
        :return: None
        """
        DiskController._logger.info('Scanning controllers')
        controllers = {}
        has_storecli = check_output('which storcli64 || true', shell=True).strip() != ''
        if has_storecli is True:
            controller_info = json.loads(check_output('storcli64 /call/eall/sall show all J', shell=True))
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
            if device_alias.endswith(wwn):
                controller_type, location = DiskController.controllers[wwn]
                if controller_type == 'storcli64':
                    DiskController._logger.info('Location {0} for {1}'.format('start' if start is True else 'stop', location))
                    check_output('storcli64 {0} {1} locate'.format(location, 'start' if start is True else 'stop'), shell=True)

    @staticmethod
    def get_disk_data_by_alias(device_alias):
        """
        Retrieve disk information
        :param device_alias: Alias of the device  (eg: '/dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0' or 'pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0')
        :type device_alias: str
        :return: Disk data
        :rtype: dict
        """
        disk_data = None
        all_disks = DiskController.list_disks()
        if not device_alias.startswith('/dev/disk/by-'):
            for disk_info in all_disks.values():
                for alias in disk_info.get('aliases', []):
                    if alias.endswith(device_alias):
                        disk_data = disk_info
                        break
                if disk_data is not None:
                    break
        else:
            disk_data = all_disks.get(device_alias)
            if disk_data is None:  # Crap implementation for FIO devices, once a partition has been created, then the original by-path alias for the device starts pointing to the partition
                for data in all_disks.itervalues():
                    if device_alias in data['partition_aliases']:
                        disk_data = data
                        break
        if disk_data is None:
            raise RuntimeError('Disk with alias {0} not available'.format(device_alias))
        if len(disk_data.get('aliases', [])) == 0:
            raise RuntimeError('No aliases found for device {0}'.format(device_alias))
        return disk_data
