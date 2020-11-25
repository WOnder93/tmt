import os
import click
import shutil
import re

import fmf
import tmt
import tmt.beakerlib
import tmt.steps.discover


class DiscoverFmf(tmt.steps.discover.DiscoverPlugin):
    """
    Discover available tests from fmf metadata

    By default all available tests from the current repository are used
    so the minimal configuration looks like this:

        discover:
            how: fmf

    Full config example:

        discover:
            how: fmf
            url: https://github.com/psss/tmt
            ref: master
            path: /fmf/root
            test: /tests/basic
            filter: 'tier: 1'

    It is also possible to limit tests only to those that have changed in git
    since a given revision. This can be particularly useful when testing
    changes to tests themselves (e.g. in a pull request CI).

    Related config options (all optional):
    * modified_only - set to True if you want to filter modified tests
    * reference_url - will be fetched as "reference" remote in the test dir
    * reference_ref - the ref to compare against

    Example to compare local repo against upstream master:

        discover:
            how: fmf
            modified_only: True
            reference_url: https://github.com/psss/tmt
            reference_ref: reference/master

    Note that internally the modified tests are appended to the list specified
    via 'test', so those tests will also be selected even if not modified.
    """

    # Supported methods
    _methods = [tmt.steps.Method(name='fmf', doc=__doc__, order=50)]

    @classmethod
    def options(cls, how=None):
        """ Prepare command line options for given method """
        return [
            click.option(
                '-u', '--url', metavar='REPOSITORY',
                help='URL of the git repository with fmf metadata.'),
            click.option(
                '-r', '--ref', metavar='REVISION',
                help='Branch, tag or commit specifying the git revision.'),
            click.option(
                '-U', '--reference-url', metavar='REPOSITORY',
                help='URL of the reference git repository with fmf metadata.'),
            click.option(
                '-R', '--reference-ref', metavar='REVISION',
                help='Branch, tag or commit specifying the reference git revision.'),
            click.option(
                '-m', '--only-modified', is_flag=True,
                help='If set, select only tests modified since reference revision.'),
            click.option(
                '-p', '--path', metavar='ROOT',
                help='Path to the metadata tree root.'),
            click.option(
                '-t', '--test', metavar='NAMES', multiple=True,
                help='Select tests by name.'),
            click.option(
                '-F', '--filter', metavar='FILTERS', multiple=True,
                help='Include only tests matching the filter.'),
            ] + super().options(how)

    def default(self, option, default=None):
        """ Return default data for given option """
        # Git revision defaults to master if url provided
        if option == 'ref' and self.get('url'):
            return 'master'
        if option == 'reference_ref':
            return 'master'
        # No other defaults available
        return default

    def show(self):
        """ Show discover details """
        super().show(['url', 'ref', 'path', 'test', 'filter'])

    def wake(self):
        """ Wake up the plugin (override data with command line) """

        # Handle backward-compatible stuff
        if 'repository' in self.data:
            self.data['url'] = self.data.pop('repository')
        if 'revision' in self.data:
            self.data['ref'] = self.data.pop('revision')

        # Make sure that 'filter' and 'test' keys are lists
        for key in ['filter', 'test']:
            if key in self.data and not isinstance(self.data[key], list):
                self.data[key] = [self.data[key]]

        # Process command line options, apply defaults
        for option in ['url', 'ref', 'reference_url', 'reference_ref', 'path',
                       'test', 'filter', 'only_modified']:
            value = self.opt(option)
            if value:
                self.data[option] = value

    def go(self):
        """ Discover available tests """
        super(DiscoverFmf, self).go()

        # Check url and path, prepare test directory
        url = self.get('url')
        path = self.get('path')
        testdir = os.path.join(self.workdir, 'tests')

        # Clone provided git repository (if url given)
        if url:
            self.info('url', url, 'green')
            self.debug(f"Clone '{url}' to '{testdir}'.")
            self.run(['git', 'clone', url, testdir], shell=False)
        # Copy git repository root to workdir
        else:
            if path and not os.path.isdir(path):
                raise tmt.utils.DiscoverError(
                    f"Provided path '{path}' is not a directory.")
            fmf_root = path or self.step.plan.run.tree.root
            # Check git repository root (use fmf root if not found)
            try:
                output = self.run(
                    'git rev-parse --show-toplevel', cwd=fmf_root, dry=True)
                git_root = output[0].strip('\n')
            except tmt.utils.RunError:
                self.debug(f"Git root not found, using '{fmf_root}.'")
                git_root = fmf_root
            # Set path to relative path from the git root to fmf root
            path = os.path.relpath(fmf_root, git_root)
            self.info('directory', git_root, 'green')
            self.debug(f"Copy '{git_root}' to '{testdir}'.")
            if not self.opt('dry'):
                shutil.copytree(git_root, testdir, symlinks=True)

        # Checkout revision if requested
        ref = self.get('ref')
        if ref:
            self.info('ref', ref, 'green')
            self.debug(f"Checkout ref '{ref}'.")
            self.run(['git', 'checkout', '-f', ref], cwd=testdir, shell=False)

        # Adjust path and optionally show
        if path is None or path == '.':
            path = ''
        else:
            self.info('path', path, 'green')

        # Prepare the whole tree path and test path prefix
        tree_path = os.path.join(testdir, path.lstrip('/'))
        if not os.path.isdir(tree_path) and not self.opt('dry'):
            raise tmt.utils.DiscoverError(
                f"Metadata tree path '{path}' not found.")
        prefix_path = os.path.join('/tests', path.lstrip('/'))

        # Show filters and test names if provided
        filters = self.get('filter', [])
        for filter_ in filters:
            self.info('filter', filter_, 'green')
        names = self.get('test', [])
        if names:
            self.info('names', fmf.utils.listed(names), 'green')

        only_modified = self.get('only_modified')
        ref_url = self.get('reference_url')
        if ref_url:
            self.info('reference_url', ref_url, 'green')
            self.debug(f"Fetch also '{ref_url}' as 'reference'.")
            self.run(['git', 'remote', 'add', 'reference', ref_url],
                     cwd=testdir, shell=False)
            self.run(['git', 'fetch', 'reference'], cwd=testdir, shell=False)
        if only_modified:
            reference_ref = self.get('reference_ref')
            self.info('reference_ref', reference_ref, 'green')
            output = self.run(['git', 'log', '--format=', '--stat',
                               '--name-only', f"{reference_ref}..HEAD"],
                              cwd=testdir, shell=False)[0]
            modified = set(f"^/{re.escape(name)}$"
                           for name in map(os.path.dirname, output.split('\n'))
                           if name)
            self.debug(f"Limit to modified test dirs: {modified}")
            names.extend(modified)

        # Initialize the metadata tree, search for available tests
        self.debug(f"Check metadata tree in '{tree_path}'.")
        if self.opt('dry'):
            self._tests = []
            return
        tree = tmt.Tree(path=tree_path, context=self.step.plan._fmf_context())
        self._tests = tree.tests(filters=filters, names=names)

        # Prefix tests and handle library requires
        for test in self._tests:
            # Prefix test path with 'tests' and possible 'path' prefix
            test.path = os.path.join(prefix_path, test.path.lstrip('/'))
            # Check for possible required beakerlib libraries
            if test.require or test.recommend:
                test.require, test.recommend, _ = tmt.beakerlib.dependencies(
                    test.require, test.recommend, parent=self)

    def tests(self):
        """ Return all discovered tests """
        return self._tests
