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
This package contains the DAL list engine
"""

from source.dal.base import Base


class DataList(object):
    """
    The DataList class contains method(s) to query the underlying SQLite database.
    """

    @staticmethod
    def query(object_type, query, parameters=None):
        """
        This is a basic query wrapper that exposes a few "user friendly" features:
        * Translates relations to their internal fields:
          `SELECT disk_id FROM asd WHERE asd_id=?` => `SELECT _disk_id FROM asd WHERE asd_id=?`
        * Table translation (only for the table of the given object type):
          `SELECT id FROM {table} WHERE name=?` => `SELECT id FROM disk WHERE name=?`

        A few remarks/limitations:
        * This isn't written (nor meant to be) very efficient. It requires the query to return the primary key(s) of
          the  objects to return and will execute a separate query to fetch the actual data and yield the object.
        * While the DAL supports more complex objects like `list` and `dict`, these are serialized into JSON, and should
          be queried as such. E.g. a list property might contains ['foo', 'bar'], but when executing queries, keep in
          mind the DB's content will be '["bar","foo"].

        :param object_type: The object type to return
        :param query: The SQLite compatibly query
        :param parameters: SQLite compatible query parameters
        :return: Yields instances of the given object type
        """
        if parameters is None:
            parameters = []
        query = query.format(table=object_type._table)
        for relation in object_type._relations:
            query = query.replace('{0}_id'.format(relation[0]),
                                  '_{0}_id'.format(relation[0]))
        with Base.connector() as connection:
            cursor = connection.cursor()
            result = cursor.execute(query, parameters)
            for row in result.fetchall():
                yield object_type(row[0])
