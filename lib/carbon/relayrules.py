import re

from os.path import exists, getmtime
from twisted.internet.task import LoopingCall

from carbon import log
from carbon.conf import OrderedConfigParser
from carbon.exceptions import CarbonConfigException
from carbon.util import parseDestinations


class RelayRule:
  def __init__(self, condition, destinations, continue_matching=False):
    self.condition = condition
    self.destinations = destinations
    self.continue_matching = continue_matching

  def matches(self, metric):
    return bool(self.condition(metric))


def loadRelayRules(path):
  rules = []
  parser = OrderedConfigParser()

  if not parser.read(path):
    raise CarbonConfigException("Could not read rules file %s" % path)

  defaultRule = None
  for section in parser.sections():
    if not parser.has_option(section, 'destinations'):
      raise CarbonConfigException("Rules file %s section %s does not define a "
                                  "'destinations' list" % (path, section))

    destination_strings = parser.get(section, 'destinations').split(',')
    destinations = parseDestinations(destination_strings)

    if parser.has_option(section, 'pattern'):
      if parser.has_option(section, 'default'):
        raise CarbonConfigException("Section %s contains both 'pattern' and "
                                    "'default'. You must use one or the other." % section)
      pattern = parser.get(section, 'pattern')
      regex = re.compile(pattern, re.I)

      continue_matching = False
      if parser.has_option(section, 'continue'):
        continue_matching = parser.getboolean(section, 'continue')
      rule = RelayRule(
        condition=regex.search, destinations=destinations, continue_matching=continue_matching)
      rules.append(rule)
      continue

    if parser.has_option(section, 'default'):
      if not parser.getboolean(section, 'default'):
        continue  # just ignore default = false
      if defaultRule:
        raise CarbonConfigException("Only one default rule can be specified")
      defaultRule = RelayRule(condition=lambda metric: True,
                              destinations=destinations)

  if not defaultRule:
    raise CarbonConfigException("No default rule defined. You must specify exactly one "
                                "rule with 'default = true' instead of a pattern.")

  rules.append(defaultRule)
  return rules


class RelayRuleManager(object):
  def __init__(self, clock=None):
    self.rules = []
    self.rules_file = None
    self.rules_last_read = 0.0
    self.read_task = LoopingCall(self.read_rules)
    if clock is not None:
      self.read_task.clock = clock

  def read_from(self, rules_file):
    self.rules_file = rules_file
    self.read_rules()
    if not self.read_task.running:
      self.read_task.start(10, now=False)

  def stop(self):
    if self.read_task.running:
      self.read_task.stop()

  def read_rules(self):
    if not exists(self.rules_file):
      if self.rules:
        log.err("Relay rules file %s disappeared; keeping current rules" % self.rules_file)
        return
      raise CarbonConfigException("Could not read rules file %s" % self.rules_file)

    try:
      mtime = getmtime(self.rules_file)
    except OSError:
      log.err("Failed to get mtime of %s" % self.rules_file)
      return

    if mtime <= self.rules_last_read:
      return

    try:
      new_rules = loadRelayRules(self.rules_file)
      loaded_mtime = getmtime(self.rules_file)
    except Exception as error:
      log.err("Failed to reload relay rules from %s: %s" % (self.rules_file, error))
      if not self.rules:
        raise
      return

    if loaded_mtime < mtime:
      return

    self.rules = new_rules
    self.rules_last_read = mtime
