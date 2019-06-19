import re
import os
import time
import logging
from abc import abstractmethod
from distutils.version import LooseVersion
from subprocess import check_output
from ovs_extensions.generic.sshclient import SSHClient
from ovs_extensions.storage.persistent.pyrakoonstore import PyrakoonStore
from ovs_extensions.services.interfaces.systemd import SystemdUnitParser, SERVICE_DIR, SERVICE_SUFFIX
from ovs_extensions.update.base import ComponentUpdater as component_updater
from source.tools.persistentfactory import PersistentFactory
from source.tools.system import System
from source.tools.servicefactory import ServiceFactory
from StringIO import StringIO

logger = logging.getLogger(__name__)


class AlbaComponentUpdater(component_updater):
    """
    Implementation of abstract class to update alba
    """

    COMPONENT = 'alba'
    BINARIES = [('alba-ee', 'alba', '/usr/bin/alba')]  # List with tuples. [(package_name, binary_name, binary_location, [service_prefix_0]]

    alba_binary_base_path = '/opt'

    re_abm = re.compile('^ovs-arakoon.*-abm$')
    re_nsm = re.compile('^ovs-arakoon.*-nsm_[0-9]*$')
    re_alba_proxy = re.compile('^ovs-albaproxy_.*$')
    re_alba_binary = re.compile('^alba-[0-9.a-z]*$')
    re_alba_asd = re.compile('^alba-asd-[0-9a-zA-Z]{32}$')
    re_exec_start = re.compile('.* -config (?P<config>\S*) .*')
    re_alba_maintenance = re.compile('^alba-maintenance_.*-[0-9a-zA-Z]{16}$')

    SERVICE_MANAGER = ServiceFactory.get_manager()

    SERVICE_TEMPLATE = '{0}/{{0}}{1}'.format(SERVICE_DIR, SERVICE_SUFFIX)

    @staticmethod
    @abstractmethod
    def get_persistent_client():
        # type: () -> PyrakoonStore
        """
        Retrieve a persistent client which needs
        Needs to be implemented by the callee
        """
        return PersistentFactory.get_client()

    @classmethod
    def update_alternatives(cls):
        # type: () -> None
        """
        update the /etc/alternatives alba symlink to the most recent alba version.
        the alba in /usr/bin/alba is a symlink to file in /etc/alternatives, as set by ops or this function.
        the /etc/alternatives files are in turn a symlink to /opt/alba-*.
        The alternatives are used to be able to run multiple alba instances on the same node

        :return: None
        """
        version = max([LooseVersion(i) for i in os.listdir(cls.alba_binary_base_path) if cls.re_alba_binary.match(i)])
        check_output(['update-alternatives', '--set', 'alba', os.path.join('{0}/{1}'.format(cls.alba_binary_base_path, str(version)))])

    @classmethod
    def update_binaries(cls):
        # type: () -> None
        """
        Update the binary
        :return:
        """
        if cls.BINARIES is None:
            raise NotImplementedError('Unable to update packages. Binaries are not included')
        for package_name, _, _ in cls.BINARIES:
            logging.info('Updating {}'.format(package_name))
            cls.install_package(package_name)
            cls.update_alternatives()

    @classmethod
    def get_service_file_path(cls, name):
        # type: (str) -> str
        """
        Get the path to a service
        :param name: Name of the service
        :return: The path to the service file
        :rtype: str
        """
        return cls.SERVICE_TEMPLATE.format(name)

    @classmethod
    def get_arakoon_config_file(cls, service):
        # type: (str) -> str
        """
        Fetches the local file path of a given arakoon service, and parses the execstart configfile location
        :param service: ovs-arakoon.*
        :return: config file location
        """
        local_client = cls.get_local_root_client()

        file_path = cls.get_service_file_path(service)
        file_contents = local_client.file_read(file_path)
        parser = SystemdUnitParser()
        parser.readfp(StringIO(file_contents))
        try:
            execstart_rule = parser.get('Service', 'ExecStart')
            return cls.re_exec_start.search(execstart_rule).groupdict().get('config')
        except:
            raise RuntimeError('This execStart rule did not contain an execStart rule')

    @classmethod
    def restart_services(cls):
        # type: () -> None

        """
        Restart related services
        :return:
        """
        local_client = cls.get_local_root_client()
        node_id = System.get_my_machine_id()
        all_services = cls.SERVICE_MANAGER.list_services(local_client)

        # restart arakoons first, drop master if this node is master
        arakoon_services = [i for i in all_services if i.startswith('ovs-arakoon')]
        for service in arakoon_services:
            arakoon_config = cls.get_arakoon_config_file(service)
            if node_id == cls.get_arakoon_master(arakoon_config):
                cls.drop_arakoon_master()
            master_node = cls.get_arakoon_master(arakoon_config)
            if master_node:
                cls.SERVICE_MANAGER.restart_service(service, local_client)

        # restart other alba related services after making sure arakoons are ok
        maintenance_services = [i for i in all_services if cls.re_alba_maintenance.match(i)]
        for service in maintenance_services:
            cls.SERVICE_MANAGER.restart_service(service, local_client)
        abm_nsm_services = [i for i in all_services if cls.re_nsm.match(i) or cls.re_abm.match(i)]
        for service in abm_nsm_services:
            cls.SERVICE_MANAGER.restart_service(service, local_client)
        asd_services = [i for i in all_services if cls.re_alba_asd.match(i)]
        for service in asd_services:
            cls.SERVICE_MANAGER.restart_service(service, local_client)
        proxy_services = [i for i in all_services if cls.re_alba_proxy.match(i)]
        for service in proxy_services:
            cls.SERVICE_MANAGER.restart_service(service, local_client)

    @staticmethod
    def get_arakoon_master(arakoon_config_url, max_attempts=10):
        # type: (str) -> str
        """
        Fetches the master node id, based on the arakoon config url
        :param arakoon_config_url: str
        :return: str
        """
        attempt = 0
        while True:

            master = check_output(['arakoon', '--who-master', '-config', arakoon_config_url])
            attempt += 1

            if master:
                break
            if max_attempts == attempt:
                raise RuntimeError("Couldn't find arakoon master node after {0} attempts".format(max_attempts))

            time.sleep(5)
        return master

    @staticmethod
    def drop_arakoon_master():
        # type: () -> str
        """
        Drops the master node id, based on the arakoon config url
        :param arakoon_config_url: str
        :return: str
        """
        node_id = System.get_my_machine_id()
        return check_output(['arakoon', '--drop-master', node_id, '127.0.0.1', 'port'])

    @staticmethod
    def get_local_root_client():
        # type: () -> SSHClient
        """
        Return a local root client
        :return: The root client
        :rtype: SSHClient
        """
        return SSHClient('127.0.0.1', username='root')

if __name__ == '__main__':
    print AlbaComponentUpdater.restart_services()