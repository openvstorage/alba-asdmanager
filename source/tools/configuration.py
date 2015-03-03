# Copyright 2015 CloudFounders NV
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
                config_file.write(json.dumps(self.data, indent=2))
        finally:
            self.mutex.release()
