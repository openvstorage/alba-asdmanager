# Copyright 2015 CloudFounders NV
# All rights reserved

"""
API views
"""

import os
import re
import json
import string
import random
from subprocess import check_output
from source.app.exceptions import BadRequest
from source.tools.fstab import FSTab
from source.tools.configuration import Configuration
from source.app.decorators import get, post


class API(object):
    @staticmethod
    @get('/')
    def index():
        return {'_links': ['/disks'],
                '_actions': []}

    @staticmethod
    @get('/disks')
    def list_disks():
        # Find mountpoints
        all_mounts = check_output('mount', shell=True).split('\n')
        mounts = []
        for mount in all_mounts:
            mount = mount.strip()
            match = re.search('/dev/(.+?) on /.*', mount)
            if match is not None:
                mounts.append(match.groups()[0])

        # Find all disks
        all_disks = check_output('ls -al /dev/disk/by-id/', shell=True).split('\n')
        disks = []
        for disk in all_disks:
            disk = disk.strip()
            match = re.search('.+?(((scsi-)|(ata-)).+?) -> ../../(.+)', disk)
            if match is not None:
                disk_id, disk_name = match.groups()[0], match.groups()[-1]
                if re.search('-part\d+', disk_id) is None:
                    if not any(mount for mount in mounts if disk_name in mount):
                        disks.append(disk_id)

        # Update configuration
        with Configuration() as config:
            for disk in disks:
                if disk not in config.data['disks']:
                    config.data['disks'][disk] = {'available': True}

        # For the existing disks, request metadata
        df_info = check_output('df -k', shell=True).strip().split('\n')
        for disk_id in config.data['disks']:
            disk = config.data['disks'][disk_id]
            if disk['available'] is False:
                for df in df_info:
                    match = re.search('\S+?\s+?(\d+?)\s+?(\d+?)\s+?(\d+?)\s.+?/mnt/alba-asd/{0}'.format(disk_id), df)
                    if match is not None:
                        config.data['disks'][disk_id]['statistics'] = {'size': int(match.groups()[0]) * 1024,
                                                                       'used': int(match.groups()[1]) * 1024,
                                                                       'available': int(match.groups()[2]) * 1024}
                        config.data['disks'][disk_id]['mountpoint'] = '/mnt/alba-asd/{0}'.format(disk_id)
                        config.data['disks'][disk_id]['device'] = '/dev/disk/by-id/{0}'.format(disk_id)

        # Use HATEOAS
        for disk in config.data['disks']:
            config.data['disks'][disk]['_link'] = '/disks/{0}'.format(disk)
            if config.data['disks'][disk]['available'] is False:
                actions = ['/disks/{0}/delete'.format(disk)]
            else:
                actions = ['/disks/{0}/add'.format(disk)]
            config.data['disks'][disk]['_actions'] = actions
        data = config.data['disks']
        data['_parent'] = '/'
        data['_actions'] = []

        return data

    @staticmethod
    @get('/disks/<disk>')
    def index_disk(disk):
        config = Configuration()

        # Validate parameters
        if disk not in config.data['disks']:
            raise BadRequest('Disk unknown')

        # Load information about the given disk
        df_info = check_output('df -k', shell=True).strip().split('\n')
        disk_info = config.data['disks'][disk]
        if disk_info['available'] is False:
            for df in df_info:
                match = re.search('\S+?\s+?(\d+?)\s+?(\d+?)\s+?(\d+?)\s.+?/mnt/alba-asd/{0}'.format(disk), df)
                if match is not None:
                    disk_info['statistics'] = {'size': int(match.groups()[0]) * 1024,
                                               'used': int(match.groups()[1]) * 1024,
                                               'available': int(match.groups()[2]) * 1024}
                    disk_info['mountpoint'] = '/mnt/alba-asd/{0}'.format(disk)
                    disk_info['device'] = '/dev/disk/by-id/{0}'.format(disk)

        # Use HATEOAS
        data = disk_info
        data['_link'] = '/disks/{0}'.format(disk)
        data['_links'] = ['/', '/disks']
        if disk_info['available'] is False:
            actions = ['/disks/{0}/delete'.format(disk)]
        else:
            actions = ['/disks/{0}/add'.format(disk)]
        data['_actions'] = actions

        return data

    @staticmethod
    @post('/disks/<disk>/add')
    def add_disk(disk):
        config = Configuration()

        # Validate parameters
        if disk not in config.data['disks']:
            raise BadRequest('Disk not available')
        if config.data['disks'][disk]['available'] is False:
            raise BadRequest('Disk already configured')

        # @TODO: Controller magic: start using disk and other stuff

        # Partitioning and mounting
        check_output('umount /mnt/alba-asd/{0} || true'.format(disk), shell=True)
        check_output('parted /dev/disk/by-id/{0} -s mklabel gpt'.format(disk), shell=True)
        check_output('parted /dev/disk/by-id/{0} -s mkpart {0} 2MB 100%'.format(disk), shell=True)
        check_output('mkfs.ext4 -q /dev/disk/by-id/{0}-part1 -L {0}'.format(disk), shell=True)
        check_output('mkdir -p /mnt/alba-asd/{0}'.format(disk), shell=True)
        FSTab.add('/dev/disk/by-id/{0}-part1'.format(disk), '/mnt/alba-asd/{0}'.format(disk))
        check_output('mount /mnt/alba-asd/{0}'.format(disk), shell=True)
        check_output('chown -R alba:alba /mnt/alba-asd/{0}'.format(disk), shell=True)

        # Prepare & start service
        port = int(config.data['ports']['asd'])
        used_ports = [config.data['disks'][_disk]['port'] for _disk in config.data['disks']
                      if config.data['disks'][_disk]['available'] is False]
        while port in used_ports:
            port += 1
        asd_config = {'home': '/mnt/alba-asd/{0}'.format(disk),
                      'box_id': config.data['main']['box_id'],
                      'asd_id': '{0}-{1}'.format(disk, ''.join(random.choice(string.ascii_letters +
                                                                             string.digits)
                                                               for _ in range(5))),
                      'log_level': 'debug',
                      'port': port}
        with open('/opt/alba-asdmanager/config/asd/{0}.json'.format(disk), 'w') as conffile:
            conffile.write(json.dumps(asd_config))
        check_output('chmod 666 /opt/alba-asdmanager/config/asd/{0}.json'.format(disk), shell=True)
        check_output('chown alba:alba /opt/alba-asdmanager/config/asd/{0}.json'.format(disk), shell=True)
        with open('/opt/alba-asdmanager/config/upstart/alba-asd.conf', 'r') as template:
            contents = template.read()
        contents = contents.replace('<ASD>', disk)
        with open('/etc/init/alba-asd-{0}.conf'.format(disk), 'w') as upstart:
            upstart.write(contents)
        check_output('start alba-asd-{0}'.format(disk), shell=True)

        # Save configurations
        with Configuration() as config:
            config.data['disks'][disk]['available'] = False
            config.data['disks'][disk]['port'] = port
        return {'_link': '/disks/{0}'.format(disk)}

    @staticmethod
    @post('/disks/<disk>/delete')
    def delete_disk(disk):
        config = Configuration()

        # Validate parameters
        if disk not in config.data['disks']:
            raise BadRequest('Disk not available')
        if config.data['disks'][disk]['available'] is True:
            raise BadRequest('Disk not yet configured')

        # Stop and remove service
        check_output('stop alba-asd-{0} || true'.format(disk), shell=True)
        if os.path.exists('/etc/init/alba-asd-{0}.conf'.format(disk)):
            os.remove('/etc/init/alba-asd-{0}.conf'.format(disk))
        if os.path.exists('/opt/alba-asdmanager/config/asd/{0}.json'.format(disk)):
            os.remove('/opt/alba-asdmanager/config/asd/{0}.json'.format(disk))

        # Cleanup & unmount disk
        check_output('rm -rf /mnt/alba-asd/{0}/* || true'.format(disk), shell=True)
        check_output('umount /mnt/alba-asd/{0} || true'.format(disk), shell=True)
        FSTab.remove('/dev/disk/by-id/{0}-part1'.format(disk))
        check_output('rm -rf /mnt/alba-asd/{0} || true'.format(disk), shell=True)

        # @TODO: Controller magic: remove disk from controller and/or highlight the disk

        # Save configurations
        with Configuration() as config:
            config.data['disks'][disk] = {'available': True}
        return {'_link': '/disks/{0}'.format(disk)}
