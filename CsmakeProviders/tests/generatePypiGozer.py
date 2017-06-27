# <copyright>
# (c) Copyright 2017 Hewlett Packard Enterprise Development LP
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# </copyright>
# <copyright>
# (c) Copyright 2017 Hewlett Packard Enterprise Development LP
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# </copyright>
#!/usr/bin/python
# Execute like:
#   PYTHONPATH=..:
import PypiProvider
import pickle
import urllib2
import os.path
import logging

class FakeLog:
    def __init__(self):
        self.log = logging
        logging.devdebug = logging.debug
log = FakeLog()

fakectxt = PypiProvider.PypiContext({'name':'fake'}, log)

target='http://pypi.gozer.hpcloud.net/openstack'
mirrorpath='latest'
plt = PypiProvider.PullLinksThread(target, mirrorpath, log)
plt.start()
plt.join()
url, links = plt.getLinks()

pypiDict = {}
outliers = {}

for link, _ in links:
    _, package = os.path.split(link)
    expected = {'package': package}
    plt = PypiProvider.PullLinksThread(target, "%s/%s"% (mirrorpath,link.rstrip('/')), log)
    plt.start()
    plt.join()
    packageurl, packagelinks = plt.getLinks()
    print packageurl, packagelinks
    packagefiles = []
    for packagelink, _ in packagelinks:
        path, filename = os.path.split(packagelink)
        for ext in PypiProvider.PypiContext.SUPPORTED_EXTENSIONS:
            if filename.endswith(ext):
                packagefiles.append(filename)
    if len(packagefiles) == 0:
        continue

    for filename in packagefiles:
        print "Processing file: ", filename
        try:
            result = fakectxt._splitPypiName(filename, {})
        except ValueError as e:
            if package not in outliers:
                outliers[package] = []
            print "outlier: ", str(e)
            outliers[package].append((filename, str(e)))
            continue
        print filename
        print result
        if package not in pypiDict:
            pypiDict[package] = []
        pypiDict[package].append( (filename, result) )

print "pypiDict = ", str(pypiDict)
print "outliers = ", str(outliers)
with open("gozer.pickle", "wb") as p:
    pickle.dump(pypiDict, p)
 
