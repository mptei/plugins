#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Modbus plugin for SmartHomeNG.       https://github.com/smarthomeNG//
#
#  This plugin is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This plugin is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this plugin. If not, see <http://www.gnu.org/licenses/>.
#########################################################################
import logging
import threading
import struct
from lib.model.smartplugin import SmartPlugin
from pymodbus.client.sync import ModbusTcpClient, ModbusSerialClient
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.payload import Endian

# Class holding information about type
class MBType:
    def __init__(self, name, wordlen, decoder, encoder):
        self.name = name
        self.wordlen = wordlen
        self.decoder = decoder
        self.encoder = encoder

    def decode(self, raw):
        return self.decoder(raw)

    def encode(self, value):
        return self.encoder(value)

class Range:
    def __init__(self, start, end):
        self.start = start
        self.end = end

class Modbus(SmartPlugin):
    PLUGIN_VERSION = "0.0.0.1"
    ALLOW_MULTIINSTANCE = False
    types = {
             'INT16LE': MBType('INT16LE', 1, lambda x: x[0], lambda x: [x]),
             'FP32LE': MBType('FP32LE', 2, lambda x: struct.unpack('>f',struct.pack('>HH',*x))[0], lambda x: struct.unpack('>HH', struct.pack('>f', *x)))
            }

    def __init__(self, smarthome, connection, port="", update_cycle="30"):
        self._sh = smarthome
        self.logger = logging.getLogger(__name__)
        self.connection = connection
        self.port = port
        if port is not None and int(port) > 0:
            self.connect = lambda : ModbusTcpClient (connection, port=int(port))
        else:
            self.connect = lambda : ModbusSerialClient (method="rtu", port=connection, baudrate=9600, stopbits=1, bytesize=8, timeout=1)
            
        self._cycle = int(update_cycle)
        self.units = {}
        self._lockmb = threading.Lock()    # modbus serial port lock
        self.fun_dict = {'INPUT':0x04,'HOLDING':0x10}
        self._sh.scheduler.add(__name__, self._read_modbus, prio=5, cycle=int(update_cycle))

    # Called regularly to update modbus values
    def _read_modbus(self):
        self._lockmb.acquire()
        try:
            for unit in self.units:
                funs = self.units[unit]
                for fun in funs:
                    client = self.connect()
                    (mbitems,ranges) = funs[fun]
                    for myrange in ranges:
                        regcnt = myrange.end - myrange.start
                        rq = None
                        if fun == 4:
                            rq = client.read_input_registers(myrange.start, regcnt, unit=unit)
                        elif fun == 16:
                            rq = client.read_holding_registers(myrange.start, regcnt, unit=unit)
                        if rq.isError():
                            self.logger.error('Failed to read input registers')
                            break
                        addr = myrange.start
                        step = mbitems[0].mbtype.wordlen
                        registers = rq.registers
                        while addr < myrange.end:
                            # Create sub list for decode
                            subreg = []
                            for i in range(step):
                                subreg.append(registers.pop(0))
                            # Find matching item
                            matches = [x for x in mbitems if x.addr == addr]
                            if len(matches) == 1:
                                mbitem = matches[0]
                                value = mbitem.mbtype.decode(subreg)
                                for item in mbitem.items:
                                    item(value, self.get_shortname(), "Modbus unit={}, addr={}".format(mbitem.unit, mbitem.addr))
                            addr += step

        except Exception as err:
            self.logger.error(err)
        finally:
            self._lockmb.release()

    def run(self):
        self.logger.debug("Plugin '{}': run method called".format(self.get_fullname()))
        # setup scheduler for device poll loop
        self._sh.scheduler.add(__name__, self._read_modbus, prio=5, cycle=self._cycle)
        #self.scheduler.add(__name__, self._read_modbus, prio=5, cycle=self._cycle)
        self.alive = True

    def stop(self):
        self.logger.debug("Plugin '{}': stop method called".format(self.get_fullname()))
        self.alive = False

    def update_item(self, item, mbitem, caller=None, source=None, dest=None):
        # ignore values from bus
        if caller != self.get_shortname():
            if mbitem.fun == 0x10:
                self._write_modbus_holding(mbitem.unit, mbitem.addr, mbitem.mbtype.encode(item()))
    
    def _read_parm(self, item, parmname, validator, converter):
        raw = self.get_iattr_value(item.conf, parmname)
        if raw is None:
            return None
        if not validator(raw):
            raise Exception('The value "'+raw+'" is not valid')
        return converter(raw)
    
    def _check_parm(self, item, parmname, parm):
        if parm is None:
            self.logger.error(parmname + ' must been given')
            raise Exception(parmname + ' must been given')

    def parse_item(self, item):
        raw = self.get_iattr_value(item.conf, 'modbus_reg')
        if raw is not None:
            # This is a modbus item
            modbus_regaddr = int(raw)
            # walk upwards until we have all modbus parms
            modbus_unit = None
            modbus_type =None
            modbus_fun = None
            itemSearch = item
            while ((modbus_unit is None or modbus_type is None or modbus_fun is None) and hasattr(itemSearch, 'conf')):
                if modbus_unit is None:
                    modbus_unit = self._read_parm(itemSearch, 'modbus_unit',
                                                   lambda x: True,
                                                   lambda x: int(x))
                if modbus_type is None:
                    modbus_type = self._read_parm(itemSearch, 'modbus_type', 
                                                  lambda x: x.upper() in Modbus.types, 
                                                  lambda x: x)
                if modbus_fun is None:
                    modbus_fun = self._read_parm(itemSearch, 'modbus_fun',
                                                   lambda x: x.upper() in self.fun_dict,
                                                   lambda x: self.fun_dict[x.upper()])
                itemSearch = itemSearch.return_parent()
            self._check_parm(item, 'modbus_unit', modbus_unit)
            if modbus_type is None:
                modbus_type = 'INT16LE'
            if modbus_fun is None:
                modbus_fun = 4
            self.logger.debug("modbus: {0} connected to register {1:#04x} on unit {2}".format(item, modbus_regaddr, modbus_unit))
            
            # Check if this address is already used
            mbitem = None
            if modbus_unit in self.units:
                funs = self.units[modbus_unit]
                if modbus_fun in funs:
                    (mbitems,ranges) = funs[modbus_fun]
                    matches = [x for x in mbitems if x.addr == modbus_regaddr]
                    if len(matches) == 1:
                        mbitem = matches[0]
            if mbitem is not None:
                        if mbitem.mbtype.name != modbus_type:
                            raise Exception('Only one data type allowed')
            else:
                mbitem = MBItem(modbus_unit, modbus_regaddr, Modbus.types[modbus_type], modbus_fun)
                # append to dictionary
                if mbitem.unit in self.units:
                    funs = self.units[mbitem.unit]
                else:
                    funs = {}
                    self.units[mbitem.unit] = funs
                if mbitem.fun in funs:
                    (mbitems,ranges) = funs[mbitem.fun]
                else:
                    mbitems = []
                    ranges = []
                    funs[mbitem.fun]=(mbitems,ranges)
                mbitems.append(mbitem)
                # Look to extend a range at end
                matches = [x for x in ranges if x.end == mbitem.addr]
                if len(matches) == 1:
                    matches[0].end += mbitem.mbtype.wordlen
                else:
                    # Look to extend range at start
                    matches = [x for x in ranges if x.start == mbitem.addr+mbitem.mbtype.wordlen]
                    if len(matches) == 1:
                        matches[0].start = mbitem.addr
                    else:
                        ranges.append(Range(mbitem.addr, mbitem.addr+mbitem.mbtype.wordlen))
            
            mbitem.items.append(item)
            return lambda item, caller, source, dest: self.update_item(item, mbitem, caller, source, dest)
            #return self.update_item2

        return None

    def _write_modbus_holding(self, unit, addr, values):
        self._lockmb.acquire()
        try:
            self.logger.debug('write to modbus')
            try:
                client = self.connect()
                rp = client.write_registers(addr, values, unit=unit)
                if rp.isError():
                    raise Exception('Here')
            except Exception as err:
                self.logger.error('Could not write register value to modbus. Error: {err}!'.format(err=err))
        finally:
            self._lockmb.release()

# Class holding information about a modbus item            
class MBItem:
    def __init__(self, unit, addr, mbtype, fun):
        self.unit = unit
        self.addr = addr
        self.fun = fun
        self.mbtype = mbtype
        self.items = []

# Class holding information about modbus Unit
class MBUnit:
    def __init__(self, unit):
        self.unit = unit
        
