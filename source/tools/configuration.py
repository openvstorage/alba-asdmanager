# Copyright 2015 CloudFounders NV
# All rights reserved

"""
Configuration related code
"""
from ConfigParser import RawConfigParser


class Configuration(object):
    filename = '/opt/alba-asdmanager/config/config.cfg'

    @staticmethod
    def get(key):
        section, item = key.split('.', 1)
        config = RawConfigParser()
        config.read(Configuration.filename)
        return config.get(section, item)

    @staticmethod
    def set(key, value):
        if isinstance(value, list):
            value = ','.join(value)
        section, item = key.split('.', 1)
        config = RawConfigParser()
        config.read(Configuration.filename)
        config.set(section, item, value)
        with open(Configuration.filename, 'w') as config_file:
            config.write(config_file)

    @staticmethod
    def get_list(key):
        value = Configuration.get(key)
        return [item.strip() for item in value.split(',') if item.strip() != '']
