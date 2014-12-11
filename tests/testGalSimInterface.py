from __future__ import with_statement
import os
import numpy
import unittest
import eups
import lsst.utils.tests as utilsTests
from lsst.sims.photUtils import Bandpass, Sed
from lsst.sims.catalogs.measures.instance import InstanceCatalog
from lsst.sims.catalogs.generation.utils import makePhoSimTestDB
from lsst.sims.catUtils.galSimInterface import GalSimGalaxies
from lsst.sims.catUtils.utils import testGalaxyBulge
import lsst.afw.image as afwImage

class testGalaxies(GalSimGalaxies):
    column_outputs = GalSimGalaxies.column_outputs
    column_outputs.remove('fitsFiles')
    column_outputs.append('magNorm')
    column_outputs.append('redshift')
    column_outputs.append('internalAv')
    column_outputs.append('internalRv')
    column_outputs.append('galacticAv')
    column_outputs.append('galacticRv')
    column_outputs.append('fitsFiles')

def calcADUwrapper(sedName=None, magNorm=None, redshift=None, internalAv=None, internalRv=None,
                   galacticAv=None, galacticRv=None, bandpass=None):

    imsimband = Bandpass()
    imsimband.imsimBandpass()
    sedDir = os.getenv('SIMS_SED_LIBRARY_DIR')
    sedFile = os.path.join(sedDir, sedName)
    sed = Sed()
    sed.readSED_flambda(sedFile)
    fNorm = sed.calcFluxNorm(magNorm, imsimband)
    sed.multiplyFluxNorm(fNorm)
    if internalAv is not None and internalRv is not None:
        if internalAv != 0.0 and internalRv != 0.0:
            a_int, b_int = sed.setupCCMab()
            sed.addCCMDust(a_int, b_int, A_v=internalAv, R_v=internalRv)
    
    if redshift is not None and redshift!=0.0:
        sed.redshiftSED(redshift, dimming=False)
    
    a_int, b_int = sed.setupCCMab()
    sed.addCCMDust(a_int, b_int, A_v=galacticAv, R_v=galacticRv)
    
    adu = sed.calcADU(bandpass)
    
    return adu

class GalSimInterfaceTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dbName = 'galSimTestDB.db'
        if os.path.exists(cls.dbName):
            os.unlink(cls.dbName)
        
        displacedRA = numpy.array([72.0/3600.0])
        displacedDec = numpy.array([0.0])
        cls.obs_metadata = makePhoSimTestDB(filename=cls.dbName, size=1,
                                            displacedRA=displacedRA, displacedDec=displacedDec)
        cls.connectionString = 'sqlite:///'+cls.dbName

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.dbName):
            os.unlink(cls.dbName)

        del cls.dbName
        del cls.connectionString
        del cls.obs_metadata

    def testGalaxyBulge(self):
        catName = 'galaxyBulgeCatalog.sav'
        gals = testGalaxyBulge(address=self.connectionString)
        cat = GalSimGalaxies(gals, obs_metadata = self.obs_metadata)
        cat.write_catalog(catName)
        cat.write_images()
        
        with open(catName, 'r') as testFile:
            lines = testFile.readlines()
            gg = lines[len(lines)-1].split(';')
            sedName = gg[5]
            magNorm = float(gg[11])
            redshift = float(gg[12])
            internalAv = float(gg[13])
            internalRv = float(gg[14])
            galacticAv = float(gg[15])
            galacticRv = float(gg[16])
        
            for name in cat.galSimInterpreter.detectorObjects:
                print name
                im = afwImage.ImageF(name)
                imArr = im.getArray()
                galsimCounts = imArr.sum()
                
                filterName = name[-6]
                bandPassName=os.path.join(eups.productDir('throughputs'),'baseline',('total_'+filterName+'.dat'))
                bandpass = Bandpass()
                bandpass.readThroughput(bandPassName)
                controlCounts = calcADUwrapper(sedName=sedName, bandpass=bandpass, redshift=redshift, magNorm=magNorm,
                                               internalAv=internalAv, internalRv=internalRv, galacticAv=galacticAv,
                                               galacticRv=galacticRv)
                
                self.assertTrue(numpy.abs(controlCounts-galsimCounts) < 0.05*galsimCounts)

def suite():
    utilsTests.init()
    suites = []
    suites += unittest.makeSuite(GalSimInterfaceTest)

    return unittest.TestSuite(suites)

def run(shouldExit = False):
    utilsTests.run(suite(), shouldExit)
if __name__ == "__main__":
    run(True)
