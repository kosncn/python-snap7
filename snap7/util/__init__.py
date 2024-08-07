"""
This module contains utility functions for working with PLC DB objects.
There are functions to work with the raw bytearray data snap7 functions return
In order to work with this data you need to make python able to work with the
PLC bytearray data.

For example code see test_util.py and example.py in the example folder.


example::

    spec/DB layout

    # Byte index    Variable name  Datatype
    layout=\"\"\"
    4	          ID             INT
    6             NAME	         STRING[6]

    12.0          testbool1      BOOL
    12.1          testbool2      BOOL
    12.2          testbool3      BOOL
    12.3          testbool4      BOOL
    12.4          testbool5      BOOL
    12.5          testbool6      BOOL
    12.6          testbool7      BOOL
    12.7          testbool8      BOOL
    13            testReal       REAL
    17            testDword      DWORD
    \"\"\"

    client = snap7.client.Client()
    client.connect('192.168.200.24', 0, 3)

    # this looks confusing but this means uploading from the PLC to YOU
    # so downloading in the PC world :)

    all_data = client.upload(db_number)

    simple:

    db1 = snap7.util.DB(
        db_number,              # the db we use
        all_data,               # bytearray from the plc
        layout,                 # layout specification DB variable data
                                # A DB specification is the specification of a
                                # DB object in the PLC you can find it using
                                # the dataview option on a DB object in PCS7

        17+2,                   # size of the specification 17 is start
                                # of last value
                                # which is a DWORD which is 2 bytes,

        1,                      # number of row's / specifications

        id_field='ID',          # field we can use to identify a row.
                                # default index is used
        layout_offset=4,        # sometimes specification does not start a 0
                                # like in our example
        db_offset=0             # At which point in 'all_data' should we start
                                # reading. if could be that the specification
                                # does not start at 0
    )

    Now we can use db1 in python as a dict. if 'ID' contains
    the 'test' we can identify the 'test' row in the all_data bytearray

    To test of you layout matches the data from the plc you can
    just print db1[0] or db['test'] in the example

    db1['test']['testbool1'] = 0

    If we do not specify a id_field this should work to read out the
    same data.

    db1[0]['testbool1']

    to read and write a single Row from the plc. takes like 5ms!

    db1['test'].write()

    db1['test'].read(client)


"""

import re
from typing import Any
from collections import OrderedDict

from .db import (
    DB,
    DB_Row,
)

from .setters import (
    set_bool,
    set_fstring,
    set_string,
    set_real,
    set_dword,
    set_udint,
    set_dint,
    set_uint,
    set_int,
    set_word,
    set_byte,
    set_usint,
    set_sint,
    set_time,
)

from .getters import (
    get_bool,
    get_fstring,
    get_string,
    get_wstring,
    get_real,
    get_dword,
    get_udint,
    get_dint,
    get_uint,
    get_int,
    get_word,
    get_byte,
    get_s5time,
    get_dt,
    get_usint,
    get_sint,
    get_time,
    get_date,
    get_tod,
    get_lreal,
    get_char,
    get_wchar,
    get_dtl,
)


__all__ = [
    "get_bool",
    "get_real",
    "get_dword",
    "get_udint",
    "get_dint",
    "get_uint",
    "get_int",
    "get_word",
    "get_byte",
    "get_usint",
    "get_sint",
    "get_time",
    "get_date",
    "get_tod",
    "get_lreal",
    "get_char",
    "get_wchar",
    "get_dtl",
    "get_s5time",
    "get_dt",
    "get_fstring",
    "get_string",
    "get_wstring",
    "set_real",
    "set_dword",
    "set_udint",
    "set_dint",
    "set_uint",
    "set_int",
    "set_word",
    "set_byte",
    "set_usint",
    "set_sint",
    "set_time",
    "set_bool",
    "set_fstring",
    "set_string",
]


def parse_specification(db_specification: str) -> OrderedDict[str, Any]:
    """Create a db specification derived from a
        dataview of a db in which the byte layout
        is specified

    Args:
        db_specification: string formatted table with the indexes, aliases and types.

    Returns:
        Parsed DB specification.
    """
    parsed_db_specification = OrderedDict()

    for line in db_specification.split("\n"):
        if line and not line.lstrip().startswith("#"):
            index, var_name, _type = line.lstrip().split("#")[0].split()
            parsed_db_specification[var_name] = (index, _type)

    return parsed_db_specification


def print_row(data: bytearray) -> None:
    """print a single db row in chr and str"""
    index_line = ""
    pri_line1 = ""
    chr_line2 = ""
    asci = re.compile("[a-zA-Z0-9 ]")

    for i, xi in enumerate(data):
        # index
        if not i % 5:
            diff = len(pri_line1) - len(index_line)
            index_line += diff * " "
            index_line += str(i)
            # i = i + (ws - len(i)) * ' ' + ','

        # byte array line
        str_v = str(xi)
        pri_line1 += str(xi) + ","
        # char line
        c = chr(xi)
        c = c if asci.match(c) else " "
        # align white space
        w = len(str_v)
        c = c + (w - 1) * " " + ","
        chr_line2 += c

    print(index_line)
    print(pri_line1)
    print(chr_line2)
