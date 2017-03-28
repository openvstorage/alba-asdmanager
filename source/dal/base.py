# Copyright (C) 2017 iNuron NV
#
# This file is part of Open vStorage Open Source Edition (OSE),
# as available from
#
#      http://www.openvstorage.org and
#      http://www.openvstorage.com.
#
# This file is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License v3 (GNU AGPLv3)
# as published by the Free Software Foundation, in version 3 as it comes
# in the LICENSE.txt file of the Open vStorage OSE distribution.
#
# Open vStorage is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY of any kind.

"""
This package contains the DAL object's base class.
"""

import json
import sqlite3
from source.dal.relations import RelationMapper


class ObjectNotFoundException(Exception):
    """ Exception indicating that an object in the DAL was not found. """
    pass


class Base(object):
    """
    Base object that is inherited by all DAL objects. It contains base logic like save, delete, ...
    """

    DATABASE_LOCATION = '/opt/asd-manager/db/main.db'

    _table = None
    _properties = []
    _relations = []
    _dynamics = []

    def __init__(self, identifier=None):
        """
        Initializes a new object. If no identifier is passed in, a new one is created.
        :param identifier: Optional identifier (primary key)
        :type identifier: int
        """
        self.id = identifier
        self.__class__._ensure_table()
        with Base.connector() as connection:
            if identifier is not None:
                cursor = connection.cursor()
                cursor.execute('SELECT * FROM {0} WHERE id=?'.format(self._table), [self.id])
                row = cursor.fetchone()
                if row is None:
                    raise ObjectNotFoundException()
                for prop in self._properties:
                    setattr(self, prop[0], Base._deserialize(prop[1], row[prop[0]]))
                for relation in self._relations:
                    setattr(self, '_{0}'.format(relation[0]), {'id': row['_{0}_id'.format(relation[0])],
                                                               'object': None})
            else:
                for prop in self._properties:
                    setattr(self, prop[0], None)
                for relation in self._relations:
                    setattr(self, '_{0}'.format(relation[0]), {'id': None,
                                                               'object': None})
        for relation in self._relations:
            self._add_relation(relation)
        for key, relation_info in RelationMapper.load_foreign_relations(self.__class__).iteritems():
            self._add_foreign_relation(key, relation_info)
        for key in self._dynamics:
            self._add_dynamic(key)

    @staticmethod
    def connector():
        """ Creates and returns a new connection to SQLite. """
        connection = sqlite3.connect(Base.DATABASE_LOCATION)
        connection.row_factory = sqlite3.Row
        return connection

    def _add_dynamic(self, key):
        """ Generates a new dynamic value on an object. """
        setattr(self.__class__, key, property(lambda s: getattr(s, '_{0}'.format(key))()))

    def _add_foreign_relation(self, key, relation_info):
        """ Generates a new foreign relation on an object. """
        setattr(self.__class__, key, property(lambda s: s._get_foreign_relation(relation_info)))

    def _get_foreign_relation(self, relation_info):
        """ Getter logic for a foreign relation. """
        remote_class = relation_info['class']
        with Base.connector() as connection:
            cursor = connection.cursor()
            cursor.execute('SELECT id FROM {0} WHERE _{1}_id=?'.format(remote_class._table, relation_info['key']),
                           [self.id])
            for row in cursor.fetchall():
                yield remote_class(row['id'])

    def _add_relation(self, relation):
        """ Generates a new relation on an object. """
        setattr(self.__class__, relation[0], property(lambda s: s._get_relation(relation),
                                                      lambda s, v: s._set_relation(relation, v)))
        setattr(self.__class__, '{0}_id'.format(relation[0]), property(lambda s: s._get_relation_id(relation)))

    def _get_relation(self, relation):
        """ Getter for a relation. """
        data = getattr(self, '_{0}'.format(relation[0]))
        if data['object'] is None and data['id'] is not None:
            data['object'] = relation[1](data['id'])
        return data['object']

    def _set_relation(self, relation, value):
        """ Setter for a relation. """
        data = getattr(self, '_{0}'.format(relation[0]))
        if value is None:
            data['id'] = None
            data['object'] = None
        else:
            data['id'] = value.id
            data['object'] = value

    def _get_relation_id(self, relation):
        """ Getter for a relation identifier. """
        return getattr(self, '_{0}'.format(relation[0]))['id']

    def save(self):
        """
        Saves the current object. If not existing, it is created and the identifier field is filled.
        :return: None
        """
        prop_values = [Base._serialize(prop[1], getattr(self, prop[0])) for prop in self._properties] + \
                      [getattr(self, '_{0}'.format(relation[0])).get('id') for relation in self._relations]
        if self.id is None:
            field_names = ', '.join([prop[0] for prop in self._properties] +
                                    ['_{0}_id'.format(relation[0]) for relation in self._relations])
            prop_statement = ', '.join('?' for _ in self._properties + self._relations)
            with Base.connector() as connection:
                cursor = connection.cursor()
                cursor.execute('INSERT INTO {0}({1}) VALUES ({2})'.format(self._table, field_names, prop_statement),
                               prop_values)
                self.id = cursor.lastrowid
        else:
            prop_statement = ', '.join(['{0}=?'.format(prop[0]) for prop in self._properties] +
                                       ['_{0}_id=?'.format(relation[0]) for relation in self._relations])
            with Base.connector() as connection:
                connection.execute('UPDATE {0} SET {1} WHERE id=? LIMIT 1'.format(self._table, prop_statement),
                                   prop_values + [self.id])

    def delete(self):
        """
        Deletes the current object from the SQLite database.
        :return: None
        """
        with Base.connector() as connection:
            connection.execute('DELETE FROM {0} WHERE id=? LIMIT 1'.format(self._table), [self.id])

    @staticmethod
    def _get_prop_type(prop_type):
        """ Translates a python type to a SQLite type. """
        if prop_type in [int, bool]:
            return 'INTEGER'
        if prop_type in [str, basestring, unicode, list, dict]:
            return 'TEXT'
        raise ValueError('The type {0} is not supported. Supported types: int, str, list, dict, bool'.format(prop_type))

    @staticmethod
    def _deserialize(prop_type, data):
        """ Deserializes a SQLite field to a python type. """
        if prop_type in [int, str, basestring, unicode]:
            return data
        if prop_type in [list, dict]:
            return json.loads(data)
        if prop_type in [bool]:
            return data == 1
        raise ValueError('The type {0} is not supported. Supported types: int, str, list, dict, bool'.format(prop_type))

    @staticmethod
    def _serialize(prop_type, data):
        """ Serializes a python type to a SQLite field. """
        if prop_type in [int, str, basestring, unicode]:
            return data
        if prop_type in [list, dict]:
            return json.dumps(data, sort_keys=True)
        if prop_type in [bool]:
            return 1 if data else 0
        raise ValueError('The type {0} is not supported. Supported types: int, str, list, dict, bool'.format(prop_type))

    @classmethod
    def _ensure_table(cls):
        type_statement = ', '.join(
            ['{0} {1}'.format(prop[0], Base._get_prop_type(prop[1])) for prop in cls._properties] +
            ['_{0}_id INTEGER'.format(relation[0]) for relation in cls._relations]
        )
        type_statement = 'id INTEGER PRIMARY KEY AUTOINCREMENT, {0}'.format(type_statement)
        with Base.connector() as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS {0} ({1})'.format(cls._table, type_statement))

    def __repr__(self):
        """ Short representation of the object. """
        return '<{0} (id: {1}, at: {2})>'.format(self.__class__.__name__, self.id, hex(id(self)))

    def __str__(self):
        """ Returns a full representation of the object. """
        data = {'id': self.id}
        for prop in self._properties:
            data[prop[0]] = getattr(self, prop[0])
        for relation in self._relations:
            name = '{0}_id'.format(relation[0])
            data[name] = getattr(self, name)
        for dynamic in self._dynamics:
            data[dynamic] = getattr(self, dynamic)
        return json.dumps(data, indent=4, sort_keys=True)
