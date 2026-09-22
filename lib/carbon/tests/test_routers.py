import os
import tempfile
import unittest

from carbon import routers
from carbon.exceptions import CarbonConfigException
from carbon.util import parseDestinations
from carbon.tests import util


DESTINATIONS = (
    'foo:124:a',
    'foo:125:b',
    'foo:126:c',
    'bar:423:a',
    'bar:424:b',
    'bar:425:c',
)


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
    def setUp(self):
        fd, self.rules_path = tempfile.mkstemp(suffix='-relay-rules.conf')
        os.close(fd)
        self.addCleanup(os.unlink, self.rules_path)
        self.rules_mtime = 1000

    def tearDown(self):
        if hasattr(self, 'router'):
            self.router.rule_manager.read_task.stop()

    def writeRelayRules(self, rules):
        self.rules_mtime += 1
        with open(self.rules_path, 'w') as rules_file:
            rules_file.write(rules)
        os.utime(self.rules_path, (self.rules_mtime, self.rules_mtime))

    def createRouter(self):
        settings = createSettings()
        settings['relay-rules'] = self.rules_path
        self.router = routers.RelayRulesRouter(settings)
        for destination in DESTINATIONS:
            self.router.addDestination(parseDestination(destination))
        return self.router

    def destinationsFor(self, metric):
        return list(self.router.getDestinations(metric))

    def testBasic(self):
        self.writeRelayRules('\n'.join((
            '[alpha]',
            'pattern = ^alpha',
            'destinations = foo:124:a',
            '[default]',
            'destinations = foo:126:c',
            'default = true',
        )))
        self.createRouter()
        self.assertEqual(len(self.destinationsFor('alpha.bar')), 1)

    def testStartsReloadTask(self):
        self.writeRelayRules('\n'.join((
            '[default]',
            'destinations = foo:124:a',
            'default = true',
        )))
        router = self.createRouter()
        self.assertTrue(router.rule_manager.read_task.running)
        self.assertEqual(
            router.rule_manager.read_task.f,
            router.rule_manager.read_rules
        )

    def testAddsRuleWhenFileChanges(self):
        self.writeRelayRules('\n'.join((
            '[alpha]',
            'pattern = ^alpha',
            'destinations = foo:124:a',
            '[default]',
            'destinations = foo:126:c',
            'default = true',
        )))
        self.createRouter()

        self.assertEqual(self.destinationsFor('gamma.bar'),
                         [parseDestination('foo:126:c')])

        self.writeRelayRules('\n'.join((
            '[alpha]',
            'pattern = ^alpha',
            'destinations = foo:124:a',
            '[gamma]',
            'pattern = ^gamma',
            'destinations = foo:125:b',
            '[default]',
            'destinations = foo:126:c',
            'default = true',
        )))
        self.router.rule_manager.read_rules()

        self.assertEqual(self.destinationsFor('gamma.bar'),
                         [parseDestination('foo:125:b')])

    def testRemovesRuleWhenFileChanges(self):
        self.writeRelayRules('\n'.join((
            '[alpha]',
            'pattern = ^alpha',
            'destinations = foo:124:a',
            '[beta]',
            'pattern = ^beta',
            'destinations = foo:125:b',
            '[default]',
            'destinations = foo:126:c',
            'default = true',
        )))
        self.createRouter()

        self.writeRelayRules('\n'.join((
            '[alpha]',
            'pattern = ^alpha',
            'destinations = foo:124:a',
            '[default]',
            'destinations = foo:126:c',
            'default = true',
        )))
        self.router.rule_manager.read_rules()

        self.assertEqual(self.destinationsFor('beta.bar'),
                         [parseDestination('foo:126:c')])

    def testUsesChangedRuleOrder(self):
        self.writeRelayRules('\n'.join((
            '[broad]',
            'pattern = ^alpha',
            'destinations = foo:124:a',
            '[specific]',
            'pattern = ^alpha[.]special',
            'destinations = foo:125:b',
            '[default]',
            'destinations = foo:126:c',
            'default = true',
        )))
        self.createRouter()

        self.assertEqual(self.destinationsFor('alpha.special'),
                         [parseDestination('foo:124:a')])

        self.writeRelayRules('\n'.join((
            '[specific]',
            'pattern = ^alpha[.]special',
            'destinations = foo:125:b',
            '[broad]',
            'pattern = ^alpha',
            'destinations = foo:124:a',
            '[default]',
            'destinations = foo:126:c',
            'default = true',
        )))
        self.router.rule_manager.read_rules()

        self.assertEqual(self.destinationsFor('alpha.special'),
                         [parseDestination('foo:125:b')])
        self.assertEqual(self.destinationsFor('alpha.normal'),
                         [parseDestination('foo:124:a')])

    def testUpdatesContinuePatternDefaultAndDestinations(self):
        self.writeRelayRules('\n'.join((
            '[old]',
            'pattern = ^alpha',
            'continue = true',
            'destinations = foo:124:a',
            '[default]',
            'destinations = foo:126:c',
            'default = true',
        )))
        self.createRouter()

        self.assertEqual(self.destinationsFor('alpha.foo'), [
            parseDestination('foo:124:a'),
            parseDestination('foo:126:c'),
        ])

        self.writeRelayRules('\n'.join((
            '[updated]',
            'pattern = ^beta',
            'continue = false',
            'destinations = foo:125:b,bar:423:a',
            '[default]',
            'default = false',
            'destinations = foo:126:c',
            '[fallback]',
            'default = true',
            'destinations = bar:424:b',
        )))
        self.router.rule_manager.read_rules()

        self.assertEqual(self.destinationsFor('alpha.foo'),
                         [parseDestination('bar:424:b')])
        self.assertEqual(self.destinationsFor('beta.foo'), [
            parseDestination('foo:125:b'),
            parseDestination('bar:423:a'),
        ])

    def testKeepsPreviousRulesWhenNewRulesAreInvalid(self):
        self.writeRelayRules('\n'.join((
            '[alpha]',
            'pattern = ^alpha',
            'destinations = foo:124:a',
            '[default]',
            'destinations = foo:126:c',
            'default = true',
        )))
        self.createRouter()
        original_rules = self.router.rule_manager.rules

        self.writeRelayRules('\n'.join((
            '[alpha]',
            'pattern = ^alpha(',
            'destinations = foo:124:a',
            '[default]',
            'destinations = foo:126:c',
            'default = true',
        )))
        self.router.rule_manager.read_rules()

        self.assertIs(self.router.rule_manager.rules, original_rules)
        self.assertEqual(self.destinationsFor('alpha.foo'),
                         [parseDestination('foo:124:a')])
        self.assertEqual(self.destinationsFor('beta.foo'),
                         [parseDestination('foo:126:c')])

        self.writeRelayRules('\n'.join((
            '[beta]',
            'pattern = ^beta',
            'destinations = foo:125:b',
            '[default]',
            'destinations = foo:126:c',
            'default = true',
        )))
        self.router.rule_manager.read_rules()

        self.assertEqual(self.destinationsFor('alpha.foo'),
                         [parseDestination('foo:126:c')])
        self.assertEqual(self.destinationsFor('beta.foo'),
                         [parseDestination('foo:125:b')])

    def testInvalidInitialRulesRaise(self):
        self.writeRelayRules('\n'.join((
            '[alpha]',
            'pattern = ^alpha',
        )))
        with self.assertRaises(CarbonConfigException):
            self.createRouter()


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
