#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2013 Robert Budde                       robert@projekt131.de
#########################################################################
#  Squeezebox-Plugin for SmartHomeNG.  https://github.com/smarthomeNG//
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
import urllib.request
import urllib.error
import urllib.parse
from lib.network import Tcp_client
import re
import time
from lib.model.smartplugin import SmartPlugin
from bin.smarthome import VERSION

class Squeezebox(SmartPlugin):
    ALLOW_MULTIINSTANCE = False
    PLUGIN_VERSION = "1.4.0"

    def __init__(self, smarthome):
        if '.'.join(VERSION.split('.', 2)[:2]) <= '1.5':
            self.logger = logging.getLogger(__name__)
        try:
            self._host = self.get_parameter_value('host')
            self._port = self.get_parameter_value('port')
            self._autoreconnect = self.get_parameter_value('autoreconnect')
            self._connect_retries = self.get_parameter_value('connect_retries')
            self._connect_cycle = self.get_parameter_value('connect_cycle')
            self._squeezebox_server_alive = False
            self._web_port = self.get_parameter_value('web_port')
            name = 'plugins.' + self.get_fullname()
            self._squeezebox_tcp_connection = Tcp_client(host=self._host,
                                                         port=self._port,
                                                         name=name,
                                                         autoreconnect=self._autoreconnect,
                                                         connect_retries=self._connect_retries,
                                                         connect_cycle=self._connect_cycle,
                                                         binary=True,
                                                         terminator=b'\r\n')
            self._squeezebox_tcp_connection.set_callbacks(connected=self._on_connect,
                                                          data_received=self._on_received_data,
                                                          disconnected=self._on_disconnect)
            self._val = {}
            self._obj = {}
            self._init_cmds = []
            self._listen = False
        except Exception:
            self._init_complete = False
            return


    def _check_mac(self, mac):
        return re.match("[0-9a-fA-F]{2}([:][0-9a-fA-F]{2}){5}", mac)

    def _resolv_full_cmd(self, item, attr):
        # check if PlayerID wildcard is used
        if self.has_iattr(item.conf[attr], '<playerid>'):
            # try to get from parent object
            parent_item = item.return_parent()
            if (parent_item is not None) and self.has_iattr(parent_item.conf, 'squeezebox_playerid') and self._check_mac(self.get_iattr_value(parent_item.conf, 'squeezebox_playerid')):
                item.conf[attr] = item.conf[attr].replace('<playerid>', self.get_iattr_value(parent_item.conf, 'squeezebox_playerid'))
            else:
                grandparent_item = parent_item.return_parent()
                if (grandparent_item is not None) and self.has_iattr(grandparent_item.conf, 'squeezebox_playerid') and self._check_mac(self.get_iattr_value(grandparent_item.conf, 'squeezebox_playerid')):
                    item.conf[attr] = item.conf[attr].replace('<playerid>', self.get_iattr_value(grandparent_item.conf, 'squeezebox_playerid'))
                else:
                    grandgrandparent_item = grandparent_item.return_parent()
                    if (grandgrandparent_item is not None) and self.has_iattr(grandgrandparent_item.conf, 'squeezebox_playerid') and self._check_mac(self.get_iattr_value(grandgrandparent_item.conf, 'squeezebox_playerid')):
                        item.conf[attr] = item.conf[attr].replace('<playerid>', self.get_iattr_value(grandgrandparent_item.conf, 'squeezebox_playerid'))
                    else:
                        self.logger.warning("could not resolve playerid for {0} from parent item {1}, neither from grandparent {2} or grandgrandparent {3}".format(item, parent_item, grandparent_item, grandgrandparent_item))
                        return None

        return item.conf[attr]

    def parse_item(self, item):
        if self.has_iattr(item.conf, 'squeezebox_recv'):
            cmd = self._resolv_full_cmd(item, 'squeezebox_recv')
            if (cmd is None):
                return None

            self.logger.debug("{0} receives updates by \"{1}\"".format(item, cmd))
            if not cmd in self._val:
                self._val[cmd] = {'items': [item], 'logics': []}
            else:
                if not item in self._val[cmd]['items']:
                    self._val[cmd]['items'].append(item)

        if self.has_iattr(item.conf, 'squeezebox_albumart'):
            playerid = self._resolv_full_cmd(item, 'squeezebox_albumart')
            if (playerid is None):
                return None
            url = 'http://{}:{}/music/current/cover.jpg?player={}'.format(self._host, self._web_port, playerid)
            item(url, 'LMS', 'parse')
            self.logger.debug("album art item {0} is set to \"{1}\"".format(item, url))

        if self.has_iattr(item.conf, 'squeezebox_init'):
            cmd = self._resolv_full_cmd(item, 'squeezebox_init')
            if (cmd is None):
                return None

            self.logger.debug("{0} is initialized by \"{1}\"".format(item, cmd))
            if not cmd in self._val:
                self._val[cmd] = {'items': [item], 'logics': []}
            else:
                if not item in self._val[cmd]['items']:
                    self._val[cmd]['items'].append(item)

            if not cmd in self._init_cmds:
                self._init_cmds.append(cmd)

        if self.has_iattr(item.conf, 'squeezebox_send'):
            cmd = self._resolv_full_cmd(item, 'squeezebox_send')
            if (cmd is None):
                return None
            self.logger.debug("{0} is sent to \"{1}\"".format(item, cmd))
            return self.update_item
        else:
            return None

    def parse_logic(self, logic):
        if self.has_iattr(logic.conf, 'squeezebox_playerid'):
            playerid = self.get_iattr_value(logic.conf, 'squeezebox_playerid')
            if not self._check_mac(playerid):
                self.logger.warning("invalid playerid for {0}".format(logic.name))
                return None
        else:
            playerid = 'playerid_not_set'
        if self.has_iattr(logic.conf, 'squeezebox_recv'):
            cmds = self.get_iattr_value(logic.conf, 'squeezebox_recv')
            if isinstance(cmds, str):
                cmds = [cmds, ]
            for cmd in cmds:
                cmd = cmd.replace('<playerid>', playerid)
                if not self._check_mac(cmd.split(maxsplit=1)[0]):
                    self.logger.warning("no valid playerid in \"{}\"".format(cmd))
                    continue
                self.logger.debug("{} will be triggered by \"{}\"".format(logic.name, cmd))
                if not cmd in self._val:
                    self._val[cmd] = {'items': [], 'logics': [logic]}
                else:
                    if not logic in self._val[cmd]['logics']:
                        self._val[cmd]['logics'].append(logic)
        else:
            return None

    def update_item(self, item, caller=None, source=None, dest=None):
        # be careful: as the server echoes ALL comands not using this will
        # result in a loop
        if caller != 'LMS':
            cmd = self._resolv_full_cmd(item, 'squeezebox_send').split()
            if not self._check_mac(cmd[0]):
                self.logger.debug("Command {0} does not include player_id. Is that on purpose?".format(cmd))
            value = item()
            if isinstance(value, bool):
                # convert to get '0'/'1' instead of 'True'/'False'
                value = int(value)

            # special handling for bool-types that need other commands or values
            # to behave intuitively
            if isinstance(source, str):
                newsource = source.split(".")[-1:][0]
            else:
                newsource = 'None'
            condition0 = len(cmd) > 1
            condition1 = condition0 and cmd[1] == 'playlist' and cmd[2] in ['shuffle', 'repeat']
            condition2 = condition0 and cmd[1] == 'playlist' and cmd[2] == 'shuffle' and caller == 'on_change' and newsource == 'shuffle'
            condition3 = condition0 and cmd[1] == 'playlist' and cmd[2] == 'repeat' and caller == 'on_change' and newsource == 'repeat'

            if (len(cmd) >= 2) and not item() and (condition2 or condition3):
                # If shuffle or playlist item got updates by on_change nothing should happen to prevent endless loops
                self.logger.debug("Command {0} ignored to prevent repeat/shuffle command loops".format(cmd))
                return
            if (len(cmd) >= 2) and not item():
                if (cmd[1] == 'play'):
                    # if 'play' was set to false, send 'pause' to allow
                    # single-item-operation
                    cmd[1] = 'pause'
                    value = 1
                if condition1:
                    # if a boolean item of [...] was set to false, send '0' to disable the option whatsoever
                    # replace cmd[3], as there are fixed values given and
                    # filling in 'value' is pointless
                    cmd[3] = '0'
            self._send(' '.join(urllib.parse.quote(cmd_str.format(value), encoding='iso-8859-1')
                       for cmd_str in cmd))

    def _send(self, cmd):
        if self._squeezebox_tcp_connection.connected():
            # replace german umlauts
            repl = (('%FC', '%C3%BC'), ('%F6', '%C3%B6'), ('%E4', '%C3%A4'), ('%DC', '%C3%9C'), ('%D6', '%C3%96'), ('%C4', '%C3%84'))
            for r in repl:
                cmd = cmd.replace(*r)
            i = 0
            while not cmd == "listen 1" and self._listen is False:
                self.logger.debug("Waiting to send command {} as connection is not yet established. Count: {}/10".format(cmd, i))
                i += 1
                time.sleep(1)
                if i >= 10:
                    self.logger.warning("10 seconds wait time for sending {} is over. Sending it now.".format(cmd))
                    break
            self.logger.debug("Sending request: {0}".format(cmd))
            self._squeezebox_tcp_connection.send(bytes(cmd + '\r\n', 'utf-8'))
        else:
            self.logger.warning("Can not send because squeezebox is not connected.")

    def _on_received_data(self, connection, response):
        data = [urllib.parse.unquote(data_str) for data_str in response.decode().split()]

        self.logger.debug("Got: {0}".format(data))

        try:
            if (data[0].lower() == 'listen'):
                value = int(data[1])
                if (value == 1):
                    self.logger.info("Listen-mode enabled")
                    self._listen = True
                    if self._init_cmds != []:
                        self.logger.debug('squeezebox: init read')
                        for cmd in self._init_cmds:
                            self._send(cmd)
                else:
                    self.logger.info("Listen-mode disabled. The plugin won't receive any info!")
                    self._listen = False

            if self._check_mac(data[0]):
                if (data[1] == 'time' and (data[2].startswith('+') or data[2].startswith('-'))):
                    self._send(data[0] + ' time ?')
                    return
                elif (data[1] == 'play'):
                    self._update_items_with_data([data[0], 'play', '1'])
                    self._update_items_with_data([data[0], 'stop', '0'])
                    self._update_items_with_data([data[0], 'pause', '0'])
                    self._update_items_with_data([data[0], 'mode', 'play'])
                    self._send(data[0] + ' time ?')
                    # play also overrules mute
                    self._update_items_with_data([data[0], 'mute', '0'])
                    return
                elif (data[1] == 'stop'):
                    self._update_items_with_data([data[0], 'play', '0'])
                    self._update_items_with_data([data[0], 'stop', '1'])
                    self._update_items_with_data([data[0], 'pause', '0'])
                    self._update_items_with_data([data[0], 'mode', 'stop'])
                    self._send(data[0] + ' time ?')
                    return
                elif (data[1] == 'pause'):
                    self._update_items_with_data([data[0], 'play', '0'])
                    self._update_items_with_data([data[0], 'stop', '0'])
                    self._update_items_with_data([data[0], 'pause', '1'])
                    self._update_items_with_data([data[0], 'mode', 'pause'])
                    self._send(data[0] + ' mixer muting ?')
                    self._send(data[0] + ' time ?')
                    return
                elif (data[1] == 'mode'):
                    self._update_items_with_data(
                        [data[0], 'play', str(data[2] == 'play')])
                    self._update_items_with_data(
                        [data[0], 'stop', str(data[2] == 'stop')])
                    self._update_items_with_data(
                        [data[0], 'pause', str(data[2] == 'pause')])
                    self._update_items_with_data([data[0], 'mode', data[2]])
                    # play also overrules mute
                    if (data[2] == 'play'):
                        self._update_items_with_data([data[0], 'mute', '0'])
                    return
                elif ((((data[1] == 'prefset') and (data[2] == 'server')) or (data[1] == 'mixer'))
                      and (data[-2] == 'volume') and data[-1].startswith('-')):
                    # make sure value is always positive - also if muted!
                    self._update_items_with_data([data[0], 'mute', '1'])
                    data[-1] = data[-1][1:]
                elif (data[1] == 'playlist'):
                    if (data[2] == 'play' and data[3] == '1'):
                        self._update_items_with_data([data[0], 'play', '1'])
                        self._update_items_with_data([data[0], 'stop', '0'])
                        self._update_items_with_data([data[0], 'pause', '0'])
                        self._update_items_with_data([data[0], 'mode', 'play'])
                        self._send(data[0] + ' time ?')
                        # play also overrules mute
                        self._update_items_with_data([data[0], 'mute', '0'])
                        return
                    elif (data[2] == 'stop'):
                        self._update_items_with_data([data[0], 'play', '0'])
                        self._update_items_with_data([data[0], 'stop', '1'])
                        self._update_items_with_data([data[0], 'pause', '0'])
                        self._update_items_with_data([data[0], 'mode', 'stop'])
                        self._send(data[0] + ' time ?')
                        return
                    elif (data[2] == 'pause' and data[3] == '1'):
                        self._update_items_with_data([data[0], 'play', '0'])
                        self._update_items_with_data([data[0], 'stop', '0'])
                        self._update_items_with_data([data[0], 'pause', '1'])
                        self._update_items_with_data([data[0], 'mode', 'pause'])
                        self._send(data[0] + ' mixer muting ?')
                        self._send(data[0] + ' time ?')
                        return
                    elif (data[2] == 'jump') and (len(data) == 4):
                        self._update_items_with_data(
                            [data[0], 'playlist index', data[3]])
                    elif (data[2] == 'name') and (len(data) <= 3):
                        self._update_items_with_data(
                                [data[0], 'playlist name', ''])
                    elif (data[2] == 'loadtracks'):
                        self._send(data[0] + ' playlist name ?')
                    elif (data[2] == 'newsong'):
                        self._send(data[0] + ' mode ?')
                        if (len(data) >= 4):
                            self._update_items_with_data(
                                [data[0], 'title', data[3]])
                        else:
                            self._send(data[0] + ' title ?')
                        if (len(data) >= 5):
                            self._update_items_with_data(
                                [data[0], 'playlist index', data[4]])
                        # trigger reading of other song fields
                        for field in ['genre', 'artist', 'album', 'duration']:
                            self._send(data[0] + ' ' + field + ' ?')
                elif (data[1] in ['genre', 'artist', 'album', 'title']) and (len(data) == 2):
                    # these fields are returned empty so update fails - append
                    # '' to allow update
                    data.append('')
                elif (data[1] in ['duration']) and (len(data) == 2):
                    # these fields are returned empty so update fails - append
                    # '0' to allow update
                    data.append('0')
            # finally check for '?'
            if (data[-1] == '?'):
                return
            self._update_items_with_data(data)
        except Exception as e:
            self.logger.error("exception while parsing \'{0}\'. Exception: {1}".format(data, e))

    def _update_items_with_data(self, data):
        cmd = ' '.join(data_str for data_str in data[:-1])

        if (cmd in self._val):

            for item in self._val[cmd]['items']:
                if re.match("[+-][0-9]+$", data[-1]) and not isinstance(item(), str):
                    data[-1] = int(data[-1]) + item()
                item(data[-1], 'LMS', self._host)
            for logic in self._val[cmd]['logics']:
                logic.trigger('squeezebox', cmd, data[-1])

    def _connect(self, by):
        '''
        Method to try to establish a new connection to squeezebox

        :note: While this method is called during the start-up phase of the plugin, it can also be used to establish a connection to the squeezebox server if the plugin was initialized before the server went up or the connection is interrupted.

        :param by: caller information
        :type by: str
        '''
        self.logger.debug('Initializing connection, initiated by {}'.format(by))
        if not self._squeezebox_tcp_connection.connected():
            self._squeezebox_tcp_connection.connect()
            # we allow for 2 seconds to connect
            time.sleep(2)
        if not self._squeezebox_tcp_connection.connected():
            # no connection could be established, squeezebox may be offline
            self.logger.info('Could not establish a connection to squeezebox at {}'.format(self._host))
            self._squeezebox_server_alive = False
        else:
            self._squeezebox_server_alive = True

    def _on_connect(self, by=None):
        '''
        Recall method for succesful connect to squeezebox
        On a connect first check if the JSON-RPC API is available.
        If this is the case query squeezebox to initialize all items

        :param by: caller information
        :type by: str
        '''
        self._squeezebox_server_alive = True
        if isinstance(by, (dict, Tcp_client)):
            by = 'TCP_Connect'
        self.logger.info('Connected to {}, onconnect called by {}.'.format(self._host, by))
        self._send('listen 1')

    def _on_disconnect(self, obj=None):
        '''
        Recall method for TCP disconnect
        '''
        self.logger.info('Received disconnect from {}'.format(self._host))
        self._squeezebox_server_alive = False

    def run(self):
        self.alive = True
        self._connect('run')
        self.logger.debug("run method called")

    def stop(self):
        self.alive = False
        self.logger.debug("stop method called")
        self._squeezebox_tcp_connection.close()
        self._squeezebox_server_alive = False

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(relativeCreated)6d %(threadName)s %(message)s')
    # todo
    # change PluginClassName appropriately
    PluginClassName(Squeezebox).run()
