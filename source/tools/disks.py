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
Disk related code
"""
import re
import json
import time
import os
import random
import string
from subprocess import check_output, CalledProcessError
from source.tools.fstab import FSTab


class Disks(object):
    """
    Disk helper methods
    """

    controllers = {}

    @staticmethod
    def list_disks():
        """
        List the disks
        :return: Information about the disks
        """
        disks = {}

        # Find used disks
        # 1. Mounted disks
        all_mounts = check_output('mount', shell=True).splitlines()
        all_mounted_disks = []
        used_disks = []
        for mount in all_mounts:
            mount = mount.strip()
            match = re.search('/dev/(.+?) on (/.*?) type.*', mount)
            if match is not None:
                all_mounted_disks.append(match.groups()[0])
                if not match.groups()[1].startswith('/mnt/alba-asd/'):
                    used_disks.append(match.groups()[0])

        # 2. Disks used in a software raid
        mdstat = check_output('cat /proc/mdstat', shell=True)
        for md_match in re.findall('([a-z]+\d+ : (in)?active raid\d+(( [a-z]+\d?\[\d+\])+))', mdstat):
            for disk_match in re.findall('( ([a-z]+\d?)\[\d+\])', md_match[2]):
                used_disks.append(disk_match[1].strip())

        # Find all disks
        all_disks = check_output('ls -al /dev/disk/by-id/', shell=True).split('\n')
        for disk in all_disks:
            disk = disk.strip()
            match = re.search('.+?(((scsi-)|(ata-)|(virtio-)).+?) -> ../../([sv]d.+)', disk)
            if match is not None:
                disk_id, disk_name = match.groups()[0], match.groups()[-1]
                if disk_name in all_mounted_disks:
                    all_mounted_disks.remove(disk_name)
                    all_mounted_disks.append(disk_id.replace('-part1', ''))
                if re.search('-part\d+', disk_id) is None:
                    if not any(used_disk for used_disk in used_disks if disk_name in used_disk):
                        disks[disk_id] = {'device': '/dev/disk/by-id/{0}'.format(disk_id),
                                          'available': True,
                                          'state': {'state': 'ok'}}

        # Load information about mount configuration (detect whether the disks are configured)
        fstab_disks = FSTab.read()
        for device in fstab_disks.keys():
            for disk_id in disks:
                if disks[disk_id]['device'] == '/dev/disk/by-id/{0}'.format(device):
                    disks[disk_id].update({'available': False,
                                           'mountpoint': fstab_disks[device]})
                    del fstab_disks[device]
        for device in fstab_disks.keys():
            disks[device] = {'device': '/dev/disk/by-id/{0}'.format(device),
                             'available': False,
                             'mountpoint': fstab_disks[device],
                             'state': {'state': 'error',
                                       'detail': 'missing'}}

        # Locate unmounted disks
        for disk_id in disks:
            if disks[disk_id]['state']['state'] == 'ok' and disk_id not in all_mounted_disks:
                disks[disk_id]['state'] = {'state': 'error',
                                           'detail': 'ioerror'}

        # Load statistical information about the disk
        df_info = check_output('df -k /mnt/alba-asd/* || true', shell=True).strip().split('\n')
        for disk_id in disks:
            if disks[disk_id]['state']['state'] == 'ok':
                for df in df_info:
                    match = re.search('\S+?\s+?(\d+?)\s+?(\d+?)\s+?(\d+?)\s.+?/mnt/alba-asd/', df)
                    if match is not None:
                        disks[disk_id].update({'usage': {'size': int(match.groups()[0]) * 1024,
                                                         'used': int(match.groups()[1]) * 1024,
                                                         'available': int(match.groups()[2]) * 1024}})

        # Execute some checkups on the disks
        for disk_id in disks:
            if disks[disk_id]['available'] is False and disks[disk_id]['state']['state'] == 'ok':
                output = check_output('ls {0}/ 2>&1 || true'.format(disks[disk_id]['mountpoint']), shell=True)
                if 'Input/output error' in output:
                    disks[disk_id]['state'] = {'state': 'error',
                                               'detail': 'ioerror'}

        return disks

    @staticmethod
    def prepare_disk(disk):
        """
        Prepare a disk for use with ALBA
        :param disk: Disk ID
        :return: None
        """
        print 'Preparing disk {0}'.format(disk)
        mountpoint = '/mnt/alba-asd/{0}'.format(''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16)))
        disk_by_id = '/dev/disk/by-id/{0}'.format(disk)
        Disks.locate(disk, start=False)
        check_output('umount {0} || true'.format(mountpoint), shell=True)
        check_output('parted {0} -s mklabel gpt'.format(disk_by_id), shell=True)
        check_output('parted {0} -s mkpart {1} 2MB 100%'.format(disk_by_id, disk), shell=True)
        check_output('partprobe {0}'.format(disk_by_id), shell=True)
        counter = 0
        partition_name = '{0}-part1'.format(disk_by_id)
        while not os.path.exists(partition_name):
            print('Partition {0} not ready yet'.format(partition_name))
            time.sleep(0.2)
            counter += 1
            if counter > 10:
                raise RuntimeError('Partition {0} not ready in 2 seconds'.format(partition_name))
        check_output('mkfs.xfs -qf {0}-part1'.format(disk_by_id), shell=True)
        check_output('mkdir -p {0}'.format(mountpoint), shell=True)
        FSTab.add('{0}-part1'.format(disk_by_id), mountpoint)
        check_output('mount {0}'.format(mountpoint), shell=True)
        check_output('chown -R alba:alba {0}'.format(mountpoint), shell=True)
        print 'Prepare disk {0} complete'.format(disk)

    @staticmethod
    def clean_disk(disk):
        """
        Remove the disk
        :param disk: Disk ID
        :return: None
        """
        print 'Cleaning disk {0}'.format(disk)
        mountpoints = FSTab.read()
        mountpoint = mountpoints[disk]
        FSTab.remove('/dev/disk/by-id/{0}-part1'.format(disk))
        check_output('umount {0} || true'.format(mountpoint), shell=True)
        check_output('rm -rf {0} || true'.format(mountpoint), shell=True)
        try:
            check_output('parted /dev/disk/by-id/{0} -s mklabel gpt'.format(disk), shell=True)
        except CalledProcessError:
            # Wiping the partition is a nice-to-have and might fail when a disk is e.g. unavailable
            pass
        Disks.locate(disk, start=True)
        print 'Clean disk {0} complete'.format(disk)

    @staticmethod
    def remount_disk(disk):
        """
        Remount the disk
        :param disk: Disk ID
        :return: None
        """
        print 'Remounting disk {0}'.format(disk)
        mountpoints = FSTab.read()
        mountpoint = mountpoints[disk]
        check_output('umount {0} || true'.format(mountpoint), shell=True)
        check_output('mount {0} || true'.format(mountpoint), shell=True)
        print 'Remounting disk {0} complete'.format(disk)

    @staticmethod
    def scan_controllers():
        """
        Scan the disk controller(s)
        :return: None
        """
        print 'Scanning controllers'
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
        Disks.controllers = controllers
        print 'Scan complete'

    @staticmethod
    def locate(disk, start):
        """
        Locate the disk on the controller
        :param disk: Disk ID
        :param start: True to start locating, False otherwise
        :return: None
        """
        for wwn in Disks.controllers:
            if disk.endswith(wwn):
                controller_type, location = Disks.controllers[wwn]
                if controller_type == 'storcli64':
                    print 'Location {0} for {1}'.format('start' if start is True else 'stop', location)
                    check_output('storcli64 {0} {1} locate'.format(location, 'start' if start is True else 'stop'), shell=True)
