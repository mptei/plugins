#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2020-     <AUTHOR>                                   <EMAIL>
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

import datetime
import time
import os

from lib.item import Items
from lib.model.smartplugin import SmartPluginWebIf
import json

# ------------------------------------------
#    Webinterface of the plugin
# ------------------------------------------

import cherrypy
import csv
from jinja2 import Environment, FileSystemLoader


class WebInterface(SmartPluginWebIf):

    def __init__(self, webif_dir, plugin):
        """
        Initialization of instance of class WebInterface

        :param webif_dir: directory where the webinterface of the plugin resides
        :param plugin: instance of the plugin
        :type webif_dir: str
        :type plugin: object
        """
        self.logger = plugin.logger
        self.webif_dir = webif_dir
        self.plugin = plugin
        self.items = Items.get_instance()

        self.tplenv = self.init_template_environment()


    @cherrypy.expose
    def index(self, scan=None, connect=None, disconnect=None, reload=None):
        """
        Build index.html for cherrypy

        Render the template and return the html file to be delivered to the browser

        :return: contents of the template after beeing rendered
        """

        try:
            tmpl = self.tplenv.get_template('index.html')
        except Exception as err:
            self.logger.error("Loading template file 'index.html' failed: {}".format(err))
        else:
            # add values to be passed to the Jinja2 template eg: tmpl.render(p=self.plugin, interface=interface, ...)
            return tmpl.render(p=self.plugin,
                               items=self.plugin.plugin_items,
                               item_count=len(self.plugin.plugin_items),
                               easee_user=self.plugin.getEaseeUser(),
                               easee=self.plugin,
                               cloud_cycle=self.plugin._cycle_cloud)


    @cherrypy.expose
    def get_data_html(self, dataSet=None):
        """
        Return data to update the webpage

        For the standard update mechanism of the web interface, the dataSet to return the data for is None

        :param dataSet: Dataset for which the data should be returned (standard: None)
        :return: dict with the data needed to update the web page.
        """
        data = {}
        if dataSet is None:
            # get the new data
            data['cloud'] = self.plugin.getCloudState()
            data['chargers'] = self.plugin.getChargers()
            data['account'] = {'loggedIn':self.plugin.easee is not None}
            data['signalr'] = self.plugin.getUpdates()
            data['items'] = [{'idx':idx,'value':item['item']()} for idx,item in enumerate(self.plugin.plugin_items.values(),start=1)]
            # data['item'] = {}
            # for i in self.plugin.items:
            #     data['item'][i]['value'] = self.plugin.getitemvalue(i)
            #
        # return it as json the the web page
        try:
            return json.dumps(data)
        except Exception as e:
            self.logger.error("get_data_html exception: {}".format(e))
            return json.dumps({'error':True, 'title':'Enconding failed','text':repr(e)})

    def _createErrorDict(self, error):
        if isinstance(error,Exception) and error.args:
            try:
                data = error.args[0]
                return {'error':True,'title':data['title'],'text':data['detail']}
            except Exception as nextErr:
                # ignore if it was not json
                pass
        return {'error':True, 'title':'Error occured','text':repr(error)}

    @cherrypy.expose
    def submit(self, cmd=None):
        '''
        Submit handler für Ajax
        '''
        result = None

        if cmd is not None:

            # handle data
            try:
                data = json.loads(cmd)
                result_dict = {}
                for k,v in data.items():
                    if k == 'login':
                        self.plugin.login(v['user'], v['pass'], store=v['store'])
                        result_dict = self.get_data_html()
                    elif k == 'logout':
                        self.plugin.logout()
                        result_dict = self.get_data_html()
            except Exception as err:
                self.logger.info("Login failed: {}".format(repr(err)))
                result_dict = self._createErrorDict(err)

        if result_dict is not None:
            # JSON zurücksenden
            cherrypy.response.headers['Content-Type'] = 'application/json'
            return json.dumps(result_dict).encode('utf-8')
