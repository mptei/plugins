#!/usr/bin/env python
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab

import logging
import threading
from lib.model.smartplugin import SmartPlugin

logger = logging.getLogger(__name__)

class Sequencer(SmartPlugin):

    ALLOW_MULTIINSTANCE = False
    PLUGIN_VERSION = "0.0.1"

    def __init__(self, smarthome, *args, **kwargs):
        self._sh = smarthome
        self.logger = logging.getLogger(__name__)
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
            self.logger.info("Not supported")
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

#if __name__ == '__main__':
#    logging.basicConfig(level=logging.DEBUG)
#    myplugin = Timer('timer')
#    myplugin.run()
