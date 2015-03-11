# Copyright 2015 CloudFounders NV
# All rights reserved

"""
Disk related code
"""
import re
from subprocess import check_output


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

        # Load information about disks
        df_info = check_output('df -k', shell=True).strip().split('\n')
        for disk_id in disks:
            for df in df_info:
                match = re.search('\S+?\s+?(\d+?)\s+?(\d+?)\s+?(\d+?)\s.+?/mnt/alba-asd/{0}'.format(disk_id), df)
                if match is not None:
                    disks[disk_id].update({'available': False,
                                           'statistics': {'size': int(match.groups()[0]) * 1024,
                                                          'used': int(match.groups()[1]) * 1024,
                                                          'available': int(match.groups()[2]) * 1024},
                                           'mountpoint': '/mnt/alba-asd/{0}'.format(disk_id)})

        # Execute some checkups on the disks
        for disk_id in disks:
            if disks[disk_id]['available'] is False:
                output = check_output('ls /mnt/alba-asd/{0}/ 2>&1 || true'.format(disk_id), shell=True)
                if 'Input/output error' in output:
                    disks[disk_id]['state'] = {'state': 'error',
                                               'detail': 'ioerror'}

        return disks
