#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2014-     Thomas Ernst                       offline@gmx.net
#########################################################################
#  Finite state machine plugin for SmartHomeNG
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
from .StateEngineLogger import SeLogger
from . import StateEngineItem
from . import StateEngineCurrent
from . import StateEngineDefaults
from . import StateEngineTools
from . import StateEngineCliCommands
from . import StateEngineFunctions
from . import StateEngineWebif
import logging
import os
from lib.model.smartplugin import *
from bin.smarthome import VERSION
from lib.item import Items


class StateEngine(SmartPlugin):
    PLUGIN_VERSION = '1.7.3'

    # Constructor
    # noinspection PyUnusedLocal,PyMissingConstructor
    def __init__(self, sh):
        super().__init__()
        if '.'.join(VERSION.split('.', 2)[:2]) <= '1.5':
            self.logger = logging.getLogger(__name__)
        self.items = Items.get_instance()
        self.__items = self.abitems = {}
        self.__sh = sh
        self.alive = False
        self.__cli = None
        self.init_webinterface()
        self.__log_directory = self.get_parameter_value("log_directory")
        try:
            log_level = self.get_parameter_value("log_level")
            log_directory = self.__log_directory
            self.logger.info("Init StateEngine (log_level={0}, log_directory={1})".format(log_level, log_directory))

            StateEngineDefaults.startup_delay = self.get_parameter_value("startup_delay_default")
            StateEngineDefaults.suspend_time = self.get_parameter_value("suspend_time_default")
            StateEngineDefaults.instant_leaveaction = self.get_parameter_value("instant_leaveaction")
            StateEngineDefaults.write_to_log(self.logger)

            StateEngineCurrent.init(self.get_sh())

            if log_level > 0:
                base = self.get_sh().get_basedir()
                log_directory = SeLogger.create_logdirectory(base, log_directory)
                text = "StateEngine extended logging is active. Logging to '{0}' with loglevel {1}."
                self.logger.info(text.format(log_directory, log_level))
            log_maxage = self.get_parameter_value("log_maxage")
            if log_maxage > 0:
                self.logger.info("StateEngine extended log files will be deleted after {0} days.".format(log_maxage))
                SeLogger.set_logmaxage(log_maxage)
                cron = ['init', '30 0 * *']
                self.scheduler_add('StateEngine: Remove old logfiles', SeLogger.remove_old_logfiles, cron=cron, offset=0)
            SeLogger.set_loglevel(log_level)
            SeLogger.set_logdirectory(log_directory)
            self.get_sh().stateengine_plugin_functions = StateEngineFunctions.SeFunctions(self.get_sh(), self.logger)
        except Exception:
            self._init_complete = False
            return

    # Parse an item
    # noinspection PyMethodMayBeStatic
    def parse_item(self, item):
        try:
            item.expand_relativepathes('se_item_*', '', '')
        except Exception:
            pass
        if self.has_iattr(item.conf, "se_manual_include") or self.has_iattr(item.conf, "se_manual_exclude"):
            item._eval = "sh.stateengine_plugin_functions.manual_item_update_eval('" + item.id() + "', caller, source)"
        elif self.has_iattr(item.conf, "se_manual_invert"):
            item._eval = "not sh." + item.id() + "()"
        if self.has_iattr(item.conf, "se_log_level"):
            base = self.get_sh().get_basedir()
            SeLogger.create_logdirectory(base, self.__log_directory)
        return None

    # Initialization of plugin
    def run(self):
        # Initialize
        self.logger.info("Init StateEngine items")
        for item in self.items.find_items("se_plugin"):
            if item.conf["se_plugin"] == "active":
                try:
                    abitem = StateEngineItem.SeItem(self.get_sh(), item, self)
                    self.__items[abitem.id] = abitem
                except ValueError as ex:
                    self.logger.error("Problem with Item: {0}: {1}".format(item.property.path, ex))

        if len(self.__items) > 0:
            self.logger.info("Using StateEngine for {} items".format(len(self.__items)))
        else:
            self.logger.info("StateEngine deactivated because no items have been found.")

        self.__cli = StateEngineCliCommands.SeCliCommands(self.get_sh(), self.__items, self.logger)
        #self.logger.info("Items: {}".format(self.__items))
        self.alive = True
        self.get_sh().stateengine_plugin_functions.ab_alive = True

    # Stopping of plugin
    def stop(self):
        self.logger.debug("stop method called")
        self.scheduler_remove('StateEngine: Remove old logfiles')
        for item in self.__items:
            self.scheduler_remove('{}'.format(item))
            self.scheduler_remove('{}-Startup Delay'.format(item))
            self.__items[item].remove_all_schedulers()

        self.alive = False

    # Determine if caller/source are contained in changed_by list
    # caller: Caller to check
    # source: Source to check
    # changed_by: List of callers/source (element format <caller>:<source>) to check against
    def is_changed_by(self, caller, source, changed_by):
        original_caller, original_source = StateEngineTools.get_original_caller(self.get_sh(), caller, source)
        for entry in changed_by:
            entry_caller, __, entry_source = entry.partition(":")
            if (entry_caller == original_caller or entry_caller == "*") and (
                            entry_source == original_source or entry_source == "*"):
                return True
        return False

    # Determine if caller/source are not contained in changed_by list
    # caller: Caller to check
    # source: Source to check
    # changed_by: List of callers/source (element format <caller>:<source>) to check against
    def not_changed_by(self, caller, source, changed_by):
        original_caller, original_source = StateEngineTools.get_original_caller(self.get_sh(), caller, source)
        for entry in changed_by:
            entry_caller, __, entry_source = entry.partition(":")
            if (entry_caller == original_caller or entry_caller == "*") and (
                            entry_source == original_source or entry_source == "*"):
                return False
        return True

    def get_items(self):
        """
        Getting a sorted item list with active SE

        :return:        sorted itemlist
        """
        sortedlist = sorted([k for k in self.__items.keys()])

        finallist = []
        for i in sortedlist:
            finallist.append(self.__items[i])
        return finallist

    def get_graph(self, abitem, type='link'):
        if isinstance(abitem, str):
            abitem = self.__items[abitem]
        webif = StateEngineWebif.WebInterface(self.__sh, abitem)
        try:
            os.makedirs(self.path_join(self.get_plugin_dir(), 'webif/static/img/visualisations/'))
        except OSError as e:
            pass
        vis_file = self.path_join(self.get_plugin_dir(), 'webif/static/img/visualisations/{}.svg'.format(abitem))
        #self.logger.debug("Getting graph: {}, {}".format(abitem, webif))
        try:
            if type == 'link':
                return '<a href="static/img/visualisations/{}.svg"><img src="static/img/vis.png" width="30"></a>'.format(abitem)
            else:
                webif.drawgraph(vis_file)
                return '<object type="image/svg+xml" data="static/img/visualisations/{0}.svg"\
                        style="max-width: 100%; height: auto; width: auto\9; ">\
                        <iframe src="static/img/visualisations/{0}.svg">\
                        <img src="static/img/visualisations/{0}.svg"\
                        style="max-width: 100%; height: auto; width: auto\9; ">\
                        </iframe></object>'.format(abitem)
        except Exception as ex:
            self.logger.error("Problem getting graph for {}. Error: {}".format(abitem, ex))
            return ''

    def init_webinterface(self):
        """"
        Initialize the web interface for this plugin

        This method is only needed if the plugin is implementing a web interface
        """
        try:
            self.mod_http = Modules.get_instance().get_module('http')   # try/except to handle running in a core version that does not support modules
        except:
             self.mod_http = None
        if self.mod_http == None:
            self.logger.error("Plugin '{}': Not initializing the web interface".format(self.get_shortname()))
            return False

        import sys
        if not "SmartPluginWebIf" in list(sys.modules['lib.model.smartplugin'].__dict__):
            self.logger.warning("Plugin '{}': Web interface needs SmartHomeNG v1.5 and up. Not initializing the web interface".format(self.get_shortname()))
            return False

        # set application configuration for cherrypy
        webif_dir = self.path_join(self.get_plugin_dir(), 'webif')
        config = {
            '/': {
                'tools.staticdir.root': webif_dir,
            },
            '/static': {
                'tools.staticdir.on': True,
                'tools.staticdir.dir': 'static'
            }
        }

        # Register the web interface as a cherrypy app
        self.mod_http.register_webif(WebInterface(webif_dir, self),
                                     self.get_shortname(),
                                     config,
                                     self.get_classname(), self.get_instance_name(),
                                     description='')

        return True


# ------------------------------------------
#    Webinterface of the plugin
# ------------------------------------------

import cherrypy
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
        self.logger = logging.getLogger(__name__)
        self.webif_dir = webif_dir
        self.plugin = plugin
        self.tplenv = self.init_template_environment()


    @cherrypy.expose
    def index(self, action=None, item_id=None, item_path=None, reload=None, abitem=None, page='index'):
        """
        Build index.html for cherrypy

        Render the template and return the html file to be delivered to the browser

        :return: contents of the template after beeing rendered
        """
        item = self.plugin.items.return_item(item_path)

        tmpl = self.tplenv.get_template('{}.html'.format(page))

        if action == "get_graph" and abitem is not None:
            if isinstance(abitem, str):
                abitem = self.plugin.abitems[abitem]
            self.plugin.get_graph(abitem, 'graph')
            tmpl = self.tplenv.get_template('visu.html')
            return tmpl.render(p=self.plugin, item=abitem,
                               language=self.plugin._sh.get_defaultlanguage(), now=self.plugin.shtime.now())
        # add values to be passed to the Jinja2 template eg: tmpl.render(p=self.plugin, interface=interface, ...)
        return tmpl.render(p=self.plugin,
                           language=self.plugin._sh.get_defaultlanguage(), now=self.plugin.shtime.now())
