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
import os
import re
import json
import time
import random
import string
import datetime
from subprocess import check_output, CalledProcessError
from source.tools.fstab import FSTab
from source.tools.localclient import LocalClient


class DiskController(object):
    """
    Disk helper methods
    """
    NODE_ID = os.environ['ASD_NODE_ID']
    controllers = {}
    _local_client = LocalClient()

    @staticmethod
    def _log(message):
        print '{0} - {1}'.format(str(datetime.datetime.now()), message)

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
        all_mounted_asds = []
        used_disks = []
        for mount in all_mounts:
            mount = mount.strip()
            match = re.search('/dev/(.+?) on (/.*?) type.*', mount)
            if match is not None:
                if not match.groups()[1].startswith('/mnt/alba-asd/'):
                    used_disks.append(match.groups()[0])
                else:
                    all_mounted_asds.append(match.groups()[0])

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
                if disk_name in all_mounted_asds:
                    all_mounted_asds.remove(disk_name)
                    all_mounted_asds.append(disk_id.replace('-part1', ''))
                if re.search('-part\d+', disk_id) is None:
                    if not any(used_disk for used_disk in used_disks if disk_name in used_disk):
                        disks[disk_id] = {'device': '/dev/disk/by-id/{0}'.format(disk_id),
                                          'available': True,
                                          'state': 'ok'}

        # Load information about mount configuration (detect whether the disks are configured)
        fstab_disks = FSTab.read()
        for device in fstab_disks.keys():
            for disk_id in disks:
                if disk_id == device:
                    disks[disk_id].update({'available': False,
                                           'mountpoint': fstab_disks[device]})
                    del fstab_disks[device]
            if device not in all_mounted_asds:
                disks[device].update({'state': 'error',
                                      'state_detail': 'notmounted'})
        for device in fstab_disks.keys():
            disks[device] = {'device': '/dev/disk/by-id/{0}'.format(device),
                             'available': False,
                             'mountpoint': fstab_disks[device],
                             'state': 'error',
                             'state_detail': 'missing'}

        # Load statistical information about the disk
        root_directory = '/mnt/alba-asd'
        if DiskController._local_client.dir_exists(root_directory) and DiskController._local_client.dir_list(root_directory):
            df_info = check_output('df -B 1 --output=size,used,avail,target /mnt/alba-asd/*', shell=True).strip().splitlines()[1:]
            for disk_id in disks:
                if disks[disk_id]['available'] is False and disks[disk_id]['state'] == 'ok':
                    for df in df_info:
                        params = df.split()
                        if params[-1] == disks[disk_id]['mountpoint']:
                            disks[disk_id].update({'usage': {'size': int(params[0]),
                                                             'used': int(params[1]),
                                                             'available': int(params[2])}})

        # Execute some checkups on the disks
        for disk_id in disks:
            if disks[disk_id]['available'] is False and disks[disk_id]['state'] == 'ok':
                output = check_output('ls {0}/ 2>&1 || true'.format(disks[disk_id]['mountpoint']), shell=True)
                if 'Input/output error' in output:
                    disks[disk_id].update({'state': 'error',
                                           'state_detail': 'ioerror'})

        # Extra information
        for disk_id, disk in disks.iteritems():
            disk['name'] = disk_id
            disk['node_id'] = DiskController.NODE_ID

        return disks

    @staticmethod
    def prepare_disk(disk_id):
        """
        Prepare a disk for use with ALBA
        :param disk_id: Disk identifier
        :type disk_id: str
        """
        DiskController._log('Preparing disk {0}'.format(disk_id))
        mountpoint = '/mnt/alba-asd/{0}'.format(''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16)))
        disk_by_id = '/dev/disk/by-id/{0}'.format(disk_id)
        DiskController.locate(disk_id, start=False)
        check_output('umount {0} || true'.format(mountpoint), shell=True)
        check_output('parted {0} -s mklabel gpt'.format(disk_by_id), shell=True)
        check_output('parted {0} -s mkpart {1} 2MB 100%'.format(disk_by_id, disk_id), shell=True)
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
        DiskController._log('Prepare disk {0} complete'.format(disk_id))

    @staticmethod
    def clean_disk(disk_id, mountpoint):
        """
        Removes the given disk
        :param disk_id: Disk identifier
        :type disk_id: str
        :param mountpoint: Mountpoint of the disk
        :type mountpoint: str
        """
        DiskController._log('Cleaning disk {0}'.format(disk_id))
        FSTab.remove('/dev/disk/by-id/{0}-part1'.format(disk_id))
        check_output('umount {0} || true'.format(mountpoint), shell=True)
        DiskController._local_client.dir_delete(mountpoint)
        try:
            check_output('parted /dev/disk/by-id/{0} -s mklabel gpt'.format(disk_id), shell=True)
        except CalledProcessError:
            # Wiping the partition is a nice-to-have and might fail when a disk is e.g. unavailable
            pass
        DiskController.locate(disk_id, start=True)
        DiskController._log('Clean disk {0} complete'.format(disk_id))

    @staticmethod
    def remount_disk(disk_id, mountpoint):
        """
        Remount the disk
        :param disk_id: Disk identifier
        :type disk_id: str
        :param mountpoint: Mountpoint of the disk
        :type mountpoint: str
        """
        DiskController._log('Remounting disk {0}'.format(disk_id))
        check_output('umount {0} || true'.format(mountpoint), shell=True)
        check_output('mount {0} || true'.format(mountpoint), shell=True)
        DiskController._log('Remounting disk {0} complete'.format(disk_id))

    @staticmethod
    def scan_controllers():
        """
        Scan the disk controller(s)
        """
        DiskController._log('Scanning controllers')
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
        DiskController._log('Scan complete')

    @staticmethod
    def locate(disk_id, start):
        """
        Locate the disk on the controller
        :param disk_id: Disk identifier
        :type disk_id: str
        :param start: True to start locating, False otherwise
        :type start: bool
        """
        for wwn in DiskController.controllers:
            if disk_id.endswith(wwn):
                controller_type, location = DiskController.controllers[wwn]
                if controller_type == 'storcli64':
                    DiskController._log('Location {0} for {1}'.format('start' if start is True else 'stop', location))
                    check_output('storcli64 {0} {1} locate'.format(location, 'start' if start is True else 'stop'), shell=True)
