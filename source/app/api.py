# Copyright 2015 CloudFounders NV
# All rights reserved

"""
API views
"""

import os
import re
import json
from app import app
from subprocess import check_output
from tools.fstab import FSTab
from tools.configuration import Configuration
from app.decorators import requires_auth


class API(object):
    @staticmethod
    @app.route('/', methods=['GET'])
    @requires_auth()
    def index():
        data = {'_links': ['/disks'],
                '_actions': []}
        return json.dumps(data)

    @staticmethod
    @app.route('/disks', methods=['GET'])
    @requires_auth()
    def list_disks():
        data = {'_links': ['/disks/{disk}'],
                '_actions': [],
                'data': [],
                '_success': True}
        try:
            all_mounts = check_output('mount', shell=True).split('\n')
            mounts = []
            for mount in all_mounts:
                mount = mount.strip()
                match = re.search('/dev/(.+?) on /.*', mount)
                if match is not None:
                    mounts.append(match.groups()[0])
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
            with Configuration() as config:
                for disk in disks:
                    if disk not in config.data['disks']:
                        config.data['disks'][disk] = {'available': True}
            data['data'] = config.data['disks']
        except Exception as ex:
            data['_success'] = False
            data['_error'] = str(ex)
        return json.dumps(data)

    @staticmethod
    @app.route('/disks/<disk>', methods=['GET'])
    @requires_auth()
    def index_disk(disk):
        _ = disk
        data = {'_links': [],
                '_actions': ['add', 'delete']}
        return json.dumps(data)

    @staticmethod
    @app.route('/disks/<disk>/add', methods=['POST'])
    @requires_auth()
    def add_disk(disk):
        try:
            config = Configuration()

            # Validate parameters
            if disk not in config.data['disks']:
                return json.dumps({'_success': False, '_error': 'Disk not available'})
            if config.data['disks'][disk]['available'] is False:
                return json.dumps({'_success': False, '_error': 'Disk already configured'})

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

            return json.dumps({'_success': True})
        except Exception as ex:
            return json.dumps({'_success': False, '_error': str(ex)})

    @staticmethod
    @app.route('/disks/<disk>/delete', methods=['POST'])
    @requires_auth()
    def delete_disk(disk):
        try:
            config = Configuration()

            # Validate parameters
            if disk not in config.data['disks']:
                return json.dumps({'_success': False, '_error': 'Disk not available'})
            if config.data['disks'][disk]['available'] is True:
                return json.dumps({'_success': False, '_error': 'Disk not yet configured'})

            # Stop and remove service
            check_output('stop alba-asd-{0} || true'.format(disk), shell=True)
            if os.path.exists('/etc/init/alba-asd-{0}.conf'.format(disk)):
                os.remove('/etc/init/alba-asd-{0}.conf'.format(disk))
            if os.path.exists('/opt/alba-asdmanager/config/asd/{0}.json'.format(disk)):
                os.remove('/opt/alba-asdmanager/config/asd/{0}.json'.format(disk))

            # Unmount disk
            check_output('umount /mnt/alba-asd/{0} || true'.format(disk), shell=True)
            FSTab.remove('/dev/disk/by-id/{0}-part1'.format(disk))
            check_output('rm -rf /mnt/alba-asd/{0} || true'.format(disk), shell=True)

            # @TODO: Controller magic: remove disk from controller and/or highlight the disk

            # Save configurations
            with Configuration() as config:
                config.data['disks'][disk] = {'available': True}

            return json.dumps({'_success': True})
        except Exception as ex:
            return json.dumps({'_success': False, '_error': str(ex)})
