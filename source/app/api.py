# Copyright 2015 CloudFounders NV
# All rights reserved

"""
API views
"""

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
            Configuration.set('asd.available.disks', disks)
            data['data'] = disks
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
            current_disks = Configuration.get_list('asd.disks')
            available_disks = Configuration.get_list('asd.available.disks')
            if disk in current_disks:
                return json.dumps({'_success': False, '_error': 'Disk already configured'})
            if disk not in available_disks:
                return json.dumps({'_success': False, '_error': 'Disk not available'})

            # @TODO: Controller magic: start using disk and other stuff
            check_output('parted /dev/disk/by-id/{0} -s mklabel gpt'.format(disk), shell=True)
            check_output('parted /dev/disk/by-id/{0} -s mkpart {0} 2MB 100%'.format(disk), shell=True)
            check_output('mkfs.ext4 -q /dev/disk/by-id/{0}-part1 -L {0}'.format(disk), shell=True)
            check_output('mkdir -p /mnt/alba-asd/{0}'.format(disk), shell=True)
            FSTab.add('/dev/disk/by-id/{0}-part1'.format(disk), '/mnt/alba-asd/{0}'.format(disk))
            check_output('mount /mnt/alba-asd/{0}'.format(disk), shell=True)
            # @TODO: Start services etc

            current_disks.append(disk)
            Configuration.set('asd.disks', current_disks)
            return json.dumps({'_success': True})
        except Exception as ex:
            return json.dumps({'_success': False, '_error': str(ex)})

    @staticmethod
    @app.route('/disks/<disk>/delete', methods=['POST'])
    @requires_auth()
    def delete_disk(disk):
        try:
            current_disks = Configuration.get_list('asd.disks')
            if disk not in current_disks:
                return json.dumps({'_success': False, '_error': 'Disk not configured'})

            # @TODO: Stop services etc
            check_output('umount /mnt/alba-asd/{0}'.format(disk), shell=True)
            FSTab.remove('/dev/disk/by-id/{0}-part1'.format(disk))
            check_output('rm -rf /mnt/alba-asd/{0}'.format(disk), shell=True)
            # @TODO: Controller magic: remove disk from controller and/or highlight the disk

            current_disks.remove(disk)
            Configuration.set('asd.disks', current_disks)
            return json.dumps({'_success': True})
        except Exception as ex:
            return json.dumps({'_success': False, '_error': str(ex)})
