#One thing to be aware of: If the logic in Astrometry.py or Photometry.py changes,
#this unittest will fail, even if it is still possible to generate phoSim input
#catalogs.  This test is based on a simple line-by-line comparison of a phoSim
#input catalog with a previously generated catalog that should be identical.
#If we end up changing the logic in Astromtetry or Photometry, we will need to
#re-generate the testData/phoSimControlCatalog.txt to be consistent with the new code.

import os
import unittest
import lsst.utils.tests as utilsTests
import sqlite3
import numpy
import json
import eups
from collections import OrderedDict
from lsst.sims.catalogs.measures.instance import compound
from lsst.sims.catUtils.utils import testStars, testGalaxyDisk, testGalaxyBulge, testGalaxyAgn
from lsst.sims.catUtils.exampleCatalogDefinitions import PhoSimCatalogSersic2D, PhoSimCatalogPoint, \
                                                         PhoSimCatalogZPoint
from lsst.sims.catalogs.generation.utils import makePhoSimTestDB

class PhoSimCatalogTest(unittest.TestCase):

    def setUp(self):
        self.obs_metadata = makePhoSimTestDB(size=10)
        self.bulgeDB = testGalaxyBulge(address='sqlite:///PhoSimTestDatabase.db')
        self.diskDB = testGalaxyDisk(address='sqlite:///PhoSimTestDatabase.db')
        self.agnDB = testGalaxyAgn(address='sqlite:///PhoSimTestDatabase.db')
        self.starDB = testStars(address='sqlite:///PhoSimTestDatabase.db')
        baseLineFileName = eups.productDir('sims_catUtils')+'/tests/testData/phoSimControlCatalog.txt'
        self.baseLineFile = open(baseLineFileName,'r')

    def tearDown(self):

        self.baseLineFile.close()

        if os.path.exists('PhoSimTestDatabase.db'):
            os.unlink('PhoSimTestDatabase.db')

    def testCatalog(self):
        """
        This test writes a PhoSim input catalog and compares it, one line at a time
        to a previously written catalog that should be identical.
        """
        testBulge = PhoSimCatalogSersic2D(self.bulgeDB, obs_metadata = self.obs_metadata)
        testDisk = PhoSimCatalogSersic2D(self.diskDB, obs_metadata = self.obs_metadata)
        testAgn = PhoSimCatalogZPoint(self.agnDB, obs_metadata = self.obs_metadata)
        testStar = PhoSimCatalogPoint(self.starDB, obs_metadata = self.obs_metadata)

        catName = 'phoSimTestCatalog.txt'
        testBulge.write_catalog(catName)
        testDisk.write_catalog(catName, write_header=False, write_mode='a')
        testAgn.write_catalog(catName, write_header=False, write_mode='a')
        testStar.write_catalog(catName, write_header=False, write_mode='a')

        testFile = open(catName,'r')
        testLines = testFile.readlines()
        testFile.close()
        controlLines = self.baseLineFile.readlines()
        for line in testLines:
            self.assertTrue(line in controlLines)

        for line in controlLines:
            self.assertTrue(line in testLines)

        if os.path.exists(catName):
            os.unlink(catName)

def suite():
    utilsTests.init()
    suites = []
    suites += unittest.makeSuite(PhoSimCatalogTest)

    return unittest.TestSuite(suites)

def run(shouldExit = False):
    utilsTests.run(suite(), shouldExit)
if __name__ == "__main__":
    run(True)
