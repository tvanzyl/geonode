#########################################################################
#
# Copyright (C) 2012 OpenPlans
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################

import os
import sys
import time
import urllib
import zipfile
import shutil
from StringIO import StringIO

from paver.easy import task, options, cmdopts, needs
from paver.easy import path, sh, pushd, info, call_task
from paver.easy import BuildFailure

assert sys.version_info >= (2, 6, 2), \
    SystemError("GeoNode Build requires python 2.6.2 or better")


def grab(src, dest):
    urllib.urlretrieve(str(src), str(dest))

GEOSERVER_URL="http://downloads.sourceforge.net/geoserver/geoserver-2.2.3-bin.zip"
GEONODE_GEOSERVER_EXT_URL="http://build.geonode.org/geoserver/latest/geonode-geoserver-ext-0.3-geoserver-plugin.zip"

@task
@cmdopts([
    ('fast', 'f', 'Fast. Skip some operations for speed.'),
])
def setup_geoserver(options):
    """Prepare a testing instance of GeoServer."""
    fast = options.get('fast', False)
    download_dir = path('downloaded')
    download_dir.makedirs()

    geoserver_dir = path('geoserver')

    geoserver_bin = download_dir / os.path.basename(GEOSERVER_URL)
    geoserver_ext = download_dir / os.path.basename(GEONODE_GEOSERVER_EXT_URL)

    if not geoserver_bin.exists():
        print "Downloading geoserver binary distribution"
        grab(GEOSERVER_URL, geoserver_bin)
    elif not zipfile.is_zipfile(geoserver_bin):
        print "Downloading geoserver binary distribution (corrupt file)"
        grab(GEOSERVER_URL, geoserver_bin)

    if not geoserver_ext.exists():
        print "Downloading geonode geoserver extensions"
        grab(GEONODE_GEOSERVER_EXT_URL, geoserver_ext)
    elif not zipfile.is_zipfile(geoserver_ext):
        print "Re-downloading geonode geoserver extensions (corrupt file)"
        grab(GEONODE_GEOSERVER_EXT_URL, geoserver_ext)

    if not geoserver_dir.exists():
        with zipfile.ZipFile(geoserver_bin, "r") as z:
            z.extractall(download_dir)

        #FIXME(Ariel): Avoid hardcoding.
        g = download_dir / "geoserver-2.2.3"
        libs_dir = g / "webapps/geoserver/WEB-INF/lib"

        with zipfile.ZipFile(geoserver_ext, "r") as z:
            z.extractall(libs_dir)

        # Move geoserver out of downloaded
        geoserver_dir.remove()
        shutil.move(g, geoserver_dir)

@task
def setup_geoexplorer(options):
    """
    Fetch GeoExplorer
    """
    geoxp_zip = StringIO()
    geoxp_zip.write(urllib.urlopen("http://suite.opengeo.org/builds/geoexplorer/opengeosuite-dev-geoexplorer-static.zip").read())
    geoxp_zipfile = zipfile.ZipFile(geoxp_zip)
    filelist = geoxp_zipfile.filelist
    root_dir = filelist[0].filename
    for afile in filelist:
        geoxp_zipfile.extract(afile, "geonode/static/")
    geoxp_zipfile.close()
    if os.path.exists("geonode/static/geoexplorer"):
        shutil.rmtree("geonode/static/geoexplorer")
    shutil.move("geonode/static/%s" % root_dir, "geonode/static/geoexplorer")


@task
@needs([
    'setup_geoserver',
    'setup_geoexplorer',
])
def setup(options):
    """Get dependencies and prepare a GeoNode development environment."""
    sh('pip install -e .')

    info(('GeoNode development environment successfully set up.'
          'If you have not set up an administrative account,'
          ' please do so now. Use "paver start" to start up the server.'))


@cmdopts([
    ('version=', 'v', 'Legacy GeoNode version of the existing database.')
])
@task
def upgradedb(options):
    """
    Add 'fake' data migrations for existing tables from legacy GeoNode versions
    """
    version = options.get('version')
    if version in ['1.1', '1.2']:
        sh("python manage.py migrate maps 0001 --fake")
        sh("python manage.py migrate avatar 0001 --fake")
    elif version is None:
        print "Please specify your GeoNode version"
    else:
        print "Upgrades from version %s are not yet supported." % version


@task
def sync(options):
    """
    Run the syncdb and migrate management commands to create and migrate a DB
    """
    sh("python manage.py syncdb --all --noinput")
    #sh("python manage.py migrate --noinput")
    sh("python manage.py loaddata sample_admin.json")


@task
def package(options):
    """
    Creates a tarball to use for building the system elsewhere
    """
    import pkg_resources
    import tarfile
    import geonode

    version = geonode.get_version()
    # Use GeoNode's version for the package name.
    pkgname = 'GeoNode-%s-all' % version

    # Create the output directory.
    out_pkg = path(pkgname)
    out_pkg_tar = path("%s.tar.gz" % pkgname)

    # Create a distribution in zip format for the geonode python package.
    sh('python setup.py sdist --format=zip')

    with pushd('package'):
        if out_pkg_tar.exists():
            info('There is already a package for version %s' % version)
            return

        # Clean anything that is in the oupout package tree.
        out_pkg.rmtree()
        out_pkg.makedirs()

        support_folder = path('support')
        install_file = path('install.sh')

        # And copy the default files from the package folder.
        justcopy(support_folder, out_pkg / 'support')
        justcopy(install_file, out_pkg)

        # Package Geoserver's war.
        geoserver_path = ('../geoserver-geonode-ext/target/'
                          'geonode-geoserver-ext-0.3.jar')
        geoserver_target = path(geoserver_path)
        geoserver_target.copy(out_pkg)

        geonode_dist = path('..') / 'dist' / 'GeoNode-%s.zip' % version
        justcopy(geonode_dist, out_pkg)

        # Create a tar file with all files in the output package folder.
        tar = tarfile.open(out_pkg_tar, "w:gz")
        for file in out_pkg.walkfiles():
            tar.add(file)

        # Add the README with the license and important links to documentation.
        tar.add('README', arcname=('%s/README.rst' % out_pkg))
        tar.close()

        # Remove all the files in the temporary output package directory.
        out_pkg.rmtree()

    # Report the info about the new package.
    info("%s.tar.gz created" % out_pkg.abspath())


@task
@needs(['start_geoserver',
        'sync',
        'start_django'])
@cmdopts([
    ('bind=', 'b', 'Bind server to provided IP address and port number.')
], share_with=['start_django'])
def start():
    """
    Start GeoNode (Django, GeoServer & Client)
    """
    info("GeoNode is now available.")


def stop_django():
    """
    Stop the GeoNode Django application
    """
    kill('python', 'runserver')


def stop_geoserver():
    """
    Stop GeoServer
    """
    kill('java', 'geoserver')


@task
def stop():
    """
    Stop GeoNode
    """
    info("Stopping GeoNode ...")
    stop_django()
    stop_geoserver()


@cmdopts([
    ('bind=', 'b', 'Bind server to provided IP address and port number.')
])
@task
def start_django():
    """
    Start the GeoNode Django application
    """
    bind = options.get('bind', '')
    sh('python manage.py runserver %s &' % bind)


@task
def start_geoserver(options):
    """
    Start GeoServer with GeoNode extensions
    """

    from geonode.settings import GEOSERVER_BASE_URL

    with pushd('geoserver/bin/'):
        sh(('JAVA_OPTS="-Xmx512m -XX:MaxPermSize=256m"'
            ' JAVA_HOME="/usr"'
            ' sh startup.sh'
            ' > /dev/null &'
            ))

    info('Starting GeoServer on %s' % GEOSERVER_BASE_URL)
    # wait for GeoServer to start
    started = waitfor(GEOSERVER_BASE_URL)
    if not started:
        # If applications did not start in time we will give the user a chance
        # to inspect them and stop them manually.
        info(('GeoServer never started properly or timed out.'
              'It may still be running in the background.'))
        info('The logs are available at geoserver-geonode-ext/jetty.log')
        sys.exit(1)


@task
def test(options):
    """
    Run GeoNode's Unit Test Suite
    """
    sh("python manage.py test geonode --noinput")


@task
def test_javascript(options):
    with pushd('geonode/static/geonode'):
        sh('./run-tests.sh')


@task
@cmdopts([
    ('name=', 'n', 'Run specific tests.')
    ])
def test_integration(options):
    """
    Run GeoNode's Integration test suite against the external apps
    """
    _reset()
    # Start GeoServer
    call_task('start_geoserver')
    info("GeoNode is now available, running the tests now.")

    name = options.get('name', 'geonode.tests.integration')

    success = False
    try:
        if name == 'geonode.tests.csw':
            call_task('start')
            sh('sleep 30')
            call_task('setup_data')
        sh(('python manage.py test %s'
           ' --noinput --liveserver=localhost:8000' % name))
    except BuildFailure, e:
        info('Tests failed! %s' % str(e))
    else:
        success = True
    finally:
        # don't use call task here - it won't run since it already has
        stop()

    _reset()
    if not success:
        sys.exit(1)


@task
@needs(['stop'])
def reset():
    """
    Reset a development environment (Database, GeoServer & Catalogue)
    """
    _reset()


def _reset():
    sh("rm -rf geonode/development.db")
    # Reset data dir (how do we do it?)


@needs(['reset'])
def reset_hard():
    """
    Reset a development environment (Database, GeoServer & Catalogue)
    """
    sh("git clean -dxf")


@task
@cmdopts([
    ('type=', 't', 'Import specific data type ("vector", "raster", "time")'),
])
def setup_data():
    """
    Import sample data (from gisdata package) into GeoNode
    """
    import gisdata

    ctype = options.get('type', None)

    data_dir = gisdata.GOOD_DATA

    if ctype in ['vector', 'raster', 'time']:
        data_dir = os.path.join(gisdata.GOOD_DATA, ctype)

    sh("python manage.py importlayers %s -v2" % data_dir)


@needs(['package'])
@cmdopts([
    ('key=', 'k', 'The GPG key to sign the package'),
    ('ppa=', 'p', 'PPA this package should be published to.'),
])
def deb(options):
    """
    Creates debian packages.

    Example uses:
        paver deb
        paver deb -k 12345
        paver deb -k 12345 -p geonode/testing
    """
    key = options.get('key', None)
    ppa = options.get('ppa', None)

    import geonode
    from geonode.version import get_git_changeset
    raw_version = geonode.__version__
    version = geonode.get_version()
    timestamp = get_git_changeset()

    major, minor, revision, stage, edition = raw_version

    # create a temporary file with the name of the branch
    sh('echo `git rev-parse --abbrev-ref HEAD` > .git_branch')
    branch = open('.git_branch', 'r').read().strip()
    # remove the temporary file
    sh('rm .git_branch')

    if stage == 'alpha' and edition == 0:
        tail = '%s%s' % (branch, timestamp)
    else:
        tail = '%s%s' % (stage, edition)

    simple_version = '%s.%s.%s+%s' % (major, minor, revision, tail)

    info('Creating package for GeoNode version %s' % version)

    with pushd('package'):
        # Get rid of any uncommitted changes to debian/changelog
        info('Getting rid of any uncommitted changes in debian/changelog')
        sh('git checkout debian/changelog')

        # Workaround for git-dch bug
        # http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=594580
        path('.git').makedirs()

        #sh('sudo apt-get -y install debhelper devscripts git-buildpackage')

        #sh(('git-dch --git-author --new-version=%s'
        #    ' --id-length=6 --ignore-branch' % (
        #    simple_version)))

        # Revert workaround for git-dhc bug
        path('.git').rmtree()

        if key is None:
            sh('debuild -uc -us -A')
        else:
            if ppa is None:
                sh('debuild -k%s -A' % key)
            else:
                sh('debuild -k%s -S' % key)
                sh('dput ppa:%s geonode_*.sources' % ppa)


def kill(arg1, arg2):
    """Stops a proces that contains arg1 and is filtered by arg2
    """
    from subprocess import Popen, PIPE

    # Wait until ready
    t0 = time.time()
    # Wait no more than these many seconds
    time_out = 30
    running = True

    while running and time.time() - t0 < time_out:
        p = Popen('ps aux | grep %s' % arg1, shell=True,
                  stdin=PIPE, stdout=PIPE, stderr=PIPE, close_fds=True)

        lines = p.stdout.readlines()

        running = False
        for line in lines:

            if '%s' % arg2 in line:
                running = True

                # Get pid
                fields = line.strip().split()

                info('Stopping %s (process number %s)' % (arg1, fields[1]))
                kill = 'kill -9 %s 2> /dev/null' % fields[1]
                os.system(kill)

        # Give it a little more time
        time.sleep(1)
    else:
        pass

    if running:
        raise Exception('Could not stop %s: '
                        'Running processes are\n%s'
                        % (arg1, '\n'.join([l.strip() for l in lines])))


def waitfor(url, timeout=300):
    started = False
    for a in xrange(timeout):
        try:
            resp = urllib.urlopen(url)
        except IOError, e:
            pass
        else:
            if resp.getcode() == 200:
                started = True
                break
        time.sleep(1)
    return started


def justcopy(origin, target):
    import shutil
    if os.path.isdir(origin):
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(origin, target)
    elif os.path.isfile(origin):
        if not os.path.exists(target):
            os.makedirs(target)
        shutil.copy(origin, target)
