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
Fleetctl module
"""
import time
from subprocess import check_output

try:
    import fleet.v1 as fleet
    FLEET_CLIENT = fleet.Client('http+unix://%2Fvar%2Frun%2Ffleet.sock')
except ImportError:
    raise ImportError('Fleet python client is not installed. Please check documentation on how to install it')

from .systemd import Systemd



class FleetCtl(object):
    """
    Contains all logic related to managing services through fleet
    """

    @staticmethod
    def prepare_template(base_name, target_name, client):
        return Systemd.prepare_template(base_name, target_name, client)

    @staticmethod
    def add_service(name, client, params=None, target_name=None, additional_dependencies=None):
        """
        This will generate a .service (temporary) file to feed to fleet to start a service
         service will become "name@<client.ip>.service"
        """
        if params is None:
            params = {}
        if additional_dependencies is None:
            additional_dependencies = []
        client_ip = FleetCtl._get_client_ip(client)

        if FleetCtl.has_service(name, client):
            print('Not re-adding service {0} to machine {1}'.format(name, client_ip))
            return

        name = Systemd._get_name(name, client, '/opt/OpenvStorage/config/templates/systemd/')
        template_service = '/opt/OpenvStorage/config/templates/systemd/{0}.service'

        if not client.file_exists(template_service.format(name)):
            # Given template doesn't exist so we are probably using system
            # init scripts
            return

        template_file = client.file_read(template_service.format(name))

        for key, value in params.iteritems():
            template_file = template_file.replace('<{0}>'.format(key), value)
        if '<SERVICE_NAME>' in template_file:
            service_name = name if target_name is None else target_name
            template_file = template_file.replace('<SERVICE_NAME>', service_name.lstrip('ovs-'))

        dependencies = ''
        for service in additional_dependencies:
            dependencies += '{0}.service '.format(service)
        template_file = template_file.replace('<ADDITIONAL_DEPENDENCIES>', dependencies)


        template_file += "\n[X-Fleet]\nMachineID={0}".format(FleetCtl._get_id_from_ip(client_ip))
        fleet_name = "{0}@{1}.service".format(name, client_ip)

        print('Creating fleet unit {0} {1}'.format(fleet_name, template_file))
        unit = FleetCtl._create_unit(fleet_name, template_file)
        time.sleep(1)
        FLEET_CLIENT.set_unit_desired_state(unit, 'loaded')
        time.sleep(1)
        unit = FleetCtl._get_unit(fleet_name)
        print('Created unit {0}'.format(unit.as_dict()))

    @staticmethod
    def get_service_status(name, client):
        if FleetCtl._has_service(name, client):
            fleet_name = FleetCtl._get_unit_name(name, client)
            unit = FleetCtl._get_unit(fleet_name)
            print('Fleet unit {0} status {1}'.format(fleet_name, unit.as_dict()['currentState']))
            return unit.as_dict()['currentState'] == 'launched'
        return Systemd.get_service_status(name, client)

    @staticmethod
    def remove_service(name, client):
        if FleetCtl._has_service(name, client):
            fleet_name = FleetCtl._get_unit_name(name, client)
            unit = FleetCtl._get_unit(fleet_name)
            FleetCtl.stop_service(name, client)
            result = FLEET_CLIENT.destroy_unit(unit)
            start = time.time()
            print('Fleet destroy unit {0} {1}'.format(fleet_name, result))
            while time.time() - start < 60:
                time.sleep(1)
                if FleetCtl._has_service(name, client) is False:
                    return
            print('Failed to remove unit {0} after 60 seconds'.format(fleet_name))
        return Systemd.remove_service(name, client)

    @staticmethod
    def disable_service(name, client):
        fleet_name = FleetCtl._get_unit_name(name, client)
        return Systemd.disable_service(fleet_name, client)

    @staticmethod
    def enable_service(name, client):
        fleet_name = FleetCtl._get_unit_name(name, client)
        return Systemd.enable_service(fleet_name, client)

    @staticmethod
    def start_service(name, client):
        if FleetCtl._has_service(name, client):
            fleet_name = FleetCtl._get_unit_name(name, client)
            start = time.time()
            while time.time() - start < 60:
                unit = FLEET_CLIENT.get_unit(fleet_name)
                if unit.as_dict()['currentState'] != 'launched':
                    FLEET_CLIENT.set_unit_desired_state(unit, 'launched')
                    time.sleep(1)
                else:
                    break
            unit = FleetCtl._get_unit(fleet_name)
            if unit.as_dict()['currentState'] != 'launched':
                print('Failed to start unit {0}'.format(unit.as_dict()))
            print('Fleet start unit {0} > {1}'.format(fleet_name, unit.as_dict()['currentState']))
            return unit.as_dict()['currentState']
        return Systemd.stop_service(name, client)

    @staticmethod
    def stop_service(name, client):
        if FleetCtl._has_service(name, client):
            fleet_name = FleetCtl._get_unit_name(name, client)
            start = time.time()
            while time.time() - start < 60:
                unit = FleetCtl._get_unit(fleet_name)
                if unit.as_dict()['currentState'] != 'loaded':
                    FLEET_CLIENT.set_unit_desired_state(unit, 'loaded')
                    time.sleep(1)
                else:
                    break
            unit = FleetCtl._get_unit(fleet_name)
            if unit['currentState'] != 'loaded':
                print('Failed to stop unit {0}'.format(unit.as_dict()))
            print('Fleet stop unit {0} {1}'.format(fleet_name, unit.as_dict()['currentState']))
            return unit.as_dict()['currentState']
        return Systemd.stop_service(name, client)

    @staticmethod
    def restart_service(name, client):
        if not FleetCtl._has_service(name, client):
            return Systemd.restart_service(name, client)
        FleetCtl.stop_service(name, client)
        FleetCtl.start_service(name, client)
        return FleetCtl.get_service_status(name, client)

    @staticmethod
    def _has_service(name, client):
        fleet_name = FleetCtl._get_unit_name(name, client)
        try:
            FleetCtl._get_unit(fleet_name)
            return True
        except (ValueError, RuntimeError):
            return False

    @staticmethod
    def has_service(name, client):
        fleet_has_service = FleetCtl._has_service(name, client)
        if not fleet_has_service:
            return Systemd.has_service(name, client)
        return fleet_has_service

    @staticmethod
    def is_enabled(name, client):
        return Systemd.is_enabled(name, client)

    @staticmethod
    def get_service_pid(name, client):
        return Systemd.get_service_pid(name, client)

    @staticmethod
    def _list_fleet_machines():
        return FLEET_CLIENT.list_machines()

    @staticmethod
    def _get_client_ip(client):
        if client.ip == '127.0.0.1':
            ips = check_output("ip a | grep 'inet ' | sed 's/\s\s*/ /g' | cut -d ' ' -f 3 | cut -d '/' -f 1", shell=True).split('\n')
            fleet_machines = dict((m['primaryIP'], m['id']) for m in FLEET_CLIENT.list_machines())
            match = set(fleet_machines.keys()).intersection(set(ips))
            if len(match) == 1:
                return match[0]
            raise ValueError('Could not determine a match between this node and running fleet nodes')
        return client.ip

    @staticmethod
    def _get_id_from_ip(ip):
        for machine in FleetCtl._list_fleet_machines():
            if machine['primaryIP'] == ip:
                return machine['id']
        raise ValueError('Fleet machine with ip {0} not found. Make sure "fleet" service is running.'.format(ip))

    @staticmethod
    def _get_unit(fleet_name):
        try:
            return FLEET_CLIENT.get_unit(fleet_name)
        except fleet.APIError as ae:
            print('Unit {0} not found. {1}'.format(fleet_name, ae))
            if ae.code == 404:
                # make error more descriptive
                raise ValueError('Unit with name {0} not found'.format(fleet_name))
            raise RuntimeError('Fleet API error {0}'.format(ae))

    @staticmethod
    def _get_unit_name(name, client):
        name = Systemd._get_name(name, client, '/opt/OpenvStorage/config/templates/systemd/')
        client_ip = FleetCtl._get_client_ip(client)
        fleet_name = "{0}@{1}.service".format(name, client_ip)
        return fleet_name

    @staticmethod
    def _create_unit(fleet_name, template_file):
        from source.tools.configuration import EtcdConfiguration
        start = time.time()
        while time.time() - start < 60:
            try:
                unit = FLEET_CLIENT.create_unit(fleet_name, fleet.Unit(from_string=template_file))
                return unit
            except fleet.APIError as ae:
                if ae.code == 500:
                    print('API Error in fleet, most likely caused by etcd, retrying. {0}'.format(ae))
                    key = '/_coreos.com/fleet/job/{0}/object'.format(fleet_name)
                    if EtcdConfiguration.exists(key):
                        EtcdConfiguration.delete(key)
                    time.sleep(1)
                else:
                    raise
        raise RuntimeError('Failed to create ')

    @staticmethod
    def list_service_files(client):
        client_ip = FleetCtl._get_client_ip(client)
        for unit in FLEET_CLIENT.list_units():
            unit_ = unit.as_dict()
            unit_name = unit_['name']
            suffix = '{0}.service'.format(client_ip)
            if unit_name.ensdwith(suffix):
                yield unit_name.replace(suffix, '')



