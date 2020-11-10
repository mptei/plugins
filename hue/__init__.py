#!/usr/bin/env python3
# -*- coding: utf8 -*-
#########################################################################
# Copyright 2017-       Martin Sinn                         m.sinn@gmx.de
# Copyright 2014-2016   Michael Würtenberger
#########################################################################
#  Philips Hue plugin for SmartHomeNG
#
#  This plugin is free software: you can redistribute it and/or modify
#  it under the terms of the Apache License APL2.0 as published by
#  the Apache Software Foundation.
#
#  This plugin is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  Apache License for more details.
#
#  You should have received a copy of the Apache Software License along
#  with this plugin. If not, see <https://www.apache.org/licenses/>.
#########################################################################


#
#  Erstanlage mit ersten Tests
#  Basiert auf den Ueberlegungen des verhandenen Hue Plugins.
#  Die Parametrierung des Plugings in der plugin.conf und die authorize() Methode wurden zur
#  Wahrung der Kompatibilitaet uebernommen
#
#  Umsetzung rgb mit aufgenommen, basiert auf der einwegumrechnung von
#  https://github.com/benknight/hue-python-rgb-converter
#
#  Basiert aus der API 1.11 der Philips hue API spezifikation, die man unter
#  http://www.developers.meethue.com/documentation/lights-api finden kann
#
#  APL2.0
#
#  Library for RGB / CIE1931 coversion ported from Bryan Johnson's JavaScript implementation:
#  https://github.com/bjohnso5/hue-hacking
#  extension to use different triangle points depending of the type of the hue system
#

import logging
import json
import math
from collections import namedtuple
import http.client
import time
import threading

from lib.tools import Tools
from lib.model.smartplugin import SmartPlugin
from lib.utils import Utils

XY = namedtuple('XY', ['x', 'y'])
client = Tools()

class HUE(SmartPlugin):

    PLUGIN_VERSION = "1.4.5"

    def __init__(self, smarthome, hue_ip = '', hue_user = '', hue_port = '80', cycle_lamps = '10', cycle_bridges = '60', default_transitionTime = '0.4'):

        self.logger = logging.getLogger(__name__)

#        self.logger.warning("self._parameters = {}".format(str(self._parameters)))
        # parameter zu übergabe aus der konfiguration plugin.conf
        self._hue_ip = self.get_parameter_value('hue_ip')
        self._hue_user = self.get_parameter_value('hue_user')
        self._hue_port = self.get_parameter_value('hue_port')
#        self.logger.warning("self._hue_ip = {}, self._hue_user = {}, self._hue_port = {}".format(self._hue_ip, self._hue_user, self._hue_port))

        # verabreitung der parameter aus der plugin.conf
        self._numberHueBridges = len(self._hue_ip)

        if len(self._hue_port) != self._numberHueBridges or len(self._hue_user) != self._numberHueBridges:
            self.logger.error('Error in plugin.conf: if you specify more than 1 bridge, all parameters hue_ip, hue_user and hue_port have to be defined')
            self._init_complete = False
            return
        if '' in self._hue_user:
            self.logger.error('Error in plugin.conf: you have to specify all hue_user')
            self._init_complete = False
            return
        if '' in self._hue_port:
            self.logger.error('Error in plugin.conf: you have to specify all hue_port')
            self._init_complete = False
            return

        self._cycle_lampsGroups = self.get_parameter_value('cycle_lamps')
        self._cycle_bridges = self.get_parameter_value('cycle_bridges')
        self._hueDefaultTransitionTime = self.get_parameter_value('default_transitionTime')


        # variablen zur steuerung des plugins
        # hier werden alle bekannte items für lampen eingetragen
        self._sendLampItems = {}
        self._listenLampItems = {}
        # hier werden alle bekannte items für lampen eingetragen
        self._sendGroupItems = {}
        self._listenGroupItems = {}
        # hier werden alle bekannte items für die hues eingetragen
        self._sendBridgeItems = {}
        self._listenBridgeItems = {}
        # locks für die absicherung
        self._hueLock = threading.Lock()
        # hier ist die liste der einträge, für die der status auf listen gesetzt werden kann
        self._listenLampKeys = ['on', 'bri', 'sat', 'hue', 'reachable', 'effect', 'alert', 'type', 'name', 'modelid', 'uniqueid', 'manufacturername', 'swversion', 'ct']
        # hier ist die liste der einträge, für die der status auf senden gesetzt werden kann
        self._sendLampKeys = ['on', 'bri', 'bri_inc', 'sat','sat_inc', 'hue', 'hue_inc', 'effect', 'alert', 'col_r', 'col_g', 'col_b', 'ct', 'ct_inc']
        # hier ist die liste der einträge, für die der status auf listen gesetzt werden kann
        self._listenGroupKeys = ['on', 'bri', 'sat', 'hue', 'reachable', 'effect', 'alert', 'type', 'name', 'ct']
        # hier ist die liste der einträge, für die der status auf senden gesetzt werden kann
        self._sendGroupKeys = ['on', 'bri','bri_inc', 'sat' ,'sat_inc', 'hue', 'hue_inc', 'effect', 'alert', 'ct', 'ct_inc']
        # hier ist die liste der einträge, für die der status auf listen gesetzt werden kann
        self._listenBridgeKeys = ['bridge_name', 'zigbeechannel', 'mac', 'dhcp', 'ipaddress', 'netmask', 'gateway', 'UTC', 'localtime', 'timezone', 'bridge_swversion', 'apiversion', 'swupdate', 'linkbutton', 'portalservices', 'portalconnection', 'portalstate', 'whitelist','errorstatus']
        # hier ist die liste der einträge, für die der status auf senden gesetzt werden kann
        self._sendBridgeKeys = ['scene']
        # hier ist die liste der einträge, für die ein dimmer DPT3 gesetzt werden kann
        self._dimmKeys = ['bri', 'sat', 'hue']
        # hier ist die liste der einträge, für rgb gesetzt werden kann
        self._rgbKeys = ['col_r', 'col_g', 'col_b']
        # hier ist die liste der einträge, für string
        self._stringKeys = ['effect', 'alert', 'type', 'name', 'modelid', 'uniqueid', 'manufacturername', 'swversion', 'bridge_name', 'mac', 'ipaddress', 'netmask', 'gateway', 'UTC', 'localtime', 'timezone', 'bridge_swversion', 'apiversion', 'portalconnection']
        # hier ist die liste der einträge, für string
        self._boolKeys = ['on', 'reachable', 'linkbutton', 'portalservices', 'dhcp']
        # hier ist die liste der einträge, für string
        self._dictKeys = ['portalstate', 'swupdate', 'whitelist']
        # hier ist die liste der einträge, für wertebereich 0-255
        self._rangeInteger8 = ['bri', 'sat', 'col_r', 'col_g', 'col_b']
        # hier ist die liste der einträge, für wertebereich -254 bis 254
        self._rangeSignedInteger8 = ['bri_inc', 'sat_inc']
        # hier ist die liste der einträge, für wertebereich 0 bis 65535
        self._rangeInteger16 = ['hue']
        # hier ist die liste der einträge, für wertebereich -65534 bis 65534
        self._rangeSignedInteger16 = ['hue_inc','ct_inc']
        # konfiguration farbumrechnung. es gibt im Moment 2 lampentypgruppen:
        # hue bulb the corners index 0 [0] für LivingColors Bloom, Aura and Iris index 1 [1]
        self._numberHueLampTypes=3
        self.Red = [XY(0.674, 0.322), XY(0.703, 0.296), XY(1.0, 0.0)]
        self.Lime =[XY(0.408, 0.517), XY(0.214, 0.709), XY(0.703, 1.0)]
        self.Blue =[XY(0.168, 0.041), XY(0.139, 0.081), XY(0.0, 0.0)]
        # Flag for 'natural' behavior
        self._natural = True
        # Konfigurationen zur laufzeit
        # scheduler für das polling des status der lampen über die hue bridge
        self.scheduler_add('update-lamps', self._update_lamps, cycle = self._cycle_lampsGroups)
        # scheduler für das polling des status der lampen über die hue bridge
        self.scheduler_add('update-groups', self._update_groups, cycle = self._cycle_lampsGroups)
        # scheduler für das polling des status der hue bridge
        self.scheduler_add('update-bridges', self._update_bridges, cycle = self._cycle_bridges)

    ### following the library parts of the rewritten topics
    def crossProduct(self, p1, p2):
        return (p1.x * p2.y - p1.y * p2.x)
    def checkPointInLampsReach(self, p, lampType):
        v1 = XY(self.Lime[lampType].x - self.Red[lampType].x, self.Lime[lampType].y - self.Red[lampType].y)
        v2 = XY(self.Blue[lampType].x - self.Red[lampType].x, self.Blue[lampType].y - self.Red[lampType].y)
        q = XY(p.x - self.Red[lampType].x, p.y - self.Red[lampType].y)
        s = self.crossProduct(q, v2) / self.crossProduct(v1, v2)
        t = self.crossProduct(v1, q) / self.crossProduct(v1, v2)
        return (s >= 0.0) and (t >= 0.0) and (s + t <= 1.0)
    def getClosestPointToLine(self, A, B, P):
        AP = XY(P.x - A.x, P.y - A.y)
        AB = XY(B.x - A.x, B.y - A.y)
        ab2 = AB.x * AB.x + AB.y * AB.y
        ap_ab = AP.x * AB.x + AP.y * AB.y
        t = ap_ab / ab2
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
        return XY(A.x + AB.x * t, A.y + AB.y * t)
    def getClosestPointToPoint(self, xyPoint, lampType):
        pAB = self.getClosestPointToLine(self.Red[lampType], self.Lime[lampType], xyPoint)
        pAC = self.getClosestPointToLine(self.Blue[lampType], self.Red[lampType], xyPoint)
        pBC = self.getClosestPointToLine(self.Lime[lampType], self.Blue[lampType], xyPoint)
        dAB = self.getDistanceBetweenTwoPoints(xyPoint, pAB)
        dAC = self.getDistanceBetweenTwoPoints(xyPoint, pAC)
        dBC = self.getDistanceBetweenTwoPoints(xyPoint, pBC)
        lowest = dAB
        closestPoint = pAB
        if (dAC < lowest):
            lowest = dAC
            closestPoint = pAC
        if (dBC < lowest):
            lowest = dBC
            closestPoint = pBC
        cx = closestPoint.x
        cy = closestPoint.y
        return XY(cx, cy)
    def getDistanceBetweenTwoPoints(self, one, two):
        dx = one.x - two.x
        dy = one.y - two.y
        return math.sqrt(dx * dx + dy * dy)
    def getXYPointFromRGB(self, red, green, blue, lampType):
        r = ((red + 0.055) / (1.0 + 0.055))**2.4 if (red > 0.04045) else (red / 12.92)
        g = ((green + 0.055) / (1.0 + 0.055))**2.4 if (green > 0.04045) else (green / 12.92)
        b = ((blue + 0.055) / (1.0 + 0.055))**2.4 if (blue > 0.04045) else (blue / 12.92)
        X = r * 0.4360747 + g * 0.3850649 + b * 0.0930804
        Y = r * 0.2225045 + g * 0.7168786 + b * 0.0406169
        Z = r * 0.0139322 + g * 0.0971045 + b * 0.7141733
        if X + Y + Z == 0:
            cx = cy = 0
        else:
            cx = X / (X + Y + Z)
            cy = Y / (X + Y + Z)
        xyPoint = XY(cx, cy)
        inReachOfLamps = self.checkPointInLampsReach(xyPoint, lampType)
        if not inReachOfLamps:
            xyPoint = self.getClosestPointToPoint(xyPoint, lampType)
        return [xyPoint.x, xyPoint.y]
    ### end of library files

    def run(self):
        self.alive = True
        # if you want to create child threads, do not make them daemon = True!
        # They will not shutdown properly. (It's a python bug)

    def stop(self):
        self.alive = False

    def _find_item_attribute(self, item, attribute, attributeDefault, attributeLimit=99):
        # zwischenspeichern für die loggerausgabe
        itemSearch = item
        # schleife bis ich ganz oben angekommen bin
        while (not attribute in itemSearch.conf):
            # eine Stufe in den ebenen nach oben
            itemSearch = itemSearch.return_parent()
            if (itemSearch is self._sh):
                # wir sind am root knoten angekommen und haben nichts gefunden !
                if attribute == 'hue_bridge_id' and self._numberHueBridges > 1:
                    self.logger.warning('_find_item_attribute: could not find [{0}] for item [{1}], setting defined default value {2}'.format(attribute, item, attributeDefault))
                elif attribute == 'hue_lamp_type':
                    self.logger.warning('_find_item_attribute: could not find [{0}] for item [{1}], setting defined default value {2}'.format(attribute, item, attributeDefault))
                elif attribute == 'hue_lamp_id':
                    self.logger.error('_find_item_attribute: could not find [{0}] for item [{1}], an value has to be defined'.format(attribute, item))
                    raise Exception('Plugin stopped due to missing hue_lamp_id in item.conf')
                # wenn nicht gefunden, dann wird der standardwert zurückgegeben
                return str(attributeDefault)
        itemAttribute = int(itemSearch.conf[attribute])
        if itemAttribute >= attributeLimit:
            itemAttribute = attributeLimit
            self.logger.warning('_find_item_attribute: attribute [{0}] exceeds upper limit and set to default in item [{1}]'.format(attribute,item))
        return str(itemAttribute)

    def parse_item(self, item):
        # alle konfigurationsfehler sollten in der parsing routinge abgefangen werden
        # fehlende parameter werden mit eine fehlermeldung versehen und auf default werte gesetzt
        # sowie anschliessend in die objektstruktur dynamisch eingepflegt. Damit haben die Auswerte
        # routinen keinen sonderfall mehr abzudecken !
        # zunächst einmal die installation der dimmroutine
        if 'hue_dim_max' in item.conf:
            # DPT3 dimming requested
            # Check if parent is a dimmable item
            parent = item.return_parent()
            hueSend = parent.conf.get('hue_send')
            if hueSend is None:
                hueSend = parent.conf.get('hue_send_group')
            if hueSend is None or hueSend not in self._dimmKeys:
                self.logger.error('dimmenDPT3: need hue {0}} item as parent'.format(*self._dimmKeys))
                return None

            # Set defaults if not already set
            for key,val in [('hue_dim_step', '25'), ('hue_dim_time', '1'), ('hue_dim_min', '1'), ('hue_transitionTime',self._hueDefaultTransitionTime)]:
                if key not in item.conf:
                    self.logger.warning('dimmenDPT3: no {} defined in item [{}] using default {}'.format(key,item.id(),val))
                    item.conf[key] = val

            if self._natural:
                # Check if grandparent is a on item
                parent = parent.return_parent()
                hueSend = parent.conf.get('hue_send')
                if hueSend is None:
                    hueSend = parent.conf.get('hue_send_group')
                if hueSend is None or hueSend != 'on':
                    self.logger.error('dimmenDPT3KNX: need hue on item as grandparent')
                    return None
                return self.dimmenDPT3KNX
            else:
                return self.dimmenDPT3

        if 'hue_listen' in item.conf:
            hueListenCommand = item.conf['hue_listen']
            if hueListenCommand in self._listenLampKeys:
                # wir haben ein sendekommando für die lampen. dafür brauchen wir die bridge und die lampen id
                hueLampId = self._find_item_attribute(item, 'hue_lamp_id', 1)
                hueLampType = self._find_item_attribute(item, 'hue_lamp_type', 0, self._numberHueLampTypes)
                hueBridgeId = self._find_item_attribute(item, 'hue_bridge_id', 0, self._numberHueBridges)
                item.conf['hue_lamp_id'] = hueLampId
                item.conf['hue_lamp_type'] = hueLampType
                item.conf['hue_bridge_id'] = hueBridgeId
                hueIndex = hueBridgeId + '.' + hueLampId + '.' + hueListenCommand
                if not hueIndex in self._listenLampItems:
                    self._listenLampItems[hueIndex] = item
                else:
                    self.logger.warning('parse_item: in lamp item [{0}] command hue_listen = {1} is duplicated to item  [{2}]'.format(item,hueListenCommand,self._listenLampItems[hueIndex]))
            elif hueListenCommand in self._listenBridgeKeys:
                # hier brauche ich nur eine hue_bridge_id
                hueBridgeId = self._find_item_attribute(item, 'hue_bridge_id', 0, self._numberHueBridges)
                item.conf['hue_bridge_id'] = hueBridgeId
                hueIndex = hueBridgeId + '.' + hueListenCommand
                if not hueIndex in self._listenBridgeItems:
                    self._listenBridgeItems[hueIndex] = item
                else:
                    self.logger.warning('parse_item: in bridge item [{0}] command hue_listen = {1} is duplicated to item  [{2}]'.format(item,hueListenCommand,self._listenLampItems[hueIndex]))
            else:
                self.logger.error('parse_item: command hue_listen = {0} not defined in item [{1}]'.format(hueListenCommand,item))

        # für die groups brauchen wir eine eigenes listen attribut, weil die kommandos gleich denen der lampen sind damit schwer nur unterscheidbar
        if 'hue_listen_group' in item.conf:
            hueListenGroupCommand = item.conf['hue_listen_group']
            if hueListenGroupCommand in self._listenGroupKeys:
                # wir haben ein sendekommando für die lampen. dafür brauchen wir die bridge und die lampen id
                hueGroupId = self._find_item_attribute(item, 'hue_group_id', 1)
                hueBridgeId = self._find_item_attribute(item, 'hue_bridge_id', 0, self._numberHueBridges)
                item.conf['hue_group_id'] = hueGroupId
                item.conf['hue_bridge_id'] = hueBridgeId
                hueIndex = hueBridgeId + '.' + hueGroupId + '.' + hueListenGroupCommand
                if not hueIndex in self._listenGroupItems:
                    self._listenGroupItems[hueIndex] = item
                else:
                    self.logger.warning('parse_item: in group item [{0}] command hue_listen_group = {1} is duplicated to item  [{2}]'.format(item,hueListenGroupCommand,self._listenGroupItems[hueIndex]))

        if 'hue_send' in item.conf:
            hueSendCommand = item.conf['hue_send']
            if hueSendCommand in self._sendLampKeys:
                # wir haben ein sendekommando für die lampen. dafür brauchen wir die bridge und die lampen id
                hueLampId = self._find_item_attribute(item, 'hue_lamp_id', 1)
                hueLampType = self._find_item_attribute(item, 'hue_lamp_type', 0, self._numberHueLampTypes)
                hueBridgeId = self._find_item_attribute(item, 'hue_bridge_id', 0, self._numberHueBridges)
                item.conf['hue_lamp_id'] = hueLampId
                item.conf['hue_lamp_type'] = hueLampType
                item.conf['hue_bridge_id'] = hueBridgeId
                hueIndex = hueBridgeId + '.' + hueLampId + '.' + hueSendCommand
                if not hueIndex in self._sendLampItems:
                    self._sendLampItems[hueIndex] = item
                else:
                    self.logger.warning('parse_item: in lamp item [{0}] command hue_send = {1} is duplicated to item  [{2}]'.format(item,hueSendCommand,self._sendLampItems[hueIndex]))
                return self.update_lamp_item
            elif hueSendCommand in self._sendBridgeKeys:
                # hier brauche ich nur eine hue_bridge_id
                hueBridgeId = self._find_item_attribute(item, 'hue_bridge_id', 0, self._numberHueBridges)
                item.conf['hue_bridge_id'] = hueBridgeId
                hueIndex = hueBridgeId + '.' + hueSendCommand
                if not hueIndex in self._sendBridgeItems:
                    self._sendBridgeItems[hueIndex] = item
                else:
                    self.logger.warning('parse_item: in bridge item [{0}] command hue_send = {1} is duplicated to item  [{2}]'.format(item,hueSendCommand,self._sendLampItems[hueIndex]))
                return self.update_bridge_item
            else:
                self.logger.error('parse_item: command hue_send = {0} not defined in item [{1}]'.format(hueSendCommand,item))

        # für die groups brauchen wir eine eigenes listen attribut, weil die kommandos gleich denen der lampen sind damit schwer nur unterscheidbar
        if 'hue_send_group' in item.conf:
            hueSendGroupCommand = item.conf['hue_send_group']
            if hueSendGroupCommand in self._sendGroupKeys:
                # wir haben ein sendekommando für die lampen. dafür brauchen wir die bridge und die group id
                hueGroupId = self._find_item_attribute(item, 'hue_group_id', 1)
                hueBridgeId = self._find_item_attribute(item, 'hue_bridge_id', 0, self._numberHueBridges)
                item.conf['hue_group_id'] = hueGroupId
                item.conf['hue_bridge_id'] = hueBridgeId
                hueIndex = hueBridgeId + '.' + hueGroupId + '.' + hueSendGroupCommand
                if not hueIndex in self._sendGroupItems:
                    self._sendGroupItems[hueIndex] = item
                else:
                    self.logger.warning('parse_item: in group item [{0}] command hue_send_group = {1} is duplicated to item  [{2}]'.format(item,hueSendGroupCommand,self._sendGroupItems[hueIndex]))
                return self.update_group_item

    def _limit_range_int(self, value, minValue, maxValue):
        # kurze routine zur wertebegrenzung
        if value >= maxValue:
            value = int(maxValue)
        elif value < minValue:
            value = int(minValue)
        else:
            value = int(value)
        return value
   
    def update_lampgroup_item(self, item, isGroup, sendItems, stateSetter, caller=None, source=None, dest=None):
        # lokale speicherung in variablen, damit funktionen nicht immer aufgerufen werden (performance)
        value = item()
        hueBridgeId = item.conf['hue_bridge_id']

        if isGroup:
            hueId = item.conf['hue_group_id']
            hueSend = item.conf['hue_send_group']
            hueLampType = None
        else:
            hueId = item.conf['hue_lamp_id']
            hueSend = item.conf['hue_send']
            hueLampType = item.conf.get('hue_lamp_type')

        hueTransitionTime = item.conf.get('hue_transitionTime')
        if hueTransitionTime is not None:
            hueTransitionTime = int(float(hueTransitionTime) * 10)
        else:
            hueTransitionTime = int(self._hueDefaultTransitionTime * 10)

        # index ist immer bridge_id + id + hue_send
        hueIndex = hueBridgeId + '.' + hueId

        if hueSend == 'on':
            hueOnItem = item
            shStateIsOn = value
        else:
            hueOnItem = sendItems.get(hueIndex+'.on')
            if hueOnItem is not None:
                shStateIsOn = hueOnItem()
            else:
                self.logger.warning('update_lampgroup_item: no item for on/off defined for item {0}'.format(item.id()))
                shStateIsOn = False
        self.logger.debug('shStateIsOn: {0}'.format(shStateIsOn))
            
        # test aus die wertgrenzen, die die bridge verstehen kann
        if hueSend == 'ct':
            # ct darf zwischen 153 und 500 liegen
            value = self._limit_range_int(value, 153, 500)
        elif hueSend in self._rangeInteger8:
            # werte dürfen zwischen 0 und 255 liegen
            value = self._limit_range_int(value, 0, 255)    
        elif hueSend in self._rangeInteger16:
            # hue darf zwischen 0 und 65535 liegen
            value = self._limit_range_int(value, 0, 65535)    
        elif hueSend in self._rangeSignedInteger8:
            # werte dürfen zwischen -254 und 254 liegen
            value = self._limit_range_int(value, -254, 254)    
        elif hueSend in self._rangeSignedInteger16:
            # hue darf zwischen -65534 und 65534 liegen
            value = self._limit_range_int(value, -65534, 65534)    
            
        if shStateIsOn:
            # lampe ist an (status in sh). dann können alle befehle gesendet werden
            if hueSend == 'on':
                # wenn der status in sh true ist, aber mit dem befehl on, dann muss die lampe auf der hue seite erst eingeschaltet werden
                options = {'on': True , 'transitiontime': hueTransitionTime}

                ctItem = sendItems.get(hueIndex+'.ct')
                if ctItem is not None:
                    ct = int(ctItem())
                    options.update({'ct': ct})

                briItem = sendItems.get(hueIndex+'.bri')
                if self._natural:
                    # Switch on with full brightness
                    options.update({'bri': 255})
                    if briItem is not None:
                        briItem(255,'HUE','switched on')
                else:
                    # Restore brightness (if available)
                    if briItem is not None:
                        # wenn eingeschaltet wird und ein bri item vorhanden ist, dann wird auch die hellgkeit
                        # mit gesetzt, weil die gruppe das im ausgeschalteten zustand vergisst.
                        bri = int(briItem())
                        if bri == 0:
                            # Set brightness at least to 1
                            bri = 1
                            briItem(1,'HUE','set at least to 1 on switch on')
                        options.update({'bri': bri})
                    else:
                        # ansonst wird nur eingeschaltet
                        self.logger.info('update_lampgroup_item: no bri item defined for item {0} restoring the brightness after swiching on again'.format(item.id()))
                stateSetter(hueBridgeId, hueId, options)
            else:
                # anderer befehl gegeben
                if hueLampType is not None and hueSend in self._rgbKeys:
                    # besonderheit ist der befehl für die rgb variante, da hier alle werte herausgesucht werden müssen
                    col_r = sendItems.get(hueIndex+'.col_r')
                    col_g = sendItems.get(hueIndex+'.col_g')
                    col_b = sendItems.get(hueIndex+'.col_b')
                    if col_r is not None and col_g is not None and col_b is not None:
                        # wertebereiche der anderen klären bri darf zwischen 0 und 255 liegen
                        value_r = self._limit_range_int(col_r(), 0, 255)    
                        value_g = self._limit_range_int(col_g(), 0, 255)    
                        value_b = self._limit_range_int(col_b(), 0, 255)    

                        xyPoint = self.getXYPointFromRGB(value_r, value_g, value_b, int(hueLampType))
                        # und jetzt der wert setzen
                        stateSetter(hueBridgeId, hueId, {'xy': xyPoint, 'transitiontime': hueTransitionTime})
                    else:
                        self.logger.warning('update_lampgroup_item: on or more of the col... items around item {0} is not defined'.format(item.id()))
                else:
                    # Switch lamp off via bri == 0
                    if hueSend == 'bri' and value == 0:
                        # Switch item of via bri 0
                        stateSetter(hueBridgeId, hueId, {'on': False, 'transitiontime': hueTransitionTime, 'bri': 0})
                        if hueOnItem is not None:
                            hueOnItem(False,'HUE','off via bri == 0')
                    else:
                        # standardbefehle
                        stateSetter(hueBridgeId, hueId, {hueSend: value, 'transitiontime': hueTransitionTime})
        else:
            # lampe ist im status bei sh aus. in diesem zustand sollten keine befehle gesendet werden
            if hueSend == 'on':
                # sonderfall, wenn der status die transition erst ausgeöst hat, dann muss die gruppe
                # auf der hue seite erst ausgeschaltet werden
                stateSetter(hueBridgeId, hueId, {'on': False , 'transitiontime': hueTransitionTime, 'bri': 0})
                if self._natural:
                    briItem = sendItems.get(hueIndex+'.bri')
                    if briItem is not None:
                        # Set brightness to 0
                        briItem(0,'HUE','set to 0 on switch off')
            else:
                # die lampe kann auch über das senden bri angemacht werden
                if hueSend == 'bri' and value != 0:
                    # jetzt wird die gruppe eingeschaltet und der wert von bri auf den letzten wert gesetzt
                    stateSetter(hueBridgeId, hueId, {'on': True , 'bri': value, 'transitiontime': hueTransitionTime})
                    if hueOnItem is not None:
                        # switch bool item on
                        hueOnItem(True,'HUE','on via bri != 0')
                else:
                    # ansonsten wird kein befehl abgesetzt !
                    pass                           
                           
    def update_lamp_item(self, item, caller=None, source=None, dest=None):
        # methode, die bei einer änderung des items ausgerufen wird wenn die änderung von aussen kommt, dann wird diese abgearbeitet
        # im konkreten fall heisst das, dass der aktuelle status der betroffene lampe komplett zusammengestellt wird
        # und anschliessen neu über die hue bridge gesetzt wird.
        self.logger.debug('update lamp item {0}, caller {1}, source {2} => {3}'.format(item.id(),caller,source,item()))
        if caller != 'HUE':
            self.update_lampgroup_item(item, False, self._sendLampItems, self._set_lamp_state, caller, source, dest)

    def update_group_item(self, item, caller=None, source=None, dest=None):
        # methode, die bei einer änderung des items ausgerufen wird wenn die änderung von aussen kommt, dann wird diese abgearbeitet
        # im konkreten fall heisst das, dass der aktuelle status der betroffene lampe komplett zusammengestellt wird
        # und anschliessen neu über die hue bridge gesetzt wird.
        self.logger.debug('update group item {0}, caller {1}, source {2} => {3}'.format(item.id(),caller,source,item()))
        if caller != 'HUE':
            self.update_lampgroup_item(item, True, self._sendGroupItems, self._set_group_state, caller, source, dest)
                           
    def update_bridge_item(self, item, caller=None, source=None, dest=None):
        # methode, die bei einer änderung des items ausgerufen wird
        # wenn die änderung von aussen kommt, dann wird diese abgearbeitet
        # im konkreten fall heisst das, dass der aktuelle status der betroffene lampe komplett zusammengestellt wird
        # und anschliessen neu über die hue bridge gesetzt wird.
        self.logger.debug('update bridge item {0}, caller {1}, source {2} => {3}'.format(item.id(),caller,source,item()))
        if caller != 'HUE':
            # lokale speicherung in variablen, damit funktionen nicht immer aufgerufen werden (performance)
            value = item()
            hueBridgeId = item.conf['hue_bridge_id']
            hueSend = item.conf['hue_send']
            # test aus die wertgrenzen, die die bridge verstehen kann
            if hueSend in self._rangeInteger8:
                # werte dürfen zwischen 0 und 255 liegen
                value = self._limit_range_int(value, 0, 255)
            if hueSend in self._rangeInteger16:
                # hue darf zwischen 0 und 65535 liegen
                value = self._limit_range_int(value, 0, 65535)
            self._set_group_state(hueBridgeId, '0', {hueSend: value})

    def dimmenDPT3(self, item, caller=None, source=None, dest=None):
        # das ist die methode, die die DPT3 dimmnachrichten auf die dimmbaren hue items mapped
        # fallunterscheidung dimmen oder stop
        self.logger.debug('dimm DPT3 item {0}, caller {1}, source {2} => {3}'.format(item.id(),caller,source,item()))
        if caller != 'HUE':
            # auswertung der list werte für die KNX daten
            # [1] steht für das dimmen
            # [0] für die richtung
            # es wird die fading function verwendet
            parent = item.return_parent()
            if item()[1] == 1:
                # dimmen
                if item()[0] == 1:
                    targetVal = float(item.conf['hue_dim_max'])
                else:
                    targetVal = float(item.conf['hue_dim_min'])
                if not parent._fading:
                    valueDimStep = float(item.conf['hue_dim_step'])
                    valueDimTime = float(item.conf['hue_dim_time'])
                    self.logger.debug('Dimm item {0} to {1} with step {2} and step time {3}'.format(parent.id(), targetVal, valueDimStep, valueDimTime))
                    parent.fade(targetVal, valueDimStep, valueDimTime)
            else:
                # stop, dimming
                parent._fading = False
                self.logger.debug('Stopped dimming item {0}'.format(parent.id()))

    # Dimming KNX compatibel. Means dimming up starts on min.
    # It is assured that the item has a HUE bri parent. Also it exists
    # a switch item
    def dimmenDPT3KNX(self, item, caller=None, source=None, dest=None):
        # das ist die methode, die die DPT3 dimmnachrichten auf die dimmbaren hue items mapped
        # fallunterscheidung dimmen oder stop
        self.logger.debug('dimm DPT3 item {0}, caller {1}, source {2} => {3}'.format(item.id(),caller,source,item()))
        if caller != 'HUE':
            # Determine bri and on item                
            hueBriItem = item.return_parent()
            hueOnItem = hueBriItem.return_parent()
            hueId = hueOnItem.conf.get('hue_send')
            # Determine setter method
            if hueId is not None:
                # lamp item
                hueId = hueOnItem.conf['hue_id']
                stateSetter = self._set_lamp_state
            else:
                # group item
                hueId = hueOnItem.conf.get('hue_group_id')
                stateSetter = self._set_group_state

            if item()[1] == 1:
                # dimming
                hueTransitionTime = float(item.conf.get('hue_transitionTime')*10)
                valueMin = float(item.conf['hue_dim_min'])
                if item()[0] == 1:
                    # up
                    if not hueOnItem():
                        # Switch lamp on with lowest brightness
                        hueBridgeId = hueOnItem.conf['hue_bridge_id']
                        stateSetter(hueBridgeId, hueId, {'on': True , 'bri': valueMin, 'transitiontime': hueTransitionTime})
                        hueBriItem(valueMin,'HUE','DPT3 start on min')
                        hueOnItem(True,'HUE','DPT3 start on min')
                    targetVal = float(item.conf['hue_dim_max'])
                else:
                    # down
                    targetVal = valueMin
                if not hueBriItem._fading:
                    valueDimStep = float(item.conf['hue_dim_step'])
                    valueDimTime = float(item.conf['hue_dim_time'])
                    self.logger.debug('Dimm item {0} to {1} with step {2} and step time {3}'.format(hueBriItem.id(), targetVal, valueDimStep, valueDimTime))
                    hueBriItem.fade(targetVal, valueDimStep, valueDimTime)
            else:
                # stop, dimming
                hueBriItem._fading = False
                self.logger.debug('Stopped dimming item {0}'.format(hueBriItem.id()))
                
    def  _get_web_content(self, hueBridgeId='0', path='', method='GET', body=None):
        # in dieser routine erfolgt der umbau und die speziellen themen zur auswertung der verbindung, die speziell für das plugin ist
        # der rest sollte standard in der routine fetch_url() enthalten sein. leider fehlt dort aber die auswertung der fehllerconditions
        # erst einmal die komplette url
        url = 'http://' + self._hue_ip[int(hueBridgeId)] + ':' + self._hue_port[int(hueBridgeId)] + '/api/' + self._hue_user[int(hueBridgeId)] + path
        # setzen des fehlerstatus items
        if hueBridgeId + '.' + 'errorstatus' in self._listenBridgeItems:
            errorItem = self._listenBridgeItems[hueBridgeId + '.' + 'errorstatus']
        else:
            errorItem = None
            self.logger.debug('_get_web_content {0}, {1}, {2}, {3}'.format(hueBridgeId,method,path,body))
        # dann der aufruf kompatibel, aber inhaltlich nicht identisch fetch_url aus lib.tools, daher erst eimal das fehlerobjekt nicht mehr da
        try:
            response = client.fetch_url(url, None, None, 2, 0, method, body, errorItem)
        except:
            response = False
        if response:
            # und jetzt der anteil der decodierung, der nicht in der fetch_url drin ist
            # lesen, decodieren nach utf-8 (ist pflicht nach der api definition philips) und in ein python objekt umwandeln
            responseJson = response.decode('utf-8')
            returnValues = json.loads(responseJson)
            # fehlerauswertung der rückmeldung, muss noch vervollständigt werden
            if isinstance(returnValues, list) and returnValues[0].get('error', None):
                error = returnValues[0]["error"]
                description = error['description']
                if error['type'] == 1:
                    self.logger.error('_request: Error: {0} (Need to specify correct hue user?)'.format(description))
                else:
                    self.logger.error('_request: Error: {0}'.format(description))
                return None
            return returnValues
        else:
            return None

    def _set_lamp_state(self, hueBridgeId, hueLampId, state):
        # hier erfolgt das setzen des status einer lampe
        # hier kommt der PUT request, um die stati an die hue bridge zu übertragen
        with self._hueLock:
            returnValues = self._get_web_content(hueBridgeId, '/lights/%s/state' % hueLampId, 'PUT', json.dumps(state))
            if returnValues == None:
                return
            # der aufruf liefert eine bestätigung zurück, was den numgesetzt werden konnte
            for hueObject in returnValues:
                for hueObjectStatus, hueObjectReturnString in hueObject.items():
                    if hueObjectStatus == 'success':
                        for hueObjectReturnStringPath, hueObjectReturnStringValue in hueObjectReturnString.items():
                            hueObjectReturnStringPathItem = hueObjectReturnStringPath.split('/')[4]
                            # hier werden jetzt die bestätigten werte aus der rückübertragung im item gesetzt
                            # wir gehen durch alle listen items, um die zuordnung zu machen
                            for returnItem in self._listenLampItems:
                                # wenn ein listen item angelegt wurde und dafür ein status zurückkam
                                # verglichen wird mit dem referenzkey, der weiter oben aus lampid und state gebaut wurde
                                if returnItem == (hueBridgeId + '.' + hueLampId + '.' + hueObjectReturnStringPathItem):
                                    # dafür wir der reale wert der hue bridge gesetzt
                                    if hueObjectReturnStringPathItem in self._boolKeys:
                                        # typecast auf bool
                                        value = bool(hueObjectReturnStringValue)
                                    elif hueObjectReturnStringPathItem in self._stringKeys:
                                        # typecast auf string
                                        value = str(hueObjectReturnStringValue)
                                    else:
                                        # sonst ist es int
                                        value = int(hueObjectReturnStringValue)
                                    self._listenLampItems[returnItem](value, 'HUE')
                    else:
                        self.logger.warning('hue_set_lamp_state - hueObjectStatus no success:: {0}: {1} command state {2}'.format(hueObjectStatus, hueObjectReturnString, state))

    def _set_group_state(self, hueBridgeId, hueGroupId , state):
        # hier erfolgt das setzen des status einer gruppe im Moment ist nur der abruf einer szene implementiert
        # hier kommt der PUT request, um die stati an die hue bridge zu übertragen
        with self._hueLock:
            returnValues = self._get_web_content(hueBridgeId, '/groups/%s/action' % hueGroupId, 'PUT', json.dumps(state))
            if returnValues == None:
                return
            # der aufruf liefert eine bestätigung zurück, was den numgesetzt werden konnte
            for hueObject in returnValues:
                for hueObjectStatus, hueObjectReturnString in hueObject.items():
                    if hueObjectStatus == 'success':
                        pass
                    else:
                        self.logger.warning('_set_group_state - hueObjectStatus no success:: {0}: {1} command state {2}'.format(hueObjectStatus, hueObjectReturnString, state))
    
    # Common method for updating items connected to lamps or groups
    def _update_lampsgroups(self, hueBridgeId, returnValues, listenItems):
        # schleife über alle gefundenen hue items
        for itemId, itemValues in returnValues.items():
            # schleife über alle rückmeldungen der lampen.
            # jetzt muss ich etwas tricksen, da die states eine ebene tiefer als die restlichen infos der lampe liegen
            # in den items ist das aber eine flache hierachie. um nur eine schleife darüber zu haben, baue ich mir ein
            # entsprechendes dict zusammen. 'state' ist zwar doppelt drin, stört aber nicht, da auch auf unterer ebene.
            dictOptimized = {}
            if 'state' in itemValues:
                dictOptimized.update(itemValues['state'])
            if 'action' in itemValues:
                dictOptimized.update(itemValues['action'])
            if dictOptimized:
                dictOptimized.update(itemValues)
                # jetzt kann der durchlauf beginnen
                for hueObjectItem, hueObjectItemValue in dictOptimized.items():
                    # nachdem alle objekte und werte auf die gleiche ebene gebracht wurden, beginnt die zuordnung
                    # vor hier an werden die ganzen listen items durchgesehen und die werte aus der rückmeldung zugeordnet
                    listenItem = listenItems.get(hueBridgeId + '.' + itemId + '.' + hueObjectItem)
                    if listenItem is not None:
                        if hueObjectItem in self._boolKeys:
                            value = bool(hueObjectItemValue)
                        elif hueObjectItem in self._stringKeys:
                            value = str(hueObjectItemValue)
                        else:
                            value = int(hueObjectItemValue)
                        # wenn der wert gerade im fading ist, dann nicht überschreiben, sonst bleibt es stehen !
                        if not listenItem._fading:
                            # es werden nur die Einträge zurückgeschrieben, falls die Lampe nich im fading betrieb ist
                            if hueObjectItem == 'bri':
                                # bei brightness gibt es eine fallunterscheidung
                                onListenItem = listenItems.get(hueBridgeId + '.' + itemId + '.on')
                                if onListenItem is not None:
                                    # geht aber nur, wenn ein solches item vorhanden ist
                                    if onListenItem():
                                        # die brightness darf nur bei lamp = on zurückgeschrieben werden, den bei aus ist sie immer 0
                                        listenItem(value, 'HUE')
                            else:
                                # bei allen anderen kann zurückgeschrieben werden
                                listenItem(value, 'HUE')

    def _update_lamps(self):
        # mache ich mit der API get all lights
        # hier kommt der PUT request, um die stati an die hue bridge zu übertragen beispiel:
        numberBridgeId = 0
        while numberBridgeId < self._numberHueBridges:
            hueBridgeId = str(numberBridgeId)
            with self._hueLock:
                returnValues = self._get_web_content(hueBridgeId, '/lights')
                if returnValues == None:
                    return
                self._update_lampsgroups(hueBridgeId, returnValues, self._listenLampItems)
            numberBridgeId = numberBridgeId + 1

    def _update_groups(self):
        # mache ich mit der API get all groups
        # hier kommt der PUT request, um die stati an die hue bridge zu übertragen beispiel:
        numberBridgeId = 0
        while numberBridgeId < self._numberHueBridges:
            hueBridgeId = str(numberBridgeId)
            with self._hueLock:
                returnValues = self._get_web_content(hueBridgeId, '/groups')
                if returnValues == None:
                    return
                self._update_lampsgroups(hueBridgeId, returnValues, self._listenGroupItems)
            numberBridgeId = numberBridgeId + 1

    def _update_bridges(self):
        # der datenabruf besteht aus dem befehl get configuration bridge
        numberBridgeId = 0
        while numberBridgeId < self._numberHueBridges:
            hueBridgeId = str(numberBridgeId)
            with self._hueLock:
                returnValues = self._get_web_content(hueBridgeId, '/config')
                if returnValues == None:
                    return
                # schleife über alle gefundenen lampen
                for hueObjectItem, hueObjectItemValue in returnValues.items():
                    # nachdem alle objekte und werte auf die gleiche ebene gebracht wurden, beginnt die zuordnung
                    # vor hier an werden die ganzen listen items durchgesehen und die werte aus der rückmeldung zugeordnet
                    for returnItem in self._listenBridgeItems:
                        # wenn ein listen item angelegt wurde und dafür ein status zurückkam
                        # verglichen wird mit dem referenzkey, der weiter oben aus lampid und state gebaut wurde
                        if hueObjectItem == 'swversion':
                            hueObjectItem = 'bridge_swversion'
                        if hueObjectItem == 'name':
                            hueObjectItem = 'bridge_name'
                        if returnItem == (hueBridgeId + '.' + hueObjectItem):
                            # dafür wir der reale wert der hue bridge gesetzt
                            if hueObjectItem in self._boolKeys:
                                value = bool(hueObjectItemValue)
                            elif hueObjectItem in self._stringKeys:
                                value = str(hueObjectItemValue)
                            elif hueObjectItem in self._dictKeys:
                                value = dict(hueObjectItemValue)
                            else:
                                value = int(hueObjectItemValue)
                            # wenn der wert gerade im fading ist, dann nicht überschreiben, sonst bleibt es stehen !
                            self._listenBridgeItems[returnItem](value, 'HUE')
            numberBridgeId = numberBridgeId + 1


    def get_config(self, hueBridgeId='0'):
        # hier eine interaktive routing für di ecli, um den user herauszubekommen,
        # mit dem die szenen gesetzt worden sind, um ihn dann als user für das plugin einzusetzen
        # und jetzt alle szenen
        returnValues = self._get_webcontent(hueBridgeId, '/scenes')
        self.logger.warning('get_config: Scenes {0}'.format(returnValues))
        returnValues = self._get_webcontent(hueBridgeId, '/groups')
        self.logger.warning('get_config: Groups {0}'.format(returnValues))
        return returnValues


    def authorizeuser(self, hueBridgeId='0'):
        data = json.dumps(
            {"devicetype": "smarthome#" + self._hue_user[int(hueBridgeId)]})
        con = http.client.HTTPConnection(self._hue_ip[int(hueBridgeId)], self._hue_port[int(hueBridgeId)])
        con.request("POST", "/api", data)
        resp = con.getresponse()
        con.close()
        if resp.status != 200:
            self.logger.error('authorize: Authenticate request failed')
            return "Authenticate request failed"
        resp = resp.read().decode('utf-8')
        self.logger.debug(resp)
        resp = json.loads(resp)
        self.logger.debug(resp)
        return resp

