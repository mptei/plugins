#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2020-      Martin Sinn                         m.sinn@gmx.de
#########################################################################
#  This file is part of SmartHomeNG.
#  https://www.smarthomeNG.de
#  https://knx-user-forum.de/forum/supportforen/smarthome-py
#
#  Sample plugin for new plugins to run with SmartHomeNG version 1.5 and
#  upwards.
#
#  SmartHomeNG is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  SmartHomeNG is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with SmartHomeNG. If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################

from typing import Any, Callable, Dict, List
from pyeasee import Easee, Charger, Site
from pyeasee.charger import ChargerConfig
from pyeasee.const import ChargerStreamData, EqualizerStreamData, DatatypesStreamData
import aiohttp
import json

from lib.model.smartplugin import *
from lib.item import Items

from .webif import WebInterface

import asyncio
from cryptography.fernet import Fernet
import base64
import threading
import collections
import time
from enum import Enum

# Constants
REFRESHER = "refresh_from_easee_cloud"

ID = "id"
TYPE = "type"
FUNCTION = "function"
CHARGER = 'charger'
ITEM = "item"

CONFATTRS = [ID, TYPE, FUNCTION]
ATTRPRF = 'easee_'

# Helper to find the data id enum
IDDICT = {
    'charger': lambda a : ChargerStreamDataEx[a],
    'equalizer': lambda a : EqualizerStreamData[a].value
}

ChargerStreamDataEx = {  **{k:v.value for k,v in ChargerStreamData.__members__.items()},
    'config_lockCablePermanently': ChargerStreamData.state_lockCablePermanently.value,
    'config_limitToSinglePhaseCharging': ChargerStreamData.config_enable3PhasesDEPRECATED.value,
    'state_latestPulse': 1000,
    'state_voltage': 1001,
    'state_isOnline': 1002,
    'state_latestFirmware': 1003,
    'state_offlineMaxCircuitCurrentP1': 1004,
    'state_offlineMaxCircuitCurrentP2': 1005,
    'state_offlineMaxCircuitCurrentP3': 1006,
    'state_errorCode': ChargerStreamData.ErrorCode.value,
}

# If a needed package is imported, which might be not installed in the Python environment,
# add it to a requirements.txt file within the plugin's directory

class EaseeCloud(SmartPlugin):
    """
    Main class of the Plugin. Does all plugin specific stuff and provides
    the update functions for the items
    """

    PLUGIN_VERSION = '0.0.1'    # (must match the version specified in plugin.yaml)

    easee = None               # object for communication with the cloud
    sites = []
    _chargers = []              # a list with simple dicts of the charger
    cloud_state = {}            # current status of cloud
    updates = collections.deque(maxlen=128) # updates from cloud; keep some of them for reporting
    updid = 0

    def __init__(self, sh):
        """
        Initalizes the plugin.

        If you need the sh object at all, use the method self.get_sh() to get it. There should be almost no need for
        a reference to the sh object any more.

        Plugins have to use the new way of getting parameter values:
        use the SmartPlugin method get_parameter_value(parameter_name). Anywhere within the Plugin you can get
        the configured (and checked) value for a parameter by calling self.get_parameter_value(parameter_name). It
        returns the value in the datatype that is defined in the metadata.
        """

        # Call init code of parent class (SmartPlugin)
        super().__init__()

        keyFile = sh.get_basedir() + "/var/cache/fernetkey"
        if os.path.isfile(keyFile):
            keyFileSize = os.stat(keyFile).st_size
            if keyFileSize > 60:
                raise Exception("Fernet key file \"{}\" has unusual size: {}".format(keyFile, keyFileSize))
            with open(keyFile,mode='rb') as file:
                key = file.read()
        else:
            # Create a new keyfile
            key = Fernet.generate_key()
            with open(keyFile,mode='wb') as file:
                file.write(key)
            self.logger.warning("Created a new key file. All existing encrypted values are lost")

        self._fernet = Fernet(key)

        # get the parameters for the plugin (as defined in metadata plugin.yaml):
        self.credentials = self.get_parameter_value('credentials')
        if self.credentials:
            try:
                self.credentials = self._fernet.decrypt(base64.decodebytes(self.credentials.encode('utf-8'))).decode('utf-8')
            except Exception as decryptErr:
                self.logger.warning("Credentials decryption faled: {}".format(repr(decryptErr)))
                self.credentials = ''
        if self.credentials and not len(self.credentials.split('\n')) == 2:
            self.logger.warning("Credentials in invalid format!")
            self.credentials = ''

        # polled for value changes by adding a scheduler entry in the run method of this plugin
        self._cycle_cloud = self.get_parameter_value('polltime')

        self._loop = asyncio.new_event_loop()
        self._lock = threading.Lock()

        # dict to store information about items handled by this plugin
        self.plugin_items = {}

        # lookup dict to find the items joined to the easee information item
        # first level is product id, next is data id
        self._reverse = {}

        self.init_webinterface(WebInterface)

        return

    def run(self):
        """
        Run method for the plugin
        """
        self.logger.debug("Run method called")

        # deamon thread for asyncio
        threading.Thread(target=self._async_thread, args=(self._loop,), daemon=True, name="easee_loop_executor").start()

        try:
            self.login()
            self._updateFromCloud()
        except Exception as err:
            self.logger.info("Login failed: {}".format(err))

        # setup scheduler for device poll loop   (disable the following line, if you don't need to poll the device. Rember to comment the self_cycle statement in __init__ as well)
        self.scheduler_add(REFRESHER, self._updateFromCloud, cycle=self._cycle_cloud)

        self.alive = True
        # if you need to create child threads, do not make them daemon = True!
        # They will not shutdown properly. (It's a python bug)

    def stop(self):
        """
        Stop method for the plugin
        """
        self.logger.debug("Stop method called")
        self.scheduler_remove(REFRESHER)
        self.alive = False
        self.logout()
        self._loop.call_soon_threadsafe(self._loop.stop)

    def parse_item(self, item):
        """
        Default plugin parse_item method. Is called when the plugin is initialized.
        The plugin can, corresponding to its attribute keywords, decide what to do with
        the item in future, like adding it to an internal array for future reference
        :param item:    The item to process.
        :return:        If the plugin needs to be informed of an items change you should return a call back function
                        like the function update_item down below. An example when this is needed is the knx plugin
                        where parse_item returns the update_item function when the attribute knx_send is found.
                        This means that when the items value is about to be updated, the call back function is called
                        with the item, caller, source and dest as arguments and in case of the knx plugin the value
                        can be sent to the knx with a knx write function within the knx plugin.
        """
        conf_data = {k:v for k, v in [[cfgKey, self.get_iattr_value(item.conf, ATTRPRF+cfgKey)] for cfgKey in CONFATTRS] if v}
        if conf_data:
            self.logger.debug("parse item: {}".format(item))
            if len(conf_data) != len(CONFATTRS):
                if item.type() != 'foo':
                    self.logger.warning("Item {} is only partially configured for easee. Ignored".format(item.path())) 
                return
            conf_data[ITEM] = item

            # Determine if it is an easee data point
            try:
                data_id = IDDICT[conf_data[TYPE]](conf_data[FUNCTION])
                self.plugin_items[item.id()] = conf_data
                self._reverse.setdefault(conf_data[ID], {}).setdefault(data_id,[]).append(item)
                # try to find an update method; only possible for changable data points
                return self._determineUpdateMethod(data_id, conf_data)
            except KeyError as e:
                pass

            # Determine if this corresponds to a function
            try:
                method = None
                if conf_data[FUNCTION] == 'startCharging':
                    method = lambda item, caller=None, source=None, dest=None: self._updateChargerItem(item, caller, conf_data, lambda charger, val : asyncio.run_coroutine_threadsafe(charger.start(), self._loop).result())
                elif conf_data[FUNCTION] == 'pauseCharging':
                    method = lambda item, caller=None, source=None, dest=None: self._updateChargerItem(item, caller, conf_data, lambda charger, val : asyncio.run_coroutine_threadsafe(charger.pause(), self._loop).result())
                elif conf_data[FUNCTION] == 'resumeCharging':
                    method = lambda item, caller=None, source=None, dest=None: self._updateChargerItem(item, caller, conf_data, lambda charger, val : asyncio.run_coroutine_threadsafe(charger.resume(), self._loop).result())
                elif conf_data[FUNCTION] == 'stopCharging':
                    method = lambda item, caller=None, source=None, dest=None: self._updateChargerItem(item, caller, conf_data, lambda charger, val : asyncio.run_coroutine_threadsafe(charger.stop(), self._loop).result())
                if method is None:
                    raise KeyError(conf_data[FUNCTION])
                self.plugin_items[item.id()] = conf_data
                return method
            except KeyError as e:
                self.logger.warning("Wrong easee configuration in item {}. Term \"{}\" is not understood. Item ignored!".format(item.path(), e.args[0]))
                return
        return

    def _determineUpdateMethod(self, data_id:int, conf_data:Dict) -> Callable:
        if data_id == ChargerStreamData.config_maxChargerCurrent.value:
            return lambda item, caller=None, source=None, dest=None: self._updateChargerItem(item, caller, conf_data, lambda charger, val : asyncio.run_coroutine_threadsafe(charger.set_max_charger_current(val), self._loop).result())
        if data_id == ChargerStreamData.state_dynamicChargerCurrent.value:
            return lambda item, caller=None, source=None, dest=None: self._updateChargerItem(item, caller, conf_data, lambda charger, val : asyncio.run_coroutine_threadsafe(charger.set_dynamic_charger_current(val), self._loop).result())
        if data_id == ChargerStreamData.config_ledStripBrightness.value:
            return lambda item, caller=None, source=None, dest=None: self._updateChargerItem(item, caller, conf_data, lambda charger, val : asyncio.run_coroutine_threadsafe(self._charger_setLedStripeBrightness(charger.id, val), self._loop).result())
        if data_id == ChargerStreamData.config_isEnabled.value:
            return lambda item, caller=None, source=None, dest=None: self._updateChargerItem(item, caller, conf_data, lambda charger, val : asyncio.run_coroutine_threadsafe(charger.enable_charger(val), self._loop).result())
        if data_id == ChargerStreamData.state_dynamicCircuitCurrentP1.value:
            return lambda item, caller=None, source=None, dest=None: self._updateChargerItem(item, caller, conf_data, lambda charger, val : asyncio.run_coroutine_threadsafe(charger.set_dynamic_charger_circuit_current(val), self._loop).result())
        return self._update_readonly_item

    def _updateChargerItem(self, item, caller, config, func):
        if self.alive and caller != self.get_shortname():
            charger = config.get(CHARGER, None)
            if charger is not None:
                func(charger, item())

    def _update_readonly_item(self, item, caller=None, source=None, dest=None):
        if self.alive and caller != self.get_shortname():
            self.logger.warning("item {} represents a read-only value. Change request ignored! (Caller={},Source={})".format(item.id(),caller,source))

    def parse_logic(self, logic):
        """
        Default plugin parse_logic method
        """
        if 'xxx' in logic.conf:
            # self.function(logic['name'])
            pass

    def update_item(self, item, caller=None, source=None, dest=None):
        """
        Item has been updated

        This method is called, if the value of an item has been updated by SmartHomeNG.
        It should write the changed value out to the device (hardware/interface) that
        is managed by this plugin.

        :param item: item to be updated towards the plugin
        :param caller: if given it represents the callers name
        :param source: if given it represents the source
        :param dest: if given it represents the dest
        """
        if self.alive and caller != self.get_shortname():

            # code to execute if the plugin is not stopped
            # and only, if the item has not been changed by this this plugin:
            self.logger.info("update_item: {} has been changed by caller {} outside this plugin".format(item.id(), caller))
        return

    def update_plugin_config(self):
        """
        Update the plugin configuration of this plugin in ../etc/plugin.yaml

        Fill a dict with all the parameters that should be changed in the config file
        and call the Method update_config_section()
        """
        conf_dict = {}
        conf_dict['credentials'] = base64.encodebytes(self._fernet.encrypt(self.credentials.encode('utf-8'))).decode('utf-8')
        self.update_config_section(conf_dict)
        return

    # ============================================================================================

    def _async_thread(self, loop):
        asyncio.set_event_loop(loop)
        loop.run_forever()

    async def _initEasee(self, user, pwd):
        return Easee(user, pwd)

    def login(self, user=None, pwd=None, store=False) -> None:
        if user is None and pwd is None and self.credentials:
            user, pwd = self.credentials.split('\n')
        if user is None or not user or pwd is None or not pwd:
            raise Exception({'title':"Login failed", 'detail':"Missing user credentials"})
        self.easee = asyncio.run_coroutine_threadsafe(self._initEasee(user,pwd), self._loop).result()
        asyncio.run_coroutine_threadsafe(self.easee.connect(), self._loop).result()

        if store:
            self.credentials = user + '\n' + pwd
            self.update_plugin_config()
    
    def logout(self, store=False) -> None:
        if self.easee is not None:
            asyncio.run_coroutine_threadsafe(self.easee.close(), self._loop).result()
            self.easee = None
            if store:
                self.credentials = ''
                self.update_plugin_config()

    def getChargers(self) -> List[Dict]:
        if self.easee is None:
            return []
        with self._lock:
            return self._chargers
    
    def getCloudState(self) -> Dict:
        return self.cloud_state.get('status', {'description': "Unknown", 'indicator': 'none'})

    def getEaseeUser(self) -> str:
        return self.credentials.split('\n')[0] if self.credentials else ''
    
    def _getDatatypeName(self, data_type: int) -> str:
        """Returns the clear name for the given data type"""
        try:
            return DatatypesStreamData(data_type).name
        except:
            return "Unknown {}".format(data_type)
    
    def _getDataName(self, data_id: int) -> str:
        """Returns the clear name for the given data id"""
        try:
            return ChargerStreamData(data_id).name
        except:
            return "Unknown {}".format(data_id)

    def getUpdates(self) -> Dict:
        """Delivers SignalR updates in a readyble format"""
        return [{'time':k['time'],'id':k['id'],'data_type':self._getDatatypeName(k['data_type']),'data_id':self._getDataName(k['data_id']),'value':k['value']} for k in self.updates]

    def _getChargerConfig(self, charger : Charger) -> Dict[str,Any]:
        return asyncio.run_coroutine_threadsafe(charger.get_config(raw=True), self._loop).result().get_data()

    def _getChargerState(self, charger : Charger) -> Dict[str,Any]:
        return asyncio.run_coroutine_threadsafe(charger.get_state(raw=True), self._loop).result().get_data()

    def _updateFromCloud(self) -> None:
        if self.easee is None:
            return
        self.cloud_state = asyncio.run_coroutine_threadsafe(self._get_cloud_state(), self._loop).result()
        newChargers = []
        for site in asyncio.run_coroutine_threadsafe(self.easee.get_sites(), self._loop).result():
            for circuit in site.get_circuits():
                for charger in circuit.get_chargers():
                    asyncio.run_coroutine_threadsafe(self.easee.sr_subscribe(charger, self._stream_callback), self._loop).result()
                    # Connect charger with config
                    for item_conf in self.plugin_items.values():
                        if item_conf[ID] == charger.id and not CHARGER in item_conf:
                            item_conf[CHARGER] = charger
                    # Update config items
                    cfg = self._getChargerConfig(charger)
                    for k,v in cfg.items():
                        try:
                            self._updateItems(charger.id, ChargerStreamDataEx['config_'+k], v, 'Poll')
                        except KeyError as err:
                            self.logger.debug("Unknown item in config: {} = {}".format(k, v))
                            pass
                    # Update state items
                    state = self._getChargerState(charger)
                    for k,v in state.items():
                        try:
                            self._updateItems(charger.id, ChargerStreamDataEx['state_'+k], v, 'Poll')
                        except KeyError as err:
                            self.logger.debug("Unknown item in state: {} = {}".format(k, v))
                            pass

                    newChargers.append({"id":charger.id, "name": charger.name, "firm": state.get("chargerFirmware"),
                                        "maxa": cfg.get("maxChargerCurrent"),
                                        "site": site.name, "maxac": circuit.get("ratedCurrent")})
        with self._lock:
            self._chargers = newChargers
    
    def _updateItems(self, id : str, data_id : int, value : Any, source : str) -> None:
        # Find items to be updated
        for item in self._reverse.get(id,{}).get(data_id,[]):
            item(value, self.get_shortname(), source)

    async def _stream_callback(self, id : str, data_type : int, data_id : int, value : Any) -> None:
        """Callback to be called from SignalR receiver """
        if True:
            # Hint: Time is used as an id by writing a running number in the milliseconds space
            self.updid = (self.updid + 1) % 1000
            self.updates.append({'time':int(time.time())*1000+self.updid,'id':id,'data_type':data_type,'data_id':data_id,'value':value})
        self._updateItems(id, data_id, value, 'SignalR')

    async def _charger_setLedStripeBrightness(self, id:str, value: int):
        """Set the brightness of the led stripe """
        jsonStr = {"ledStripBrightness": value}
        return await self.easee.post(f"/api/chargers/{id}/settings", json=jsonStr)

    async def _get_cloud_state(self):
        """Delivers the state of the easee cloud"""
        async with aiohttp.ClientSession() as session:
            async with session.get('https://easee.statuspage.io/api/v2/status.json') as resp:
                return json.loads(await resp.text())
