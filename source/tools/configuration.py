# Copyright 2015 Open vStorage NV
# All rights reserved

"""
Configuration related code
"""

import json
from source.tools.filemutex import FileMutex


class Configuration(object):
    filename = '/opt/alba-asdmanager/config/config.json'

    def __init__(self):
        with open(Configuration.filename, 'r') as config_file:
            self.data = json.loads(config_file.read())
        self.mutex = FileMutex('config')

    def __enter__(self):
        self.mutex.acquire()
        return self

    def __exit__(self, *args, **kwargs):
        _ = args, kwargs
        try:
            with open(Configuration.filename, 'w') as config_file:
                config_file.write(json.dumps(self.data, indent=4))
        finally:
            self.mutex.release()

    def migrate(self):
        try:
            self.__enter__()
            version = self.data['main']['version']
            if version < 1:
                # No migrations in the initial version
                print 'Migrating configuration to version 1'
                version = 1
            if version < 2:
                # print 'Migrating configuration to version 2'
                # @TODO: in the future, here is where upgrades to the configuration file should be located
                # version = 2
                pass
            self.data['main']['version'] = version
        finally:
            self.__exit__()
