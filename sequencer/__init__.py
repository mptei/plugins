#!/usr/bin/env python
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
# Copyright 2013 KNX-User-Forum e.V.            http://knx-user-forum.de/
#########################################################################
#  This file is part of SmartHome.py.   http://smarthome.sourceforge.net/
#
#  SmartHome.py is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  SmartHome.py is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with SmartHome.py. If not, see <http://www.gnu.org/licenses/>.
#########################################################################

import logging
import threading

logger = logging.getLogger('')

class Sequencer():

    def __init__(self, smarthome):
        self._sh = smarthome
        self._lock = threading.Condition()

    def run(self):
        self.alive = True

    def stop(self):
        self.alive = False

    def parse_item(self, item):
        pass

    def parse_logic(self, logic):
        pass

    def sequence(self, data):
        logger.debug("sequencer: sequence started")
        if isinstance(data,(str,bytes)):
            # Sequence given as a string
            # Convert into list
            logger.info("Not supported")
        # Sequence given as list
        self._sh.trigger('sequence', self._sequencejob, value={'data': data})

    def _sequencejob(self, data):
        item = None
        for obj in data:
            if obj.__class__.__name__ == 'Item':
                item = obj
            elif isinstance(obj,dict):
                value = obj['value']
                delay = obj['delay']
                if item is not None:
                    item(value)
                    self._lock.acquire()
                    self._lock.wait(delay)
                    self._lock.release()

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    myplugin = Timer('timer')
    myplugin.run()
