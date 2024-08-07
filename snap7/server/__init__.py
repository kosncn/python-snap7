"""
Snap7 server used for mimicking a siemens 7 server.
"""

import re
import time
from ctypes import (
    c_char,
    byref,
    sizeof,
    c_int,
    c_int32,
    c_uint32,
    c_void_p,
    CFUNCTYPE,
    POINTER,
)
from _ctypes import CFuncPtr
import struct
import logging
from typing import Any, Callable, Hashable, Optional, Tuple, cast, Type
from types import TracebackType

from ..common import ipv4, check_error, load_library
from ..protocol import Snap7CliProtocol
from ..types import SrvEvent, LocalPort, cpu_statuses, server_statuses, SrvArea, longword, WordLen, S7Object, CDataArrayType

logger = logging.getLogger(__name__)


def error_wrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Parses a s7 error code returned the decorated function."""

    def f(*args: tuple[Any, ...], **kwargs: dict[Hashable, Any]) -> None:
        code = func(*args, **kwargs)
        check_error(code, context="server")

    return f


class Server:
    """
    A fake S7 server.
    """

    _lib: Snap7CliProtocol
    _s7_server: S7Object
    _read_callback = None
    _callback: Optional[Callable[..., Any]] = None

    def __init__(self, log: bool = True):
        """Create a fake S7 server. set log to false if you want to disable
            event logging to python logging.

        Args:
            log: `True` for enabling the event logging. Optinoal.
        """
        self._lib: Snap7CliProtocol = load_library()
        self.create()
        if log:
            self._set_log_callback()

    def __enter__(self) -> "Server":
        return self

    def __exit__(
        self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]
    ) -> None:
        self.destroy()

    def __del__(self) -> None:
        self.destroy()

    def event_text(self, event: SrvEvent) -> str:
        """Returns a textual explanation of a given event object

        Args:
            event: an PSrvEvent struct object

        Returns:
            The error string
        """
        logger.debug(f"error text for {hex(event.EvtCode)}")
        len_ = 1024
        text_type = c_char * len_
        text = text_type()
        error = self._lib.Srv_EventText(byref(event), byref(text), len_)
        check_error(error)
        return text.value.decode("ascii")

    def create(self) -> None:
        """Create the server."""
        logger.info("creating server")
        self._lib.Srv_Create.restype = S7Object  # type: ignore[attr-defined]
        self._s7_server = S7Object(self._lib.Srv_Create())

    @error_wrap
    def register_area(self, area: SrvArea, index: int, userdata: CDataArrayType) -> int:
        """Shares a memory area with the server. That memory block will be
            visible by the clients.

        Args:
            area: memory area to register.
            index: number of area to write.
            userdata: buffer with the data to write.

        Returns:
            Error code from snap7 library.
        """
        size = sizeof(userdata)
        logger.info(f"registering area {area}, index {index}, size {size}")
        return self._lib.Srv_RegisterArea(self._s7_server, area.value, index, byref(userdata), size)

    @error_wrap
    def set_events_callback(self, call_back: Callable[..., Any]) -> int:
        """Sets the user callback that the Server object has to call when an
        event is created.
        """
        logger.info("setting event callback")
        callback_wrap: Callable[..., Any] = CFUNCTYPE(None, c_void_p, POINTER(SrvEvent), c_int)

        def wrapper(usrptr: Optional[c_void_p], pevent: SrvEvent, size: int) -> int:
            """Wraps python function into a ctypes function

            Args:
                usrptr: not used
                pevent: pointer to snap7 event struct
                size:

            Returns:
                Should return an int
            """
            logger.info(f"callback event: {self.event_text(pevent.contents)}")
            call_back(pevent.contents)
            return 0

        self._callback = cast(type[CFuncPtr], callback_wrap(wrapper))
        usrPtr = c_void_p()
        return self._lib.Srv_SetEventsCallback(self._s7_server, self._callback, usrPtr)

    @error_wrap
    def set_read_events_callback(self, call_back: Callable[..., Any]) -> int:
        """Sets the user callback that the Server object has to call when a Read
            event is created.

        Args:
            call_back: a callback function that accepts a pevent argument.
        """
        logger.info("setting read event callback")
        callback_wrapper: Callable[..., Any] = CFUNCTYPE(None, c_void_p, POINTER(SrvEvent), c_int)

        def wrapper(usrptr: Optional[c_void_p], pevent: SrvEvent, size: int) -> int:
            """Wraps python function into a ctypes function

            Args:
                usrptr: not used
                pevent: pointer to snap7 event struct
                size:

            Returns:
                Should return an int
            """
            logger.info(f"callback event: {self.event_text(pevent.contents)}")
            call_back(pevent.contents)
            return 0

        self._read_callback = callback_wrapper(wrapper)
        return self._lib.Srv_SetReadEventsCallback(self._s7_server, self._read_callback)

    def _set_log_callback(self) -> None:
        """Sets a callback that logs the events"""
        logger.debug("setting up event logger")

        def log_callback(event: SrvEvent) -> None:
            logger.info(f"callback event: {self.event_text(event)}")

        self.set_events_callback(log_callback)

    @error_wrap
    def start(self, tcpport: int = 102) -> int:
        """Starts the server.

        Args:
            tcpport: port that the server will listen. Optional.
        """
        if tcpport != 102:
            logger.info(f"setting server TCP port to {tcpport}")
            self.set_param(LocalPort, tcpport)
        logger.info(f"starting server on 0.0.0.0:{tcpport}")
        return self._lib.Srv_Start(self._s7_server)

    @error_wrap
    def stop(self) -> int:
        """Stop the server."""
        logger.info("stopping server")
        return self._lib.Srv_Stop(self._s7_server)

    def destroy(self) -> None:
        """Destroy the server."""
        logger.info("destroying server")
        if self._lib and self._s7_server is not None:
            return self._lib.Srv_Destroy(byref(self._s7_server))
        self._s7_server = None  # type: ignore[assignment]
        return None

    def get_status(self) -> Tuple[str, str, int]:
        """Reads the server status, the Virtual CPU status and the number of
            the clients connected.

        Returns:
            Server status, cpu status, client count
        """
        logger.debug("get server status")
        server_status = c_int()
        cpu_status = c_int()
        clients_count = c_int()
        error = self._lib.Srv_GetStatus(self._s7_server, byref(server_status), byref(cpu_status), byref(clients_count))
        check_error(error)
        logger.debug(f"status server {server_status.value} cpu {cpu_status.value} clients {clients_count.value}")
        return (server_statuses[server_status.value], cpu_statuses[cpu_status.value], clients_count.value)

    @error_wrap
    def unregister_area(self, area: SrvArea, index: int) -> int:
        """'Unshares' a memory area previously shared with Srv_RegisterArea().

        Notes:
            That memory block will be no longer visible by the clients.

        Args:
            area: memory area.
            index: number of the memory area.

        Returns:
            Error code from snap7 library.
        """
        return self._lib.Srv_UnregisterArea(self._s7_server, area.value, index)

    @error_wrap
    def unlock_area(self, area: SrvArea, index: int) -> int:
        """Unlocks a previously locked shared memory area.

        Args:
            area: memory area.
            index: number of the memory area.

        Returns:
            Error code from snap7 library.
        """
        logger.debug(f"unlocking area code {area} index {index}")
        return self._lib.Srv_UnlockArea(self._s7_server, area.value, index)

    @error_wrap
    def lock_area(self, area: SrvArea, index: int) -> int:
        """Locks a shared memory area.

        Args:
            area: memory area.
            index: number of the memory area.

        Returns:
            Error code from snap7 library.
        """
        logger.debug(f"locking area code {area} index {index}")
        return self._lib.Srv_LockArea(self._s7_server, area.value, index)

    @error_wrap
    def start_to(self, ip: str, tcp_port: int = 102) -> int:
        """Start server on a specific interface.

        Args:
            ip: IPV4 address where the server is located.
            tcp_port: port that the server will listen on.

        Raises:
            :obj:`ValueError`: if the `ivp4` is not a valid IPV4
        """
        if tcp_port != 102:
            logger.info(f"setting server TCP port to {tcp_port}")
            self.set_param(LocalPort, tcp_port)
        if not re.match(ipv4, ip):
            raise ValueError(f"{ip} is invalid ipv4")
        logger.info(f"starting server to {ip}:102")
        return self._lib.Srv_StartTo(self._s7_server, ip.encode())

    @error_wrap
    def set_param(self, number: int, value: int) -> int:
        """Sets an internal Server object parameter.

        Args:
            number: number of the parameter.
            value: value to be set.

        Returns:
            Error code from snap7 library.
        """
        logger.debug(f"setting param number {number} to {value}")
        return self._lib.Srv_SetParam(self._s7_server, number, byref(c_int(value)))

    @error_wrap
    def set_mask(self, kind: int, mask: int) -> int:
        """Writes the specified filter mask.

        Args:
            kind:
            mask:

        Returns:
            Error code from snap7 library.
        """
        logger.debug(f"setting mask kind {kind} to {mask}")
        return self._lib.Srv_SetMask(self._s7_server, kind, mask)

    @error_wrap
    def set_cpu_status(self, status: int) -> int:
        """Sets the Virtual CPU status.

        Args:
            status: :obj:`cpu_statuses` object type.

        Returns:
            Error code from snap7 library.

        Raises:
            :obj:`ValueError`: if `status` is not in :obj:`cpu_statuses`.
        """
        if status not in cpu_statuses:
            raise ValueError(f"The cpu state ({status}) is invalid")
        logger.debug(f"setting cpu status to {status}")
        return self._lib.Srv_SetCpuStatus(self._s7_server, status)

    def pick_event(self) -> Optional[SrvEvent]:
        """Extracts an event (if available) from the Events queue.

        Returns:
            Server event.
        """
        logger.debug("checking event queue")
        event = SrvEvent()
        ready = c_int32()
        code = self._lib.Srv_PickEvent(self._s7_server, byref(event), byref(ready))
        check_error(code)
        if ready:
            logger.debug(f"one event ready: {event}")
            return event
        logger.debug("no events ready")
        return None

    def get_param(self, number: int) -> int:
        """Reads an internal Server object parameter.

        Args:
            number: number of the parameter to be set.

        Returns:
            Value of the parameter.
        """
        logger.debug(f"retreiving param number {number}")
        value = c_int()
        code = self._lib.Srv_GetParam(self._s7_server, number, byref(value))
        check_error(code)
        return value.value

    def get_mask(self, kind: int) -> c_uint32:
        """Reads the specified filter mask.

        Args:
            kind:

        Returns:
            Mask
        """
        logger.debug(f"retrieving mask kind {kind}")
        mask = longword()
        code = self._lib.Srv_GetMask(self._s7_server, kind, byref(mask))
        check_error(code)
        return mask

    @error_wrap
    def clear_events(self) -> int:
        """Empties the Event queue.

        Returns:
            Error code from snap7 library.
        """
        logger.debug("clearing event queue")
        return self._lib.Srv_ClearEvents(self._s7_server)


def mainloop(tcpport: int = 1102, init_standard_values: bool = False) -> None:
    """Init a fake Snap7 server with some default values.

    Args:
        tcpport: port that the server will listen.
        init_standard_values: if `True` will init some defaults values to be read on DB0.
    """

    server = Server()
    size = 100
    DBdata: CDataArrayType = (WordLen.Byte.ctype * size)()
    PAdata: CDataArrayType = (WordLen.Byte.ctype * size)()
    TMdata: CDataArrayType = (WordLen.Byte.ctype * size)()
    CTdata: CDataArrayType = (WordLen.Byte.ctype * size)()
    server.register_area(SrvArea.DB, 1, DBdata)
    server.register_area(SrvArea.PA, 1, PAdata)
    server.register_area(SrvArea.TM, 1, TMdata)
    server.register_area(SrvArea.CT, 1, CTdata)

    if init_standard_values:
        ba = _init_standard_values()
        userdata = WordLen.Byte.ctype * len(ba)
        server.register_area(SrvArea.DB, 0, userdata.from_buffer(ba))

    server.start(tcpport=tcpport)
    while True:
        while True:
            event = server.pick_event()
            if event:
                logger.info(server.event_text(event))
            else:
                break
        time.sleep(1)


def _init_standard_values() -> bytearray:
    """Standard values
    * Boolean
    BYTE    BIT     VALUE
    0       0       True
    0       1       False
    0       2       True
    0       3       False
    0       4       True
    0       5       False
    0       6       True
    0       7       False

    * Small int
    BYTE    VALUE
    10      -128
    11      0
    12      100
    13      127

    * Unsigned small int
    BYTE    VALUE
    20      0
    21      255

    * Int
    BYTE    VALUE
    30      -32768
    32      -1234
    34      0
    36      1234
    38      32767

    * Double int
    BYTE    VALUE
    40      -2147483648
    44      -32768
    48      0
    52      32767
    56      2147483647

    * Real
    BYTE    VALUE
    60      -3.402823e38
    64      -3.402823e12
    68      -175494351e-38
    72      -1.175494351e-12
    76      0.0
    80      1.175494351e-38
    84      1.175494351e-12
    88      3.402823466e12
    92      3.402823466e38

    * String
    BYTE    VALUE
    100     254|37|the brown fox jumps over the lazy dog

    * Word
    BYTE    VALUE
    400     \x00\x00
    404     \x12\x34
    408     \xab\xcd
    412     \xff\xff

    * Double Word
    BYTE    VALUE
    500     \x00\x00\x00\x00
    508     \x12\x34\x56\x78
    516     \x12\x34\xab\xcd
    524     \xff\xff\xff\xff
    """

    ba = bytearray(1000)
    # 1. Bool 1 byte
    ba[0] = 0b10101010

    # 2. Small int 1 byte
    ba[10 : 10 + 1] = struct.pack(">b", -128)
    ba[11 : 11 + 1] = struct.pack(">b", 0)
    ba[12 : 12 + 1] = struct.pack(">b", 100)
    ba[13 : 13 + 1] = struct.pack(">b", 127)

    # 3. Unsigned small int 1 byte
    ba[20 : 20 + 1] = struct.pack("B", 0)
    ba[21 : 21 + 1] = struct.pack("B", 255)

    # 4. Int 2 bytes
    ba[30 : 30 + 2] = struct.pack(">h", -32768)
    ba[32 : 32 + 2] = struct.pack(">h", -1234)
    ba[34 : 34 + 2] = struct.pack(">h", 0)
    ba[36 : 36 + 2] = struct.pack(">h", 1234)
    ba[38 : 38 + 2] = struct.pack(">h", 32767)

    # 5. DInt 4 bytes
    ba[40 : 40 + 4] = struct.pack(">i", -2147483648)
    ba[44 : 44 + 4] = struct.pack(">i", -32768)
    ba[48 : 48 + 4] = struct.pack(">i", 0)
    ba[52 : 52 + 4] = struct.pack(">i", 32767)
    ba[56 : 56 + 4] = struct.pack(">i", 2147483647)

    # 6. Real 4 bytes
    ba[60 : 60 + 4] = struct.pack(">f", -3.402823e38)
    ba[64 : 64 + 4] = struct.pack(">f", -3.402823e12)
    ba[68 : 68 + 4] = struct.pack(">f", -175494351e-38)
    ba[72 : 72 + 4] = struct.pack(">f", -1.175494351e-12)
    ba[76 : 76 + 4] = struct.pack(">f", 0.0)
    ba[80 : 80 + 4] = struct.pack(">f", 1.175494351e-38)
    ba[84 : 84 + 4] = struct.pack(">f", 1.175494351e-12)
    ba[88 : 88 + 4] = struct.pack(">f", 3.402823466e12)
    ba[92 : 92 + 4] = struct.pack(">f", 3.402823466e38)

    # 7. String 1 byte per char
    string = "the brown fox jumps over the lazy dog"  # len = 37
    ba[100] = 254
    ba[101] = len(string)
    for letter, i in zip(string, range(102, 102 + len(string) + 1)):
        ba[i] = ord(letter)

    # 8. WORD 4 bytes
    ba[400 : 400 + 4] = b"\x00\x00"
    ba[404 : 404 + 4] = b"\x12\x34"
    ba[408 : 408 + 4] = b"\xab\xcd"
    ba[412 : 412 + 4] = b"\xff\xff"

    # # 9 DWORD 8 bytes
    ba[500 : 500 + 8] = b"\x00\x00\x00\x00"
    ba[508 : 508 + 8] = b"\x12\x34\x56\x78"
    ba[516 : 516 + 8] = b"\x12\x34\xab\xcd"
    ba[524 : 524 + 8] = b"\xff\xff\xff\xff"

    return ba
