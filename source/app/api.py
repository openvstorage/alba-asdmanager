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
    PACKAGE_NAME = 'openvstorage-sdm'
    SERVICE_PREFIX = 'alba-asd-'
    APT_CONFIG_STRING = '-o Dir::Etc::sourcelist="sources.list.d/ovsaptrepo.list" -o Dir::Etc::sourceparts="-" -o APT::Get::List-Cleanup="0"'

    @staticmethod
    @get('/')
    def index():
        return {'box_id': Configuration().data['main']['box_id'],
                '_links': ['/disks', '/net', '/update'],
                '_actions': []}

    @staticmethod
    @get('/net', authenticate=False)
    def net():
        print 'Loading network information'
        output = check_output("ip a | grep 'inet ' | sed 's/\s\s*/ /g' | cut -d ' ' -f 3 | cut -d '/' -f 1", shell=True)
        my_ips = output.split('\n')
        return {'ips': [found_ip.strip() for found_ip in my_ips if found_ip.strip() != '127.0.0.1' and found_ip.strip() != ''],
                '_links': [],
                '_actions': ['/net']}

    @staticmethod
    @post('/net')
    def set_net():
        print 'Setting network information'
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
        print 'Fetching disks'
        disks = Disks.list_disks()
        for disk_id in disks:
            if disks[disk_id]['available'] is False:
                asd_id = disks[disk_id]['asd_id']
                if disks[disk_id]['state']['state'] != 'error':
                    if os.path.exists('/mnt/alba-asd/{0}/asd.json'.format(asd_id)):
                        try:
                            with open('/mnt/alba-asd/{0}/asd.json'.format(asd_id), 'r') as conffile:
                                disks[disk_id].update(json.load(conffile))
                        except ValueError:
                            disks[disk_id]['state'] = {'state': 'error',
                                                       'detail': 'corruption'}
                    else:
                        disks[disk_id]['state'] = {'state': 'error',
                                                   'detail': 'servicefailure'}
                    if disks[disk_id]['state']['state'] != 'error':
                        service_state = check_output('status {0}{1} || true'.format(API.SERVICE_PREFIX, asd_id), shell=True)
                        if 'start/running' not in service_state:
                            disks[disk_id]['state'] = {'state': 'error',
                                                       'detail': 'servicefailure'}
            disks[disk_id]['name'] = disk_id
            disks[disk_id]['box_id'] = Configuration().data['main']['box_id']
            API._disk_hateoas(disks[disk_id], disk_id)
        print 'Fetching disks completed'
        return disks

    @staticmethod
    @get('/disks')
    def list_disks():
        print 'Listing disks'
        data = API._list_disks()
        data['_parent'] = '/'
        data['_actions'] = []
        return data

    @staticmethod
    @get('/disks/<disk>')
    def index_disk(disk):
        print 'Listing disk {0}'.format(disk)
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
        print 'Add disk {0}'.format(disk)
        with FileMutex('add_disk'), FileMutex('disk_'.format(disk)):
            print 'Got lock for add disk {0}'.format(disk)
            config = Configuration()
            all_disks = API._list_disks()
            if disk not in all_disks:
                raise BadRequest('Disk not available')
            if all_disks[disk]['available'] is False:
                raise BadRequest('Disk already configured')

            # Partitioning and mounting
            print 'Preparing disk {0}'.format(disk)
            asd_id = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))
            Disks.prepare_disk(disk, asd_id)

            # Prepare & start service
            print 'Setting up service for disk {0}'.format(disk)
            port = int(config.data['network']['port'])
            ips = config.data['network']['ips']
            used_ports = [all_disks[_disk]['port'] for _disk in all_disks
                          if all_disks[_disk]['available'] is False and 'port' in all_disks[_disk]]
            while port in used_ports:
                port += 1
            asd_config = {'home': '/mnt/alba-asd/{0}/data'.format(asd_id),
                          'box_id': config.data['main']['box_id'],
                          'asd_id': asd_id,
                          'log_level': 'debug',
                          'port': port}
            if ips is not None and len(ips) > 0:
                asd_config['ips'] = ips
            with open('/mnt/alba-asd/{0}/asd.json'.format(asd_id), 'w') as conffile:
                conffile.write(json.dumps(asd_config))
            check_output('chmod 666 /mnt/alba-asd/{0}/asd.json'.format(asd_id), shell=True)
            check_output('chown alba:alba /mnt/alba-asd/{0}/asd.json'.format(asd_id), shell=True)
            with open('/opt/alba-asdmanager/config/upstart/alba-asd.conf', 'r') as template:
                contents = template.read()
            service_name = '{0}{1}'.format(API.SERVICE_PREFIX, asd_id)
            contents = contents.replace('<ASD>', asd_id)
            contents = contents.replace('<SERVICE_NAME>', service_name)
            with open('/etc/init/{0}.conf'.format(service_name), 'w') as upstart:
                upstart.write(contents)
            check_output('start {0}'.format(service_name), shell=True)

            print 'Returning info about added disk {0}'.format(disk)
            all_disks = API._list_disks()
            data = all_disks[disk]
            API._disk_hateoas(data, disk)
            data['_link'] = '/disks/{0}'.format(disk)
            return data

    @staticmethod
    @post('/disks/<disk>/delete')
    def delete_disk(disk):
        print 'Deleting disk {0}'.format(disk)
        with FileMutex('disk_'.format(disk)):
            print 'Got lock for deleting disk {0}'.format(disk)
            all_disks = API._list_disks()
            if disk not in all_disks:
                raise BadRequest('Disk not available')
            if all_disks[disk]['available'] is True:
                raise BadRequest('Disk not yet configured')

            # Stop and remove service
            print 'Removing services for disk {0}'.format(disk)
            asd_id = all_disks[disk]['asd_id']
            service_name = '{0}{1}'.format(API.SERVICE_PREFIX, asd_id)
            check_output('stop {0} || true'.format(service_name), shell=True)
            if os.path.exists('/etc/init/{0}.conf'.format(service_name)):
                os.remove('/etc/init/{0}.conf'.format(service_name))

            # Cleanup & unmount disk
            print 'Cleaning disk {0}'.format(disk)
            Disks.clean_disk(disk, asd_id)

            return {'_link': '/disks/{0}'.format(disk)}

    @staticmethod
    @post('/disks/<disk>/restart')
    def restart_disk(disk):
        print 'Restarting disk {0}'.format(disk)
        with FileMutex('disk_'.format(disk)):
            print 'Got lock for restarting disk {0}'.format(disk)
            all_disks = API._list_disks()
            if disk not in all_disks:
                raise BadRequest('Disk not available')
            if all_disks[disk]['available'] is True:
                raise BadRequest('Disk not yet configured')

            # Stop service, remount, start service
            asd_id = all_disks[disk]['asd_id']
            service_name = '{0}{1}'.format(API.SERVICE_PREFIX, asd_id)
            check_output('stop {0} || true'.format(service_name), shell=True)
            check_output('umount /mnt/alba-asd/{0} || true'.format(asd_id), shell=True)
            check_output('mount /mnt/alba-asd/{0} || true'.format(asd_id), shell=True)
            check_output('start {0} || true'.format(service_name), shell=True)

            return {'_link': '/disks/{0}'.format(disk)}

    @staticmethod
    @get('/update')
    def update():
        return {'_link': '/update/information',
                '_actions': ['/update/execute',
                             '/update/restart_services']}

    @staticmethod
    def _get_sdm_services():
        services = {}
        for file_name in os.listdir('/etc/init/'):
            if file_name.startswith(API.SERVICE_PREFIX) and file_name.endswith('.conf'):
                file_name = file_name.rstrip('.conf')
                file_path = '/opt/alba-asdmanager/run/{0}.version'.format(file_name)
                if os.path.isfile(file_path):
                    with open(file_path) as fp:
                        services[file_name] = fp.read().strip()
        return services

    @staticmethod
    def _get_package_information(package_name):
        installed = None
        candidate = None
        for line in check_output('apt-cache policy {0} {1}'.format(package_name, API.APT_CONFIG_STRING), shell=True).splitlines():
            line = line.strip()
            if line.startswith('Installed:'):
                installed = line.lstrip('Installed:').strip()
            elif line.startswith('Candidate:'):
                candidate = line.lstrip('Candidate:').strip()

            if installed is not None and candidate is not None:
                break
        print 'Installed version: {0}'.format(installed)
        print 'Candidate version: {0}'.format(candidate)
        return installed, candidate

    @staticmethod
    @get('/update/information')
    def get_update_information():
        check_output('apt-get update {0}'.format(API.APT_CONFIG_STRING), shell=True)
        sdm_package_info = API._get_package_information(package_name=API.PACKAGE_NAME)
        sdm_installed = sdm_package_info[0]
        sdm_candidate = sdm_package_info[1]
        if sdm_installed != sdm_candidate:
            return {'version': sdm_candidate,
                    'installed': sdm_installed}

        alba_package_info = API._get_package_information(package_name='alba')
        services = [key for key, value in API._get_sdm_services().iteritems() if value != alba_package_info[1]]
        return {'version': sdm_candidate if services else '',
                'installed': sdm_installed}

    @staticmethod
    @post('/update/execute/<status>')
    def execute_update(status):
        check_output('apt-get update {0}'.format(API.APT_CONFIG_STRING), shell=True)
        sdm_package_info = API._get_package_information(package_name=API.PACKAGE_NAME)
        if sdm_package_info[0] != sdm_package_info[1]:
            if status == 'started':
                print 'Updating package {0}'.format(API.PACKAGE_NAME)
                check_output('echo "apt-get install -y --force-yes {0}" > /tmp/update'.format(API.PACKAGE_NAME), shell=True)
                check_output('at -f /tmp/update now', shell=True)
                check_output('rm /tmp/update', shell=True)
            return {'status': 'running'}
        else:
            return {'status': 'done' if 'running' in check_output('status alba-asdmanager', shell=True).strip() else 'running'}

    @staticmethod
    @post('/update/restart_services')
    def restart_services():
        check_output('apt-get update {0}'.format(API.APT_CONFIG_STRING), shell=True)
        alba_package_info = API._get_package_information(package_name='alba')
        for service, running_version in API._get_sdm_services().iteritems():
            if running_version != alba_package_info[1]:
                print 'Restarting service {0}'.format(service)
                check_output('restart {0}'.format(service), shell=True)
        return {'restarted': True}
