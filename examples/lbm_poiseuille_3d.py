#!/usr/bin/python -u

import sys

import math
import numpy
from sailfish import lbm
from sailfish import geo

import optparse
from optparse import OptionGroup, OptionParser, OptionValueError

class LBMGeoPoiseuille(geo.LBMGeo3D):
    """3D Poiseuille geometry."""

    maxv = 0.02

    def define_nodes(self):
        radiussq = (self.get_chan_width() / 2.0)**2

        if self.options.along_z:
            for x in range(0, self.lat_nx):
                for y in range(0, self.lat_ny):
                    if (x-(self.lat_nx/2-0.5))**2 + (y-(self.lat_ny/2-0.5))**2 >= radiussq:
                            self.set_geo((x,y,0), self.NODE_WALL)
            self.fill_geo((slice(None), slice(None), 0))

        elif self.options.along_y:
            for z in range(0, self.lat_nz):
                for x in range(0, self.lat_nx):
                    if (x-(self.lat_nx/2-0.5))**2 + (z-(self.lat_nz/2-0.5))**2 >= radiussq:
                        self.set_geo((x,0,z), self.NODE_WALL)
            self.fill_geo((slice(None), 0, slice(None)))
        else:
            for z in range(0, self.lat_nz):
                for y in range(0, self.lat_ny):
                    if (y-(self.lat_ny/2-0.5))**2 + (z-(self.lat_nz/2-0.5))**2 >= radiussq:
                        self.set_geo((0,y,z), self.NODE_WALL)
            self.fill_geo((0, slice(None), slice(None)))

    def init_dist(self, dist):
        if self.options.stationary:
            h = -0.5
            radius = self.get_chan_width() / 2.0

            if self.options.along_z:
                for x in range(0, self.lat_nx):
                    for y in range(0, self.lat_ny):
                        rc = math.sqrt((x-self.lat_nx/2.0-h)**2 + (y-self.lat_ny/2.0-h)**2)
                        if rc > radius:
                            self.velocity_to_dist((x, y, 0), (0.0, 0.0, 0.0), dist)
                        else:
                            self.velocity_to_dist((x, y, 0), (0.0, 0.0, self.get_velocity(rc)), dist)
                self.fill_dist((slice(None), slice(None), 0), dist)
            elif self.options.along_y:
                for x in range(0, self.lat_nx):
                    for z in range(0, self.lat_nz):
                        rc = math.sqrt((x-self.lat_nx/2.0-h)**2 + (z-self.lat_nz/2.0-h)**2)
                        if rc > radius:
                            self.velocity_to_dist((x, 0, z), (0.0, 0.0, 0.0), dist)
                        else:
                            self.velocity_to_dist((x, 0, z), (0.0, self.get_velocity(rc), 0.0), dist)
                self.fill_dist((slice(None), 0, slice(None)), dist)
            else:
                for z in range(0, self.lat_nz):
                    for y in range(0, self.lat_ny):
                        rc = math.sqrt((z-self.lat_nz/2.0-h)**2 + (y-self.lat_ny/2.0-h)**2)
                        if rc > radius:
                            self.velocity_to_dist((0, y, z), (0.0, 0.0, 0.0), dist)
                        else:
                            self.velocity_to_dist((0, y, z), (self.get_velocity(rc), 0.0, 0.0), dist)
                self.fill_dist((0, slice(None), slice(None)), dist)
        else:
            self.velocity_to_dist((0, 0, 0), (0.0, 0.0, 0.0), dist)
            self.fill_dist((0, 0, 0), dist)

    # Schematic drawing of the simulated system with both on-grid and mid-grid
    # bondary conditions.
    #
    # Columns:
    # 1st: linear distance from one of the pipe walls
    # 2nd: radial distance from the axis of the pipe
    # 3rd: node index
    #
    # width: 6
    #
    # Midgrid BC:
    # chan_width: 4
    #
    # wwww -0.5  2.5  0     -
    # -     0    2.0        |-
    # fff   0.5  1.5  1     |----
    # -     1    1.0        |-----
    # fff   1.5  0.5  2     |------
    # -     2    0.0        |------*
    # fff   2.5  0.5  3     |------
    # -     3    1.0        |-----
    # fff   3.5  1.5  4     |----
    # -     4    2.0        |-
    # wwww  4.5  2.5  5     -
    #
    # On-grid BC:
    # chan_width: 5
    #
    # wwww  0.0  2.5  0     |-
    # -     0.5  2.0        |---
    # fff   1.0  1.5  1     |-----
    # -     1.5  1.0        |------
    # fff   2.0  0.5  2     |-------
    # -     2.5  0.0        |-------*
    # fff   3.0  0.5  3     |-------
    # -     3.5  1.0        |------
    # fff   4.0  1.5  4     |-----
    # -     4.5  2.0        |---
    # wwww  5.0  2.5  5     |-

    def get_velocity_profile(self, fluid_only=False):
        bc = geo.get_bc(self.options.bc_wall)
        x = self.lat_nx/2
        if fluid_only and not bc.wet_nodes:
            zvals = range(1, self.lat_nz-1)
        else:
            zvals = range(0, self.lat_nz)

        ret = []

        for z in zvals:
            rc = math.sqrt((x-self.lat_nx/2.0+0.5)**2 + (z-self.lat_nz/2.0+0.5)**2)
            ret.append(self.get_velocity(rc))

        return ret

    def get_velocity(self, r):
        width = self.get_chan_width()
        return self.maxv/(width/2.0)**2 * ((width/2.0)**2 - r**2)

    def get_chan_width(self):
        bc = geo.get_bc(self.options.bc_wall)
        return self.get_width() - 1 - 2 * bc.location

    def get_width(self):
        if self.options.along_z:
            return min(self.lat_nx, self.lat_ny)
        elif self.options.along_y:
            return min(self.lat_nx, self.lat_nz)
        else:
            return min(self.lat_ny, self.lat_nz)

    def get_reynolds(self, viscosity):
        return int(self.get_width() * self.maxv/viscosity)

class LPoiSim(lbm.FluidLBMSim):

    filename = 'poiseuille3d'

    def __init__(self, geo_class, args=sys.argv[1:], defaults=None):
        opts = []
        opts.append(optparse.make_option('--drive', dest='drive', type='choice', choices=['force'], default='force'))
        opts.append(optparse.make_option('--along_y', dest='along_y', action='store_true', default=False, help='flow along the Y direction'))
        opts.append(optparse.make_option('--along_z', dest='along_z', action='store_true', default=False, help='flow along the Z direction'))
        opts.append(optparse.make_option('--stationary', dest='stationary', action='store_true', default=False, help='start with the correct velocity profile in the whole simulation domain'))

        defaults_ = {'max_iters': 500000, 'visc': 0.1, 'lat_nx': 64, 'lat_ny':
                64, 'lat_nz': 64, 'grid': 'D3Q13', 'verbose': True}
        if defaults is not None:
            defaults_.update(defaults)

        lbm.FluidLBMSim.__init__(self, geo_class, options=opts, args=args, defaults=defaults_)

    def _init_post_geo(self):
        if self.options.drive == 'force':
            accel = self.geo.maxv * (16.0 * self.options.visc) / (self.geo.get_chan_width()**2)

            if self.options.along_z:
                self.options.periodic_z = True
                self.add_body_force((0.0, 0.0, accel))
            elif self.options.along_y:
                self.options.periodic_y = True
                self.add_body_force((0.0, accel, 0.0))
            else:
                self.options.periodic_x = True
                self.add_body_force((accel, 0.0, 0.0))

    def get_profile(self):
        # NOTE: This only works for the 'along_y' option.
        if geo.get_bc(self.options.bc_wall).wet_nodes:
            return self.vy[:,int(self.options.lat_ny/2),int(self.options.lat_nx/2)]
        else:
            return self.vy[1:-1,int(self.options.lat_ny/2),int(self.options.lat_nx/2)]



if __name__ == '__main__':
    sim = LPoiSim(LBMGeoPoiseuille)
    sim.run()
