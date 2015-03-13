# Copyright 2015 CloudFounders NV
# All rights reserved

"""
Disk related code
"""
import re
from subprocess import check_output
from source.tools.fstab import FSTab


class Disks(object):
    """
    Disk helper methods
    """

    @staticmethod
    def list_disks():
        disks = {}

        # Find mountpoints
        all_mounts = check_output('mount', shell=True).split('\n')
        mounts = []
        for mount in all_mounts:
            mount = mount.strip()
            match = re.search('/dev/(.+?) on (/.*?) type.*', mount)
            if match is not None and not match.groups()[1].startswith('/mnt/alba-asd/'):
                mounts.append(match.groups()[0])

        # Find all disks
        all_disks = check_output('ls -al /dev/disk/by-id/', shell=True).split('\n')
        for disk in all_disks:
            disk = disk.strip()
            match = re.search('.+?(((scsi-)|(ata-)).+?) -> ../../(sd.+)', disk)
            if match is not None:
                disk_id, disk_name = match.groups()[0], match.groups()[-1]
                if re.search('-part\d+', disk_id) is None:
                    if not any(mount for mount in mounts if disk_name in mount):
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

        # Load statistical information about the disk
        df_info = check_output('df -k', shell=True).strip().split('\n')
        for disk_id in disks:
            for df in df_info:
                match = re.search('\S+?\s+?(\d+?)\s+?(\d+?)\s+?(\d+?)\s.+?/mnt/alba-asd/{0}'.format(disk_id), df)
                if match is not None:
                    disks[disk_id].update({'statistics': {'size': int(match.groups()[0]) * 1024,
                                                          'used': int(match.groups()[1]) * 1024,
                                                          'available': int(match.groups()[2]) * 1024}})

        # Execute some checkups on the disks
        for disk_id in disks:
            if disks[disk_id]['available'] is False and disks[disk_id]['state']['state'] == 'ok':
                output = check_output('ls /mnt/alba-asd/{0}/ 2>&1 || true'.format(disk_id), shell=True)
                if 'Input/output error' in output:
                    disks[disk_id]['state'] = {'state': 'error',
                                               'detail': 'ioerror'}

        return disks

    @staticmethod
    def prepare_disk(disk):
        check_output('umount /mnt/alba-asd/{0} || true'.format(disk), shell=True)
        check_output('parted /dev/disk/by-id/{0} -s mklabel gpt'.format(disk), shell=True)
        check_output('parted /dev/disk/by-id/{0} -s mkpart {0} 2MB 100%'.format(disk), shell=True)
        check_output('mkfs.ext4 -q /dev/disk/by-id/{0}-part1 -L {0}'.format(disk), shell=True)
        check_output('mkdir -p /mnt/alba-asd/{0}'.format(disk), shell=True)
        FSTab.add('/dev/disk/by-id/{0}-part1'.format(disk), '/mnt/alba-asd/{0}'.format(disk))
        check_output('mount /mnt/alba-asd/{0}'.format(disk), shell=True)
        check_output('mkdir /mnt/alba-asd/{0}/data'.format(disk), shell=True)
        check_output('chown -R alba:alba /mnt/alba-asd/{0}'.format(disk), shell=True)

    @staticmethod
    def clean_disk(disk):
        check_output('rm -rf /mnt/alba-asd/{0}/* || true'.format(disk), shell=True)
        check_output('umount /mnt/alba-asd/{0} || true'.format(disk), shell=True)
        FSTab.remove('/dev/disk/by-id/{0}-part1'.format(disk))
        check_output('rm -rf /mnt/alba-asd/{0} || true'.format(disk), shell=True)
