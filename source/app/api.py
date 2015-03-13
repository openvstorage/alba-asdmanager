# Copyright 2015 CloudFounders NV
# All rights reserved

"""
API views
"""

import os
import json
import string
import random
from flask import request
from subprocess import check_output
from source.app.exceptions import BadRequest
from source.tools.configuration import Configuration
from source.tools.disks import Disks
from source.tools.filemutex import FileMutex
from source.app.decorators import get, post


class API(object):
    @staticmethod
    @get('/')
    def index():
        return {'box_id': Configuration().data['main']['box_id'],
                '_links': ['/disks', '/net'],
                '_actions': []}

    @staticmethod
    @get('/net', authenticate=False)
    def net():
        output = check_output("ip a | grep 'inet ' | sed 's/\s\s*/ /g' | cut -d ' ' -f 3 | cut -d '/' -f 1", shell=True)
        my_ips = output.split('\n')
        return {'ips': [found_ip.strip() for found_ip in my_ips if found_ip.strip() != '127.0.0.1' and found_ip.strip() != ''],
                '_links': [],
                '_actions': ['/net']}

    @staticmethod
    @post('/net')
    def set_net():
        with Configuration() as config:
            config.data['network']['ips'] = json.loads(request.form['ips'])
        return {'_link': '/net'}

    @staticmethod
    def _disk_hateoas(disk, disk_id):
        disk['_link'] = '/disks/{0}'.format(disk_id)
        if disk['available'] is False:
            actions = ['/disks/{0}/delete'.format(disk_id)]
            if disk['state']['state'] == 'error':
                actions.append('/disks/{0}/restart'.format(disk_id))
        else:
            actions = ['/disks/{0}/add'.format(disk_id)]
        disk['_actions'] = actions

    @staticmethod
    def _list_disks():
        disks = Disks.list_disks()
        for disk_id in disks:
            if disks[disk_id]['available'] is False:
                if disks[disk_id]['state']['state'] != 'error':
                    if os.path.exists('/mnt/alba-asd/{0}/asd.json'.format(disk_id)):
                        try:
                            with open('/mnt/alba-asd/{0}/asd.json'.format(disk_id), 'r') as conffile:
                                disks[disk_id].update(json.load(conffile))
                        except ValueError:
                            disks[disk_id]['state'] = {'state': 'error',
                                                       'detail': 'corruption'}
                    else:
                        disks[disk_id]['state'] = {'state': 'error',
                                                   'detail': 'servicefailure'}
                    if disks[disk_id]['state']['state'] != 'error':
                        service_state = check_output('status alba-asd-{0} || true'.format(disk_id), shell=True)
                        if 'start/running' not in service_state:
                            disks[disk_id]['state'] = {'state': 'error',
                                                       'detail': 'servicefailure'}
            disks[disk_id]['name'] = disk_id
            API._disk_hateoas(disks[disk_id], disk_id)
        return disks

    @staticmethod
    @get('/disks')
    def list_disks():
        data = API._list_disks()
        data['_parent'] = '/'
        data['_actions'] = []
        return data

    @staticmethod
    @get('/disks/<disk>')
    def index_disk(disk):
        all_disks = API._list_disks()
        if disk not in all_disks:
            raise BadRequest('Disk unknown')
        data = all_disks[disk]
        API._disk_hateoas(data, disk)
        data['_link'] = '/disks/{0}'.format(disk)
        return data

    @staticmethod
    @post('/disks/<disk>/add')
    def add_disk(disk):
        with FileMutex('add_disk'), FileMutex('disk_'.format(disk)):
            config = Configuration()
            all_disks = API._list_disks()
            if disk not in all_disks:
                raise BadRequest('Disk not available')
            if all_disks[disk]['available'] is False:
                raise BadRequest('Disk already configured')

            # Partitioning and mounting
            Disks.prepare_disk(disk)

            # Prepare & start service
            port = int(config.data['network']['port'])
            ips = config.data['network']['ips']
            used_ports = [all_disks[_disk]['port'] for _disk in all_disks
                          if all_disks[_disk]['available'] is False and 'port' in all_disks[_disk]]
            while port in used_ports:
                port += 1
            asd_id = '{0}-{1}'.format(disk, ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(5)))
            asd_config = {'home': '/mnt/alba-asd/{0}/data'.format(disk),
                          'box_id': config.data['main']['box_id'],
                          'asd_id': asd_id,
                          'log_level': 'debug',
                          'port': port}
            if ips is not None and len(ips) > 0:
                asd_config['ips'] = ips
            with open('/mnt/alba-asd/{0}/asd.json'.format(disk), 'w') as conffile:
                conffile.write(json.dumps(asd_config))
            check_output('chmod 666 /mnt/alba-asd/{0}/asd.json'.format(disk), shell=True)
            check_output('chown alba:alba /mnt/alba-asd/{0}/asd.json'.format(disk), shell=True)
            with open('/opt/alba-asdmanager/config/upstart/alba-asd.conf', 'r') as template:
                contents = template.read()
            contents = contents.replace('<ASD>', disk)
            with open('/etc/init/alba-asd-{0}.conf'.format(disk), 'w') as upstart:
                upstart.write(contents)
            check_output('start alba-asd-{0}'.format(disk), shell=True)

            return {'_link': '/disks/{0}'.format(disk)}

    @staticmethod
    @post('/disks/<disk>/delete')
    def delete_disk(disk):
        with FileMutex('disk_'.format(disk)):
            all_disks = API._list_disks()
            if disk not in all_disks:
                raise BadRequest('Disk not available')
            if all_disks[disk]['available'] is True:
                raise BadRequest('Disk not yet configured')

            # Stop and remove service
            check_output('stop alba-asd-{0} || true'.format(disk), shell=True)
            if os.path.exists('/etc/init/alba-asd-{0}.conf'.format(disk)):
                os.remove('/etc/init/alba-asd-{0}.conf'.format(disk))

            # Cleanup & unmount disk
            Disks.clean_disk(disk)

            return {'_link': '/disks/{0}'.format(disk)}

    @staticmethod
    @post('/disks/<disk>/restart')
    def restart_disk(disk):
        with FileMutex('disk_'.format(disk)):
            all_disks = API._list_disks()
            if disk not in all_disks:
                raise BadRequest('Disk not available')
            if all_disks[disk]['available'] is True:
                raise BadRequest('Disk not yet configured')

            # Stop service, remount, start service
            check_output('stop alba-asd-{0} || true'.format(disk), shell=True)
            check_output('umount /mnt/alba-asd/{0} || true'.format(disk), shell=True)
            check_output('mount /mnt/alba-asd/{0} || true'.format(disk), shell=True)
            check_output('start alba-asd-{0} || true'.format(disk), shell=True)

            return {'_link': '/disks/{0}'.format(disk)}
