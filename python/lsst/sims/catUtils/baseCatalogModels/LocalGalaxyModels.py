import os
import numpy as np
import json
from lsst.utils import getPackageDir
from lsst.sims.utils import HalfSpace
from lsst.sims.utils import halfSpaceFromRaDec
from lsst.sims.utils import halfSpaceFromPoints
from lsst.sims.utils import intersectHalfSpaces
from lsst.sims.utils import cartesianFromSpherical, sphericalFromCartesian
from lsst.sims.catUtils.baseCatalogModels import GalaxyTileObj

__all__ = ["FatboyTiles"]


class Tile(object):

    def __init__(self, box_corners):
        self._trixel_bounds = None
        self._trixel_bound_level = None
        self._hs_list = []
        if len(box_corners) == 0:
            return
        self._init_from_corners(box_corners)

    def _init_from_corners(self, box_corners):
        ra_range = [c[0] for c in box_corners]
        ra_min = min(ra_range)
        ra_max = max(ra_range)
        dec_range = [c[1] for c in box_corners]
        dec_min = min(dec_range)
        dec_max = max(dec_range)
        #print(tile_id,dec_min,dec_max)
        tol = 1.0e-10
        for i_c1 in range(len(box_corners)):
            c1 = box_corners[i_c1]
            pt1 = cartesianFromSpherical(np.degrees(c1[0]), np.degrees(c1[1]))
            for i_c2 in range(i_c1+1, len(box_corners), 1):
                hs = None
                c2 = box_corners[i_c2]
                pt2 = cartesianFromSpherical(np.degrees(c2[0]), np.degrees(c2[1]))
                if np.abs(1.0-np.dot(pt1, pt2))<tol:
                    continue

                dra = np.abs(c1[0]-c2[0])
                ddec = np.abs(c1[1]-c2[1])

                if dra<tol and ddec>tol:
                    # The RAs of the two corners is identical, but the Decs are
                    # different; this Half Space is defined by a Great Circle
                    if np.abs(c1[0]-ra_min)<tol:
                        inner_pt = (ra_min+0.001, dec_min+0.001)
                    else:
                        inner_pt = (ra_max-0.001, dec_min+0.001)
                    hs = halfSpaceFromPoints(c1, c2, inner_pt)
                elif ddec<tol and dra>tol:
                    # The Decs of the two corners is identical, bu the RAs are
                    # different; this Half Space is defined by a line of constant
                    # Dec and should be centered at one of the poles
                    if np.abs(c1[1]-dec_min)<tol:
                        hs = halfSpaceFromRaDec(0.0, 90.0, 90.0-dec_min)
                    else:
                        hs = halfSpaceFromRaDec(0.0, -90.0, 90.0+dec_max)
                else:
                    continue

                if hs is None:
                    raise RuntimeError("Somehow Half Space == None")
                self._hs_list.append(hs)

    def contains_many_pts(self, pts):
        result = None
        for hs in self.half_space_list:
            valid = hs.contains_many_pts(pts)
            if result is None:
                result = valid
            else:
                result &= valid
        return result

    @property
    def half_space_list(self):
        return self._hs_list

    def rotate(self, matrix):
        new_tile = Tile([])
        for hs in self.half_space_list:
            vv = np.dot(matrix, hs.vector)
            new_hs = HalfSpace(vv, hs.dd)
            new_tile._hs_list.append(new_hs)
        return new_tile

    def intersects_circle(self, center_pt, radius_rad):
        gross_is_contained = True
        for hs in self.half_space_list:
            if not hs.intersects_circle(center_pt, radius_rad):
                gross_is_contained = False
                break
        if not gross_is_contained:
            return False

        hs_interest = HalfSpace(center_pt, np.cos(radius_rad))
        for i_h1 in range(len(self.half_space_list)):
            hs1 = self.half_space_list[i_h1]
            roots = intersectHalfSpaces(hs1, hs_interest)
            if len(roots) == 0:
                continue

            for i_h2 in range(len(self.half_space_list)):
                if i_h1 == i_h2:
                    continue
                hs2 = self.half_space_list[i_h2]
                local_contained = False
                for rr in roots:
                    if hs2.contains_pt(rr):
                        local_contained = True
                        break
                if not local_contained:
                    return False
        return True

    def _generate_all_trixels(self, level):
        output = None
        for hs in self.half_space_list:
            local_limits = hs.findAllTrixels(level)
            if output is None:
                output = local_limits
            else:
                output = HalfSpace.join_trixel_bound_sets(output, local_limits)
        self._trixel_bounds = output
        self._trixel_bound_level = level
        return None

    @property
    def trixel_bound_level(self):
        return self._trixel_bound_level

    @property
    def trixel_bounds(self):
        return self._trixel_bounds

    def find_all_trixels(self, level):
        if self._trixel_bounds is None or self.trixel_bound_level != level:
            self._generate_all_trixels(level)
        return self._trixel_bounds


class FatboyTiles(object):
    """
    A class to store the fatboy galaxy tiles as a series of Half Spaces
    """

    def __init__(self):
        data_dir = os.path.join(getPackageDir('sims_catUtils'), 'data')
        data_file = os.path.join(data_dir, 'tile_data.txt')
        dtype = np.dtype([('id', int), ('ra', float), ('dec', float),
                          ('box', str, 500)])
        tile_data = np.genfromtxt(data_file, dtype=dtype, delimiter=';')

        self._tile_id = tile_data['id']
        self._tile_ra = {}
        self._tile_dec = {}
        self._rotation_matrix_dict = {}
        for ii, rr, dd, in zip(tile_data['id'], tile_data['ra'], tile_data['dec']):
            self._tile_ra[ii] = rr
            self._tile_dec[ii] = dd
            ra_rad = np.radians(rr)
            dec_rad = np.radians(dd)

            ra_mat = np.array([[np.cos(ra_rad), np.sin(ra_rad), 0.0],
                               [-np.sin(ra_rad), np.cos(ra_rad), 0.0],
                               [0.0, 0.0, 1.0]])

            dec_mat = np.array([[np.cos(dec_rad), 0.0, np.sin(dec_rad)],
                                [0.0, 1.0, 0.0],
                                [-np.sin(dec_rad), 0.0, np.cos(dec_rad)]])

            full_mat = np.dot(dec_mat, ra_mat)
            self._rotation_matrix_dict[ii] = full_mat

        self._tile_dict = {}
        for tile_id, box in zip(tile_data['id'], tile_data['box']):
            box_corners = json.loads(box)
            self._tile_dict[tile_id] = Tile(box_corners)


    def tile_ra(self, tile_idx):
        return self._tile_ra[tile_idx]

    def tile_dec(self, tile_idx):
        return self._tile_dec[tile_idx]

    def rotation_matrix(self, tile_idx):
        return self._rotation_matrix_dict[tile_idx]

    def tile(self, tile_idx):
        return self._tile_dict[tile_idx]

    def find_all_tiles(self, ra, dec, radius):
        """
        ra, dec, radius are all in degrees

        returns a numpy array of tile IDs that intersect the circle
        """
        valid_id = []
        radius_rad = np.radians(radius)
        center_pt = cartesianFromSpherical(np.radians(ra), np.radians(dec))
        for tile_id in self._tile_dict:
            tile = self._tile_dict[tile_id]
            is_contained = tile.intersects_circle(center_pt, radius_rad)
            if is_contained:
                valid_id.append(tile_id)

        return np.array(valid_id)
