# Copyright 2015 CloudFounders NV
# All rights reserved

"""
API views
"""

import os
import json
import copy
import string
import random
from subprocess import check_output
from source.app.exceptions import BadRequest
from source.tools.fstab import FSTab
from source.tools.configuration import Configuration
from source.tools.disks import Disks
from source.app.decorators import get, post, locked


class API(object):
    @staticmethod
    @get('/')
    def index():
        return {'box_id': Configuration().data['main']['box_id'],
                '_links': ['/disks'],
                '_actions': []}

    @staticmethod
    @get('/disks')
    def list_disks():
        # Load current disks
        disks = Disks.list_disks()

        with Configuration() as config:
            # Update configuration
            for disk_id in disks:
                if disk_id not in config.data['disks']:
                    config.data['disks'][disk_id] = {'available': disks[disk_id]['available']}
                disks[disk_id].update(config.data['disks'][disk_id])
            # Find disks that are gone
            for disk_id in config.data['disks'].keys():
                if disk_id not in disks:
                    if config.data['disks'][disk_id]['available'] is True:
                        del config.data['disks'][disk_id]
                    else:
                        disks[disk_id] = copy.deepcopy(config.data['disks'][disk_id])
                        disks[disk_id]['state'] = {'state': 'error',
                                                   'detail': 'missing'}
                elif config.data['disks'][disk_id]['available'] is False:
                    service_state = check_output('status alba-asd-{0} || true'.format(disk_id), shell=True)
                    if 'start/running' not in service_state:
                        disks[disk_id]['state'] = {'state': 'error',
                                                   'detail': 'servicefailure'}

        # Add some extra data + HATEOAS
        for disk_id in disks:
            disks[disk_id]['name'] = disk_id
            disks[disk_id]['_link'] = '/disks/{0}'.format(disk_id)
            if disks[disk_id]['available'] is False:
                actions = ['/disks/{0}/delete'.format(disk_id)]
                if disks[disk_id]['state']['state'] == 'error':
                    actions.append('/disks/{0}/restart'.format(disk_id))
            else:
                actions = ['/disks/{0}/add'.format(disk_id)]
            disks[disk_id]['_actions'] = actions
        data = disks
        data['_parent'] = '/'
        data['_actions'] = []

        return data

    @staticmethod
    @get('/disks/<disk>')
    def index_disk(disk):
        all_disks = json.loads(API.list_disks().response[0])
        if all_disks['_success'] is False:
            raise Exception(all_disks['_error'])

        if disk not in all_disks:
            raise BadRequest('Disk unknown')

        # Use HATEOAS
        data = all_disks[disk]
        data['_link'] = '/disks/{0}'.format(disk)
        data['_links'] = ['/', '/disks']
        if data['available'] is False:
            actions = ['/disks/{0}/delete'.format(disk)]
            if data['state']['state'] == 'error':
                actions.append('/disks/{0}/restart'.format(disk))
        else:
            actions = ['/disks/{0}/add'.format(disk)]
        data['_actions'] = actions

        return data

    @staticmethod
    @locked()
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
        asd_id = '{0}-{1}'.format(disk, ''.join(random.choice(string.ascii_letters +
                                                              string.digits)
                                                for _ in range(5)))
        asd_config = {'home': '/mnt/alba-asd/{0}'.format(disk),
                      'box_id': config.data['main']['box_id'],
                      'asd_id': asd_id,
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
            config.data['disks'][disk]['asd_id'] = asd_id
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

    @staticmethod
    @post('/disks/<disk>/restart')
    def restart_disk(disk):
        config = Configuration()

        # Validate parameters
        if disk not in config.data['disks']:
            raise BadRequest('Disk not available')
        if config.data['disks'][disk]['available'] is True:
            raise BadRequest('Disk not yet configured')

        # Stop service, remount, start service
        check_output('stop alba-asd-{0} || true'.format(disk), shell=True)
        check_output('umount /mnt/alba-asd/{0} || true'.format(disk), shell=True)
        check_output('mount /mnt/alba-asd/{0} || true'.format(disk), shell=True)
        check_output('start alba-asd-{0} || true'.format(disk), shell=True)

        return {'_link': '/disks/{0}'.format(disk)}
