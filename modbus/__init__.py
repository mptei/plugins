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

class Modbus(SmartPlugin):
    PLUGIN_VERSION = "0.0.0.1"
    ALLOW_MULTIINSTANCE = False

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
        self.my_reg_items = []
        self.mbitems = []
        self.addrmap = {}
        self.units = {}
        self._lockmb = threading.Lock()    # modbus serial port lock
        #self._sh.scheduler.add(__name__, self._read_modbus, prio=5, cycle=int(update_cycle))
        self.fun_dict = {'INPUT':0x04,'HOLDING':0x10}
        self.type_dict = {'INT16LE':1,'FP32LE':2}
        self.typeparser_dict = {'INT16LE':lambda x: x[0], 'FP32LE':lambda x: struct.unpack('>f',struct.pack('>HH',*x))[0]}

    # Called regularly to update modbus values
    def _read_modbus(self):
        self._lockmb.acquire()
        try:
            client = self.connect()
            for unit in self.units:
                funs = self.units[unit]
                for fun in funs:
                    addrs = funs[fun]
                    for addr in addrs:
                        mbitem = addrs[addr]
                        rq = None
                        if fun == 4:
                            rq = client.read_input_registers(addr, self.type_dict[mbitem.datatype], unit=unit)
                        elif fun == 16:
                            rq = client.read_holding_registers(addr, self.type_dict[mbitem.datatype], unit=unit)
                        if rq.isError():
                            self.logger.error('Failed to read input registers')
                            break
                        self.logger.debug('read')
                        value = self.typeparser_dict[mbitem.datatype](rq.registers)
                        for item in mbitem.items:
                            item(value, self.get_shortname(), "Modbus unit={}, addr={}".format(mbitem.unit, mbitem.addr))
                            

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
            if mbitem.datatype == 'INT16LE':
                self._write_modbus_int16le(int(item()), mbitem.unit, mbitem.addr)
    
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
                                                  lambda x: x.upper() in self.type_dict, 
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
                    addrs = funs[modbus_fun]
                    if modbus_regaddr in addrs:
                        mbitem = addrs[modbus_regaddr]
            if mbitem is not None:
                        if mbitem.datatype != modbus_type:
                            raise Exception('Only one data type allowed')
            else:
                mbitem = MBItem(modbus_unit, modbus_regaddr, modbus_type, modbus_fun)
                # append to dictionary
                if mbitem.unit in self.units:
                    funs = self.units[mbitem.unit]
                else:
                    funs = {}
                    self.units[mbitem.unit] = funs
                if mbitem.fun in funs:
                    addrs = funs[mbitem.fun]
                else:
                    addrs = {}
                    funs[mbitem.fun]=addrs
                addrs[mbitem.addr] = mbitem
            
            mbitem.items.append(item)
            return lambda item, caller, source, dest: self.update_item(item, mbitem, caller, source, dest)
            #return self.update_item2

        return None

    def _write_register_value(self, item, repeat_count=0):
        try:
            self.logger.debug('writing register value')
            if not self.has_iattr(item.conf, 'systemair_regaddr'):
                self.logger.error('Could not write to modbus. Register address missing!')
                return
        except Exception as err:
            self.logger.error('Could not write register value to modbus. Error: {err}!'.format(err=err))
            self.instrument = None

    def _write_modbus_int16le(self, value, modbus_unit, modbus_regaddr):
        self._write_modbus(modbus_unit, modbus_regaddr, value)
        
    def _write_modbus(self, unit, addr, values):
        self._lockmb.acquire()
        try:
            self.logger.debug('write to modbus')
            try:
                client = self.connect()
                client.write_registers(addr, values, unit=unit)
            except Exception as err:
                self.logger.error('Could not write register value to modbus. Error: {err}!'.format(err=err))
        finally:
            self._lockmb.release()
            
class MBItem:
    def __init__(self, unit, addr, datatype, fun):
        self.unit = unit
        self.addr = addr
        self.fun = fun
        self.datatype = datatype
        self.items = []

