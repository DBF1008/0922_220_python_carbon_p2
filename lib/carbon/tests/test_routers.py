import shutil
import os
import tempfile
import unittest

from carbon import routers
from carbon.util import parseDestinations
from carbon.tests import util
from twisted.internet.task import Clock


DESTINATIONS = (
    'foo:124:a',
    'foo:125:b',
    'foo:126:c',
    'bar:423:a',
    'bar:424:b',
    'bar:425:c',
)

RULE_DESTINATIONS = (
    'alpha:2001:a',
    'beta:2002:b',
    'default:2003:d',
    'other:2004:o',
)


def writeRules(path, rules, mtime=1000):
    with open(path, 'w') as rules_file:
        rules_file.write(rules)
    os.utime(path, (mtime, mtime))


BASIC_RULES = """
[alpha]
pattern = ^alpha\\.
destinations = alpha:2001:a

[default]
default = true
destinations = default:2003:d
"""


def createSettings():
    settings = util.TestSettings()
    settings['DIVERSE_REPLICAS'] = True,
    settings['REPLICATION_FACTOR'] = 2
    settings['DESTINATIONS'] = DESTINATIONS
    settings['relay-rules'] = os.path.join(
        os.path.dirname(__file__), 'relay-rules.conf')
    settings['aggregation-rules'] = None
    return settings


def parseDestination(destination):
    return parseDestinations([destination])[0]


class TestRelayRulesRouter(unittest.TestCase):
    def testBasic(self):
        router = routers.RelayRulesRouter(createSettings())
        self.addCleanup(router.rule_manager.stop)
        for destination in DESTINATIONS:
            router.addDestination(parseDestination(destination))
        self.assertEqual(len(list(router.getDestinations('foo.bar'))), 1)

    def setUp(self):
        self.rules_directory = tempfile.mkdtemp()
        self.rules_path = os.path.join(self.rules_directory, 'relay-rules.conf')
        writeRules(self.rules_path, BASIC_RULES)

        settings = util.TestSettings()
        settings['relay-rules'] = self.rules_path
        self.router = routers.RelayRulesRouter(settings)
        for destination in RULE_DESTINATIONS:
            self.router.addDestination(parseDestination(destination))
        self.assertIs(self.router.rules, self.router.rule_manager.rules)

    def tearDown(self):
        self.router.rule_manager.stop()
        shutil.rmtree(self.rules_directory)

    def assertRoutesTo(self, metric, destinations):
        self.assertEqual(
            set(self.router.getDestinations(metric)),
            set(parseDestination(destination) for destination in destinations))

    def reloadRules(self, rules, mtime):
        writeRules(self.rules_path, rules, mtime)
        self.router.rule_manager.read_rules()

    def testAddsRuleWhenFileChanges(self):
        rules = BASIC_RULES.replace(
            '\n[default]',
            '\n[beta]\npattern = ^beta\\.\ndestinations = beta:2002:b\n\n[default]')

        self.assertRoutesTo('beta.one', ['default:2003:d'])
        self.reloadRules(rules, 2000)
        self.assertRoutesTo('beta.one', ['beta:2002:b'])

    def testScheduledReloadPicksUpChangedFile(self):
        from carbon.relayrules import RelayRuleManager

        clock = Clock()
        self.router.rule_manager.stop()
        self.router.rule_manager = RelayRuleManager(clock=clock)
        self.router.rule_manager.read_from(self.rules_path)
        rules = BASIC_RULES.replace(
            '\n[default]',
            '\n[beta]\npattern = ^beta\\.\ndestinations = beta:2002:b\n\n[default]')

        self.assertRoutesTo('beta.one', ['default:2003:d'])
        writeRules(self.rules_path, rules, 2000)
        clock.advance(10)
        self.assertRoutesTo('beta.one', ['beta:2002:b'])

    def testRemovesRuleWhenFileChanges(self):
        rules = """
[default]
default = true
destinations = default:2003:d
"""

        self.assertRoutesTo('alpha.one', ['alpha:2001:a'])
        self.reloadRules(rules, 2000)
        self.assertRoutesTo('alpha.one', ['default:2003:d'])

    def testChangesRuleOrderWhenFileChanges(self):
        rules = """
[beta]
pattern = ^(alpha|beta)\\.
destinations = beta:2002:b
continue = false

[alpha]
pattern = ^alpha\\.
destinations = alpha:2001:a
continue = true

[default]
default = true
destinations = default:2003:d
"""

        self.assertRoutesTo('alpha.one', ['alpha:2001:a'])
        self.reloadRules(rules, 2000)
        self.assertRoutesTo('alpha.one', ['beta:2002:b'])

        rules = """
[alpha]
pattern = ^alpha\\.
destinations = alpha:2001:a
continue = false

[beta]
pattern = ^(alpha|beta)\\.
destinations = beta:2002:b
continue = false

[default]
default = true
destinations = default:2003:d
"""
        self.reloadRules(rules, 3000)
        self.assertRoutesTo('alpha.one', ['alpha:2001:a'])

    def testReloadsPatternContinueDefaultAndDestinations(self):
        rules = """
[rule]
pattern = ^gamma\\.
destinations = beta:2002:b
continue = true

[default]
default = true
destinations = other:2004:o
"""

        self.reloadRules(rules, 2000)
        self.assertRoutesTo('gamma.one', ['beta:2002:b', 'other:2004:o'])
        self.assertRoutesTo('alpha.one', ['other:2004:o'])

    def testKeepsPreviousRulesWhenNewConfigIsInvalid(self):
        invalid_rules = (
            """
[alpha]
pattern = ^alpha\\.

[default]
default = true
destinations = default:2003:d
""",
            """
[alpha]
pattern = [
destinations = alpha:2001:a

[default]
default = true
destinations = default:2003:d
""",
            """
[alpha]
pattern = ^alpha\\.
destinations = alpha:2001:a
""",
        )

        for mtime, rules in enumerate(invalid_rules, start=2000):
            self.reloadRules(rules, mtime)
            self.assertRoutesTo('alpha.one', ['alpha:2001:a'])
            self.assertRoutesTo('beta.one', ['default:2003:d'])


class TestOtherRouters(unittest.TestCase):
    def testBasic(self):
        settings = createSettings()
        for plugin in routers.DatapointRouter.plugins:
            # Test everything except 'rules' which is special
            if plugin == 'rules':
                continue

            router = routers.DatapointRouter.plugins[plugin](settings)
            self.assertEqual(len(list(router.getDestinations('foo.bar'))), 0)

            for destination in DESTINATIONS:
                router.addDestination(parseDestination(destination))
            self.assertEqual(
                len(list(router.getDestinations('foo.bar'))),
                len(DESTINATIONS) if plugin == 'constant' else settings['REPLICATION_FACTOR']
            )
