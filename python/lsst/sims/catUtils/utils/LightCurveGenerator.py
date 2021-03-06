from __future__ import print_function
from builtins import zip
from builtins import str
from builtins import object
import numpy as np
import copy
from collections import OrderedDict

from lsst.sims.catUtils.utils import ObservationMetaDataGenerator
from lsst.sims.catUtils.mixins import PhotometryStars, VariabilityStars
from lsst.sims.catUtils.mixins import PhotometryGalaxies, VariabilityGalaxies
from lsst.sims.catalogs.definitions import InstanceCatalog
from lsst.sims.catalogs.decorators import compound, cached
from lsst.sims.utils import haversine

import time

__all__ = ["StellarLightCurveGenerator",
           "FastStellarLightCurveGenerator",
           "AgnLightCurveGenerator",
           "FastAgnLightCurveGenerator",
           "_baseLightCurveCatalog",
           "LightCurveGenerator",
           "FastLightCurveGenerator"]

# a global cache to store SedLists loaded by the light curve catalogs
_sed_cache = {}


class _baseLightCurveCatalog(InstanceCatalog):
    """
    """

    column_outputs = ["uniqueId", "raJ2000", "decJ2000",
                      "lightCurveMag", "sigma_lightCurveMag",
                      "truthInfo", "quiescent_lightCurveMag"]

    def iter_catalog(self, chunk_size=None, query_cache=None, column_cache=None):
        """
        Returns an iterator over rows of the catalog.

        Parameters
        ----------
        chunk_size : int, optional, defaults to None
            the number of rows to return from the database at a time. If None,
            returns the entire database query in one chunk.

        query_cache : iterator over database rows, optional, defaults to None
            the result of calling db_obj.query_columns().  If query_cache is not
            None, this method will iterate over the rows in query_cache and produce
            an appropriate InstanceCatalog. DO NOT set to non-None values
            unless you know what you are doing.  It is an optional
            input for those who want to repeatedly examine the same patch of sky
            without actually querying the database over and over again.  If it is set
            to None (default), this method will handle the database query.

        column_cache : a dict that will be copied over into the catalogs self._column_cache.
            Should be left as None, unless you know what you are doing.
        """

        if query_cache is None:
            # Call the originalversion of iter_catalog defined in the
            # InstanceCatalog class.  This version of iter_catalog includes
            # the call to self.db_obj.query_columns, which the user would have
            # used to generate query_cache.
            for line in InstanceCatalog.iter_catalog(self, chunk_size=chunk_size):
                yield line
        else:
            # Otherwise iterate over the query cache
            transform_keys = list(self.transformations.keys())
            for chunk in query_cache:
                self._set_current_chunk(chunk, column_cache=column_cache)
                chunk_cols = [self.transformations[col](self.column_by_name(col))
                              if col in transform_keys else
                              self.column_by_name(col)
                              for col in self.iter_column_names()]
                # iterate over lines in the cache and yield lines augmented by
                # values calculated using this catalogs getter methods
                for line in zip(*chunk_cols):
                    yield line

    @cached
    def get_truthInfo(self):
        """
        Default information to be returned as 'truth_dict' by the
        LightCurveGenerator.
        """
        return self.column_by_name('varParamStr')


class _stellarLightCurveCatalog(_baseLightCurveCatalog, VariabilityStars, PhotometryStars):
    """
    This class wraps a basic stellar variability InstanceCatalog.  It provides its
    own photometry getter that

    1) only returns the magnitude and uncertainty in the bandpass specified by
    self.obs_metadata

    2) caches all of the SEDs read in so that they can be reused when sampling the
    objects in this catalog at a different MJD.

    It should only be used in the context of the LightCurveGenerator class.
    """

    def _loadSedList(self, wavelen_match):
        """
        Wraps the PhotometryStars._loadSedList method.

        If current chunk of objects is not represetned in the global
        _sed_cache, this will call the base method defined in
        PhotometryStars.

        Otherwise, it will read self._sedList from the cache.
        That way, the photometry getters defined in PhotometryStars will
        not read in SEDs that have already been cached.
        """

        global _sed_cache

        object_names = self.column_by_name("uniqueId")

        if len(object_names) > 0:
            cache_name = "stellar_%s_%s" % (object_names[0], object_names[-1])
        else:
            cache_name = None

        if cache_name not in _sed_cache:

            PhotometryStars._loadSedList(self, wavelen_match)

            if cache_name is not None:
                _sed_cache[cache_name] = copy.copy(self._sedList)
        else:
            self._sedList = copy.copy(_sed_cache[cache_name])

    @compound("lightCurveMag", "sigma_lightCurveMag", "quiescent_lightCurveMag")
    def get_lightCurvePhotometry(self):
        """
        A getter which returns the magnitudes and uncertainties in magnitudes
        in the bandpass specified by self.obs_metdata.

        As it runs, this method will cache the SedLists it reads in so that
        they can be used later.
        """

        if len(self.obs_metadata.bandpass) != 1:
            raise RuntimeError("_stellarLightCurveCatalog cannot handle bandpass "
                               "%s" % str(self.obs_metadata.bandpass))

        bp = self.obs_metadata.bandpass

        return np.array([self.column_by_name("lsst_%s" % bp),
                         self.column_by_name("sigma_lsst_%s" % bp),
                         self.column_by_name("lsst_%s" % bp) - self.column_by_name("delta_lsst_%s" % bp)])


class _agnLightCurveCatalog(_baseLightCurveCatalog, VariabilityGalaxies, PhotometryGalaxies):

    def _loadAgnSedList(self, wavelen_match):
        """
        Wraps the PhotometryGalaxies._loadAgnSedList method.

        If current chunk of objects is not represented in the global
        _sed_cache, this will call the base method defined in
        PhotometryGalaxies.

        Otherwise, it will read self._sedList from the cache.
        That way, the photometry getters defined in PhotometryGalaxies will
        not read in SEDs that have already been cached.
        """

        global _sed_cache

        object_names = self.column_by_name("uniqueId")

        if len(object_names) > 0:
            cache_name = "agn_%s_%s" % (object_names[0], object_names[-1])
        else:
            cache_name = None

        if cache_name not in _sed_cache:

            PhotometryGalaxies._loadAgnSedList(self, wavelen_match)

            if cache_name is not None:
                _sed_cache[cache_name] = copy.copy(self._agnSedList)
        else:
            self._agnSedList = copy.copy(_sed_cache[cache_name])

    @compound("lightCurveMag", "sigma_lightCurveMag", "quiescent_lightCurveMag")
    def get_lightCurvePhotometry(self):
        """
        A getter which returns the magnitudes and uncertainties in magnitudes
        in the bandpass specified by self.obs_metdata.

        As it runs, this method will cache the SedLists it reads in so that
        they can be used later.
        """

        if len(self.obs_metadata.bandpass) != 1:
            raise RuntimeError("_agnLightCurveCatalog cannot handle bandpass "
                               "%s" % str(self.obs_metadata.bandpass))

        bp = self.obs_metadata.bandpass

        return np.array([self.column_by_name("%sAgn" % bp),
                         self.column_by_name("sigma_%sAgn" % bp),
                         self.column_by_name("%sAgn" % bp) - self.column_by_name("delta_%sAgn" % bp)])


class LightCurveGenerator(object):
    """
    This class will find all of the OpSim pointings in a particular region
    of the sky in a particular filter and then return light curves for all
    of the objects observed in that region of sky.

    Input parameters:
    -----------------
    catalogdb is a CatalogDBObject instantiation connecting to the database
    of objects to be observed.

    opsimdb is the path to the OpSim database of observation.

    opsimdriver (optional; default 'sqlite') indicates the database driver to
    be used when connecting to opsimdb.
    """

    _lightCurveCatalogClass = None
    _brightness_name = 'mag'

    def __init__(self, catalogdb, opsimdb, opsimdriver="sqlite"):
        self._generator = ObservationMetaDataGenerator(database=opsimdb,
                                                       driver=opsimdriver)

        self._catalogdb = catalogdb

        # optional constraint on query to catalog database
        # (usually 'varParamStr IS NOT NULL')
        if not hasattr(self, '_constraint'):
            self._constraint = None

    def _filter_chunk(self, chunk):
        return chunk

    def get_pointings(self, ra, dec,
                      bandpass=('u', 'g', 'r', 'i', 'z', 'y'),
                      expMJD=None,
                      boundLength=1.75):
        """
        Inputs
        -------
        ra is a tuple indicating the (min, max) values of RA in degrees.

        dec is a tuple indicating the (min, max) values of Dec in degrees.

        bandpass is a str (i.e. 'u', 'g', 'r', etc.) or an iterable indicating
        which filter(s) you want the light curves in.  Defaults to all six
        LSST bandpasses.

        expMJD is an optional tuple indicating a (min, max) range in MJD.
        Defaults to None, in which case, the light curves over the entire
        10 year survey are returned.

        boundLength is the radius in degrees of the field of view of each
        returned ObservationMetaData (default=1.75, the radius of the LSST
        field of view).

        Outputs
        -------
        A 2-D list of ObservationMetaData objects.  Each row is a list of
        ObservationMetaDatas that point to the same patch of sky, sorted by MJD.
        Pointings will not be sorted or grouped by filter.
        """

        print('parameters', ra, dec, bandpass, expMJD)
        if isinstance(bandpass, str):
            obs_list = self._generator.getObservationMetaData(fieldRA=ra,
                                                              fieldDec=dec,
                                                              telescopeFilter=bandpass,
                                                              expMJD=expMJD,
                                                              boundLength=boundLength)
        else:
            # obs_list will be populated with a list of lists of ObservationMetaData.
            # These ObervationMetaData will have pointingRA, pointingDec, filters,
            # and mjd values as specified by the user-input parameters.
            # Each row of obs_list will be a list of ObservationMetaData with identical
            # pointingRA and pointingDec.
            #
            obs_list = []
            for bp in bandpass:
                sub_list = self._generator.getObservationMetaData(fieldRA=ra,
                                                                  fieldDec=dec,
                                                                  telescopeFilter=bp,
                                                                  expMJD=expMJD,
                                                                  boundLength=boundLength)
                obs_list += sub_list

        if len(obs_list) == 0:
            print("No observations found matching your criterion")
            return None

        # Group the OpSim pointings so that all of the pointings centered on the same
        # point in the sky are in a list together (this will allow us to generate the
        # light curves one pointing at a time without having to query the database for
        # the same results more than once.
        tol = 1.0e-12

        obs_groups = []  # a list of list of the indices of the ObservationMetaDatas
                         # in obs_list.  All of the ObservationMetaData in
                         # obs_list[i] will point to the same point on the sky.

        mjd_groups = []  # a list of lists of the MJDs of the ObservationMetaDatas
                         # so that they can be sorted into chronological order before
                         # light curves are calculated

        for iobs, obs in enumerate(obs_list):
            group_dex = -1

            for ix, obs_g in enumerate(obs_groups):
                dd = haversine(obs._pointingRA, obs._pointingDec,
                               obs_list[obs_g[0]]._pointingRA, obs_list[obs_g[0]]._pointingDec)
                if dd < tol:
                    group_dex = ix
                    break

            if group_dex == -1:
                obs_groups.append([iobs])
                mjd_groups.append([obs_list[iobs].mjd.TAI])
            else:
                obs_groups[group_dex].append(iobs)
                mjd_groups[group_dex].append(obs_list[iobs].mjd.TAI)

        # rearrange each group of ObservationMetaDatas so that they
        # appear in chronological order by MJD
        obs_groups_out = []
        for ix, (grp, mjd) in enumerate(zip(obs_groups, mjd_groups)):
            oo = np.array(grp)
            mm = np.array(mjd)
            dexes = np.argsort(mm)
            obs_groups_out.append([obs_list[ii] for ii in oo[dexes]])

        return obs_groups_out

    def _get_query_from_group(self, grp, chunk_size, lc_per_field=None, constraint=None):
        """
        Take a group of ObervationMetaData that all point to the same region
        of the sky.  Query the CatSim database for all of the celestial objects
        in that region, and return it as an iterator over database rows.

        grp is a list of ObservationMetaData that all point at the same field
        on the sky.

        chunk_size is an int specifying th largest chunk of database rows
        to be held in memory atthe same time.

        lc_per_field specifies the maximum number of light curves to return
        per field of view (None implies no constraint).

        constraint is a string containing a SQL constraint to be applied to
        all database queries associated with generating these light curves
        (optional).
        """

        if self._constraint is not None and constraint is not None:
            master_constraint = self._constraint + ' AND ' + constraint
        elif self._constraint is not None and constraint is None:
            master_constraint = self._constraint
        elif self._constraint is None and constraint is not None:
            master_constraint = constraint
        else:
            master_constraint = None

        cat = self._lightCurveCatalogClass(self._catalogdb, obs_metadata=grp[0])

        cat.db_required_columns()

        query_result = cat.db_obj.query_columns(colnames=cat._active_columns,
                                                obs_metadata=cat.obs_metadata,
                                                constraint=master_constraint,
                                                limit=lc_per_field,
                                                chunk_size=chunk_size)

        return query_result

    def _light_curves_from_query(self, cat_dict, query_result, grp, lc_per_field=None):
        """
        Read in an iterator over database rows and return light curves for
        all of the objects contained.

        Input parameters:
        -----------------
        cat_dict is a dict of InstanceCatalogs keyed on bandpass name.  There
        only needs to be one InstanceCatalog per bandpass name.  These dummy
        catalogs provide the methods needed to calculate synthetic photometry.

        query_result is an iterator over database rows that correspond to
        celestial objects in our field of view.

        grp is a list of ObservationMetaData objects that all point to the
        region of sky containing the objects in query_result.  cat_dict
        should contain an InstanceCatalog for each bandpass represented in
        grp.

        lc_per_field is an optional int specifying the number of objects per
        OpSim field to return.  Ordinarily, this is handled at the level of
        querying the database, but, when querying our tiled galaxy tables,
        it is impossible to impose a row limit on the query.  Therefore,
        we may have to place the lc_per_field restriction here.

        Output
        ------
        This method does not output anything.  It adds light curves to the
        instance member variables self.mjd_dict, self.bright_dict, self.sig_dict,
        and self.truth_dict.
        """

        global _sed_cache

        # local_gamma_cache will cache the InstanceCatalog._gamma_cache
        # values used by the photometry mixins to efficiently calculate
        # photometric uncertainties in each catalog.
        local_gamma_cache = {}

        row_ct = 0

        for raw_chunk in query_result:
            chunk = self._filter_chunk(raw_chunk)
            if lc_per_field is not None:

                if row_ct >= lc_per_field:
                    break

                if row_ct + len(chunk) > lc_per_field:
                    chunk = chunk[:lc_per_field-row_ct]
                    row_ct += len(chunk)
                else:
                    row_ct += len(chunk)

            if chunk is not None:
                for ix, obs in enumerate(grp):
                    cat = cat_dict[obs.bandpass]
                    cat.obs_metadata = obs
                    if ix in local_gamma_cache:
                        cat._gamma_cache = local_gamma_cache[ix]
                    else:
                        cat._gamma_cache = {}

                    for star_obj in \
                        cat.iter_catalog(query_cache=[chunk]):

                        if not np.isnan(star_obj[3]) and not np.isinf(star_obj[3]):

                            if star_obj[0] not in self.truth_dict:
                                self.truth_dict[star_obj[0]] = star_obj[5]

                            if star_obj[0] not in self.mjd_dict:
                                self.mjd_dict[star_obj[0]] = {}
                                self.bright_dict[star_obj[0]] = {}
                                self.sig_dict[star_obj[0]] = {}

                            bp = cat.obs_metadata.bandpass
                            if bp not in self.mjd_dict[star_obj[0]]:
                                self.mjd_dict[star_obj[0]][bp] = []
                                self.bright_dict[star_obj[0]][bp] = []
                                self.sig_dict[star_obj[0]][bp] = []

                            self.mjd_dict[star_obj[0]][bp].append(cat.obs_metadata.mjd.TAI)
                            self.bright_dict[star_obj[0]][bp].append(star_obj[3])
                            self.sig_dict[star_obj[0]][bp].append(star_obj[4])

                    if ix not in local_gamma_cache:
                        local_gamma_cache[ix] = cat._gamma_cache

            _sed_cache = {}  # before moving on to the next chunk of objects

    def light_curves_from_pointings(self, pointings, chunk_size=100000,
                                    lc_per_field=None, constraint=None):
        """
        Generate light curves for all of the objects in a particular region
        of sky in a particular bandpass.

        Input parameters:
        -----------------

        pointings is a 2-D list of ObservationMetaData objects.  Each row
        of pointings is a list of ObservationMetaDatas that all point to
        the same patch of sky, sorted by MJD.  This can be generated with
        the method get_pointings().

        chunk_size (optional; default=10000) is an int specifying how many
        objects to pull in from the database at a time.  Note: the larger
        this is, the faster the LightCurveGenerator will run, because it
        will be handling more objects in memory at once.

        lc_per_field (optional; default None) is an int specifying the maximum
        number of light curves to return per field of view (None implies no
        constraint).

        constraint is a string containing a SQL constraint to be applied to
        all database queries associated with generating these light curves
        (optional).

        Output:
        -------
        A dict of light curves.  The dict is keyed on the object's uniqueId.
        This yields a dict keyed on bandpass, which yields a dict keyed on
        'mjd', 'mag', and 'error', i.e.

        output[111]['u']['mjd'] is a numpy array of the MJD of observations
        of object 111 in the u band.

        output[111]['u']['mag'] is a numpy array of the magnitudes of
        object 111 in the u band.

        output[111]['u']['error'] is a numpy array of the magnitude uncertainties
        of object 111 in the u band.

        And a dict of truth data for each of the objects (again, keyed on
        uniqueId).  The contents of this dict will vary, depending on the
        variability model being used, but should be sufficient to reconstruct
        the actual light curves 'by hand' if necessary (or determine the true
        period of a variable source, if attempting to evaluate the performance
        of a classification scheme against a proposed observing cadence).
        """

        # First get the list of ObservationMetaData objects corresponding
        # to the OpSim pointings in the region and bandpass of interest

        t_start = time.time()

        self.mjd_dict = {}
        self.bright_dict = {}
        self.sig_dict = {}
        self.band_dict = {}
        self.truth_dict = {}

        cat_dict = {}
        for grp in pointings:
            for obs in grp:
                if obs.bandpass not in cat_dict:
                    cat_dict[obs.bandpass] = self._lightCurveCatalogClass(self._catalogdb, obs_metadata=obs)

        # Loop over the list of groups ObservationMetaData objects,
        # querying the database and generating light curves.
        for grp in pointings:

            self._mjd_min = grp[0].mjd.TAI
            self._mjd_max = grp[-1].mjd.TAI

            print('starting query')

            t_before_query = time.time()
            query_result = self._get_query_from_group(grp, chunk_size, lc_per_field=lc_per_field,
                                                      constraint=constraint)

            print('query took ', time.time()-t_before_query)

            self._light_curves_from_query(cat_dict, query_result, grp, lc_per_field=lc_per_field)

        output_dict = {}
        for unique_id in self.mjd_dict:
            output_dict[unique_id] = {}
            for bp in self.mjd_dict[unique_id]:

                output_dict[unique_id][bp] = {}

                # we must sort the MJDs because, if an object appears in multiple
                # spatial pointings, its observations will be concatenated out of order
                mjd_arr = np.array(self.mjd_dict[unique_id][bp])
                mjd_dexes = np.argsort(mjd_arr)

                output_dict[unique_id][bp]['mjd'] = mjd_arr[mjd_dexes]
                output_dict[unique_id][bp][self._brightness_name] = \
                    np.array(self.bright_dict[unique_id][bp])[mjd_dexes]
                output_dict[unique_id][bp]['error'] = np.array(self.sig_dict[unique_id][bp])[mjd_dexes]

        print('light curves took %e seconds to generate' % (time.time()-t_start))
        return output_dict, self.truth_dict


class FastLightCurveGenerator(LightCurveGenerator):
    """
    This LightCurveGenerator sub-class will be specifically designed for variability
    models that are implemented as

    mag = quiescent_mag + delta_mag(t)

    where quiescent_mag does not change as a function of time.

    It will re-implement the _light_curves_from_query() method so that quiescent_mag
    is only calculated once, and delta_mag(t) is calculated in a vectorized fashion.
    """

    def _light_curves_from_query(self, cat_dict, query_result, grp, lc_per_field=None):
        """
        Read in an iterator over database rows and return light curves for
        all of the objects contained.

        Input parameters:
        -----------------
        cat_dict is a dict of InstanceCatalogs keyed on bandpass name.  There
        only needs to be one InstanceCatalog per bandpass name.  These dummy
        catalogs provide the methods needed to calculate synthetic photometry.

        query_result is an iterator over database rows that correspond to
        celestial objects in our field of view.

        grp is a list of ObservationMetaData objects that all point to the
        region of sky containing the objects in query_result.  cat_dict
        should contain an InstanceCatalog for each bandpass represented in
        grp.

        lc_per_field is an optional int specifying the number of objects per
        OpSim field to return.  Ordinarily, this is handled at the level of
        querying the database, but, when querying our tiled galaxy tables,
        it is impossible to impose a row limit on the query.  Therefore,
        we may have to place the lc_per_field restriction here.

        Output
        ------
        This method does not output anything.  It adds light curves to the
        instance member variables self.mjd_dict, self.bright_dict, self.sig_dict,
        and self.truth_dict.
        """

        print('using fast light curve generator')

        global _sed_cache

        # local_gamma_cache will cache the InstanceCatalog._gamma_cache
        # values used by the photometry mixins to efficiently calculate
        # photometric uncertainties in each catalog.
        local_gamma_cache = {}

        row_ct = 0

        # assemble dicts needed for data precalculation
        #
        # quiescent_ob_dict contains one ObservationMetaData per bandpass
        #
        # mjd_arr_dict is a dict of all of the mjd values needed per bandpass
        #
        # time_lookup_dict is a dict of dicts; for each bandpass it will
        # provide a dict that allows you to convert mjd to index in the
        # mjd_arr_dict[bp] array.
        quiescent_obs_dict = {}
        mjd_arr_dict = {}
        time_lookup_dict = {}
        for obs in grp:
            bp = obs.bandpass
            if bp not in quiescent_obs_dict:
                quiescent_obs_dict[bp] = obs
            if bp not in mjd_arr_dict:
                mjd_arr_dict[bp] = []
            mjd_arr_dict[bp].append(obs.mjd.TAI)
            if bp not in time_lookup_dict:
                time_lookup_dict[bp] = {}
            time_lookup_dict[bp][obs.mjd.TAI] = len(mjd_arr_dict[obs.bandpass])-1

        for bp in mjd_arr_dict:
            mjd_arr_dict[bp] = np.array(mjd_arr_dict[bp])

        for raw_chunk in query_result:
            chunk = self._filter_chunk(raw_chunk)
            if lc_per_field is not None:

                if row_ct >= lc_per_field:
                    break

                if row_ct + len(chunk) > lc_per_field:
                    chunk = chunk[:lc_per_field-row_ct]
                    row_ct += len(chunk)
                else:
                    row_ct += len(chunk)

            if chunk is not None:
                quiescent_mags = {}
                d_mags = {}
                # pre-calculate quiescent magnitudes
                # and delta magnitude arrays
                for bp in quiescent_obs_dict:
                    cat = cat_dict[bp]
                    cat.obs_metadata = quiescent_obs_dict[bp]
                    local_quiescent_mags = []
                    for star_obj in cat.iter_catalog(query_cache=[chunk]):
                        local_quiescent_mags.append(star_obj[6])
                    quiescent_mags[bp] = np.array(local_quiescent_mags)
                    if self.delta_name_mapper(bp) not in cat._actually_calculated_columns:
                        cat._actually_calculated_columns.append(self.delta_name_mapper(bp))
                    varparamstr = cat.column_by_name('varParamStr')
                    temp_d_mags = cat.applyVariability(varparamstr, mjd_arr_dict[bp])
                    d_mags[bp] = temp_d_mags[{'u':0, 'g':1, 'r':2, 'i':3, 'z':4, 'y':5}[bp]].transpose()

                for ix, obs in enumerate(grp):
                    bp = obs.bandpass
                    cat = cat_dict[bp]
                    cat.obs_metadata = obs
                    time_dex = time_lookup_dict[bp][obs.mjd.TAI]

                    # build up a column_cache of the pre-calculated
                    # magnitudes from above that can be passed into
                    # our catalog iterators so that the catalogs will
                    # not spend time computing things that have already
                    # been calculated
                    local_column_cache = {}
                    delta_name = self.delta_name_mapper(bp)
                    total_name = self.total_name_mapper(bp)

                    if delta_name in cat._compound_column_names:
                        compound_key = None
                        for key in cat._column_cache:
                            if isinstance(cat._column_cache[key], OrderedDict):
                                if delta_name in cat._column_cache[key]:
                                    compound_key = key
                                    break
                        local_column_cache[compound_key] = OrderedDict([(delta_name, d_mags[bp][time_dex])])
                    else:
                        local_column_cache[delta_name] = d_mags[bp][time_dex]

                    if total_name in cat._compound_column_names:
                        compound_key = None
                        for key in cat._column_cache:
                            if isinstance(cat._column_cache[key], OrderedDict):
                                if total_name in cat._column_cache[key]:
                                    compound_key = key
                                    break
                        local_column_cache[compound_key] = OrderedDict([(total_name, quiescent_mags[bp]+d_mags[bp][time_dex])])
                    else:
                        local_column_cache[total_name] = quiescent_mags[bp] + d_mags[bp][time_dex]

                    if ix in local_gamma_cache:
                        cat._gamma_cache = local_gamma_cache[ix]
                    else:
                        cat._gamma_cache = {}

                    for star_obj in \
                        cat.iter_catalog(query_cache=[chunk], column_cache=local_column_cache):

                        if not np.isnan(star_obj[3]) and not np.isinf(star_obj[3]):

                            if star_obj[0] not in self.truth_dict:
                                self.truth_dict[star_obj[0]] = star_obj[5]

                            if star_obj[0] not in self.mjd_dict:
                                self.mjd_dict[star_obj[0]] = {}
                                self.bright_dict[star_obj[0]] = {}
                                self.sig_dict[star_obj[0]] = {}

                            bp = cat.obs_metadata.bandpass
                            if bp not in self.mjd_dict[star_obj[0]]:
                                self.mjd_dict[star_obj[0]][bp] = []
                                self.bright_dict[star_obj[0]][bp] = []
                                self.sig_dict[star_obj[0]][bp] = []

                            self.mjd_dict[star_obj[0]][bp].append(cat.obs_metadata.mjd.TAI)
                            self.bright_dict[star_obj[0]][bp].append(star_obj[3])
                            self.sig_dict[star_obj[0]][bp].append(star_obj[4])

                    if ix not in local_gamma_cache:
                        local_gamma_cache[ix] = cat._gamma_cache

            _sed_cache = {}  # before moving on to the next chunk of objects


class StellarLightCurveGenerator(LightCurveGenerator):
    """
    This class will find all of the OpSim pointings in a particular region
    of the sky in a particular filter and then return light curves for all
    of the stellar objects observed in that region of sky.

    Input parameters:
    -----------------
    catalogdb is a CatalogDBObject instantiation connecting to the database
    of objects to be observed.

    opsimdb is the path to the OpSim database of observation.

    opsimdriver (optional; default 'sqlite') indicates the database driver to
    be used when connecting to opsimdb.
    """

    def __init__(self, *args, **kwargs):
        self._lightCurveCatalogClass = _stellarLightCurveCatalog
        self._constraint = 'varParamStr IS NOT NULL'
        super(StellarLightCurveGenerator, self).__init__(*args, **kwargs)


class FastStellarLightCurveGenerator(FastLightCurveGenerator,
                                     StellarLightCurveGenerator):

    def delta_name_mapper(self, bp):
        return 'delta_lsst_%s' % bp

    def total_name_mapper(self, bp):
        return 'lsst_%s' % bp


class AgnLightCurveGenerator(LightCurveGenerator):
    """
    This class will find all of the OpSim pointings in a particular region
    of the sky in a particular filter and then return light curves for all
    of AGN observed in that region of sky.

    Input parameters:
    -----------------
    catalogdb is a CatalogDBObject instantiation connecting to the database
    of AGN to be observed.

    opsimdb is the path to the OpSim database of observation.

    opsimdriver (optional; default 'sqlite') indicates the database driver to
    be used when connecting to opsimdb.
    """

    def __init__(self, *args, **kwargs):
        self._lightCurveCatalogClass = _agnLightCurveCatalog
        self._constraint = 'varParamStr IS NOT NULL'
        super(AgnLightCurveGenerator, self).__init__(*args, **kwargs)


class FastAgnLightCurveGenerator(FastLightCurveGenerator,
                                 AgnLightCurveGenerator):

    def delta_name_mapper(self, bp):
        return 'delta_%sAgn' % bp

    def total_name_mapper(self, bp):
        return '%sAgn' % bp
