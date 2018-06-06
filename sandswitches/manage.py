# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Config management API and helpers.
"""
import time
import logging
import os
import tempfile
from io import BytesIO
from collections import namedtuple
from lxml import etree
from plumbum import ProcessExecutionError
from .utils import RestoreFile
from .orms import buildfromschema
from .schema import _models


log = logging.getLogger('sandswitches')


class CLIError(Exception):
    '''`fs_cli` command error'''


class CLIConnectionError(CLIError):
    '''Failed to connect to local ESL on `fs_cli` commands'''


class cli(object):
    """``fs_cli`` wrapper which quacks like a func and can raise
    errors based on string handlers.
    """
    CLIError = CLIError
    CLIConnectionError = CLIConnectionError

    def __init__(self, ssh, *args, **kwargs):
        self.ssh = ssh
        self._cli = self.get_cli(*args, **kwargs)

    def get_cli(self, *args, **kwargs):
        """Build and return an ``fs_cli`` command instance.
        """
        cli = self.ssh['fs_cli']
        for arg in args:
            cli = cli['--{}'.format(arg)]

        for key, value in kwargs.items():
            cli = cli['--{}={}'.format(key, value)]

        return cli['-x']

    def __call__(self, *tokens, **erroron):
        '''Invoke an `fs_cli` command and return output with error handling.
        '''
        try:
            out = self._cli(' '.join(map(str, tokens))).strip()
        except ProcessExecutionError as err:
            raise CLIConnectionError(str(err))

        lines = out.splitlines()
        if lines and lines[-1].startswith('-ERR'):
            raise CLIError(out)

        if erroron:
            for name, func in erroron.items():
                if func(out):
                    raise CLIError(out)
        return out

    def eval(self, expr):
        """Eval an expression in ``fs_cli``.
        """
        return self('eval', expr)


class ConfigManager(object):
    '''Manages a collection of restorable XML objects discovered in the
    FreeSWITCH config directories.
    '''
    def __init__(self, rfile, etree, sftp, fscli, log):
        self.etree = etree
        self.root = etree.getroot()
        self.file = rfile
        self.sftp = sftp
        self.cli = fscli
        self.log = log
        self._touched = []

    @property
    def fscli(self):
        """Alias for self.cli
        """
        return self.cli

    def revert(self):
        """Revert all changes to the root config file.
        """
        self.log.debug("restoring '{}'".format(self.file.path))
        self.file.restore()

    def commit(self):
        """Commit the working XML etree to the remote FreeSWITCH config.
        """
        now = time.time()
        self.log.info("saving '{}'".format(self.file.path))
        # write local copy
        self.sftp.putfo(
            BytesIO(etree.tostring(self.etree, pretty_print=True)),
            self.file.path
        )
        self.fscli.api('reloadxml')
        log.debug("freeswitch.xml commit took {} seconds"
                  .format(time.time() - now))

    def sofia_status(self):
        """Return status data from sofia in a nicely organized dict.
        """
        # remove '===' "lines"
        lines = [
            line for line in self.fscli.api('sofia status').splitlines()
            if '===' not in line]
        # pop summary line
        lines.pop(-1)

        # build component to status maps
        profiles = {}
        gateways = {}
        aliases = {}

        colnames = [name.lower() for name in lines.pop(0).split()]
        iname = colnames.index('name')
        colnames.remove('name')
        for line in lines:
            fields = [field.strip() for field in line.split('\t')]
            name = fields.pop(iname)
            row = {k.lower(): v for k, v in zip(colnames, fields)}
            tp = row.pop('type')
            if tp == 'profile':
                profiles[name] = row
            elif tp == 'gateway':
                profname, gwname = name.split("::")
                row['profile'] = profname
                gateways[gwname] = row
            elif tp == 'alias':
                aliases[name] = row

        return {'profiles': profiles, 'gateways': gateways, 'aliases': aliases}

    def get_users(self, **kwargs):
        """Return all directory users in a map keyed by domain name.
        """
        args = []
        allowed = ('domain', 'group', 'user', 'context')
        for argname, value in kwargs.items():
            if argname not in allowed:
                raise ValueError(
                    '{} is not a valid argument to list_users'.format(
                        argname)
                )
            args.append('{} {}'.format(argname, value))

        # last two lines are entirely useless
        res = self.cli('list_users', *args).splitlines()[:-2]
        UserEntry = namedtuple("UserEntry", res[0].split('|'))
        # collect and pack all users
        users = []
        for row in res[1:]:
            users.append(UserEntry(*row.split('|')))

        # pack users by domain
        domains = {}
        for user in users:
            domains.setdefault(user.domain, []).append(user)

        return domains


def manage_config(rootpath, sftp, fscli, log, singlefile=True):
    """Manage the FreeSWITCH configuration found at ``rootpath`` or as
    auto-discovered using ``fs_cli`` over ssh. By default all XML configs are
    squashed down to a single ``freeswitch.xml`` file.
    """
    parser = etree.XMLParser(remove_blank_text=True)
    confpath = os.path.join(rootpath, 'freeswitch.xml')

    # copy to a local path and parse for speed
    start = time.time()
    _, localpath = tempfile.mkstemp(
        prefix='sandswitches-config',
        suffix='.xml',
    )
    with open(localpath, 'wb') as fxml:  # open as bytes
        sftp.getfo(confpath, fxml)
    with open(localpath, 'r') as fxml:
        tree = etree.parse(fxml, parser)
    log.info("Parsing {} into an etree took {} seconds".format(
        confpath, time.time() - start))

    # check if this is a single-file config by trying to access the
    # sofia configuration section
    if not tree.xpath('section/configuration[@name="sofia.conf"]'):
        log.info("Dumping aggregate freeswitch.xml config...")
        # parse the single-document config
        root = etree.fromstring(fscli.api('xml_locate root'), parser=parser)
        tree = etree.ElementTree(root)

        # remove all ignored whitespace from tail text since FS doesn't
        # use element text whatsoever
        for elem in root.iter():
            elem.tail = None
            if elem.text is not None:
                elem.text = os.linesep.join(
                    (s for s in elem.text.splitlines() if s.strip()))

        # back up original freeswitch.xml root config
        backup = confpath + time.strftime('_backup_%Y-%m-%d-%H-%M-%S')
        log.info("Backing up old {} as {}...".format(confpath, backup))
        sftp.rename(confpath, backup)

        with sftp.open(confpath, 'w') as fxml:
            fxml.write(etree.tostring(tree, pretty_print=True))

    mng = ConfigManager(
        RestoreFile(confpath, open=sftp.open if sftp else open),
        tree, sftp, fscli, log
    )

    # apply section mapped models as attrs
    for f, cls in _models:
        section = buildfromschema(
            cls, getattr(cls, 'schema', None), root=mng.root,
            log=log, confmng=mng
        )
        setattr(mng, section.name, section)

    return mng
