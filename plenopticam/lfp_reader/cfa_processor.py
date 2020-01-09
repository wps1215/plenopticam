#!/usr/bin/env python

__author__ = "Christopher Hahne"
__email__ = "info@christopherhahne.de"
__license__ = """
    Copyright (c) 2019 Christopher Hahne <info@christopherhahne.de>

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""


from plenopticam import misc
from plenopticam.cfg import PlenopticamConfig

# external libs
import numpy as np

try:
    from scipy.signal import medfilt
    from scipy.ndimage import median_filter
except ImportError:
    raise ImportError('Please install scipy package.')

try:
    from colour_demosaicing import demosaicing_CFA_Bayer_bilinear, demosaicing_CFA_Bayer_Malvar2004, demosaicing_CFA_Bayer_Menon2007
except ImportError:
    raise ImportError('Please install colour_demosaicing package')


class CfaProcessor(object):

    def __init__(self, bay_img=None, cfg=None, sta=None):

        # input variables
        self.cfg = cfg if cfg is not None else PlenopticamConfig()
        self.sta = sta if sta is not None else misc.PlenopticamStatus()

        # internal variables
        self._bit_pac = self.cfg.lfpimg['bit'] if hasattr(self.cfg.lfpimg, 'bit') else 10
        self._bay_img = bay_img.astype('float') if type(bay_img) is np.ndarray else None

        # output variables
        self._rgb_img = np.array([])

    def main(self):

        # debayer to rgb image
        if 'bay' in self.cfg.lfpimg.keys() and len(self._bay_img.shape) == 2:
            self.bay2rgb()

        # color matrix correction
        if 'ccm' in self.cfg.lfpimg.keys():
            # transpose and flip ccm_mat for RGB order
            ccm_mat = np.reshape(self.cfg.lfpimg['ccm'], (3, 3))#[::-1, ::-1].T
            self._rgb_img = self.correct_color(self._rgb_img, ccm_mat=ccm_mat)

            #self.sta.status_msg('Save CCM Image')
            #self.sta.status_msg(0)
            #misc.save_img_file(self._rgb_img, 'img_ccm')
            #self.sta.progress(100)

        # convert to uint16
        self._rgb_img = misc.Normalizer(self._rgb_img).uint16_norm()

        return True

    def bay2rgb(self, method=2):

        # print status
        self.sta.status_msg('Debayering', self.cfg.params[self.cfg.opt_prnt])
        self.sta.progress(None, self.cfg.params[self.cfg.opt_prnt])

        # Bayer to RGB conversion
        if method == 0:
            self._rgb_img = demosaicing_CFA_Bayer_bilinear(self._bay_img.astype(np.float32), self.cfg.lfpimg['bay'])
        elif method == 1:
            self._rgb_img = demosaicing_CFA_Bayer_Malvar2004(self._bay_img.astype(np.float32), self.cfg.lfpimg['bay'])
        else:
            self._rgb_img = demosaicing_CFA_Bayer_Menon2007(self._bay_img.astype(np.float32), self.cfg.lfpimg['bay'])

        # normalize image to previous intensity limits
        #obj = misc.Normalizer(img=self._rgb_img,
        #                      min=np.percentile(self._rgb_img, .05), max=np.percentile(self._rgb_img, 99.95))
        #self._rgb_img = obj.type_norm(lim_min=self._bay_img.min(), lim_max=self._bay_img.max())

        # update status message
        self.sta.progress(100, self.cfg.params[self.cfg.opt_prnt])

        return True

    def _reshape_bayer(self):

        if len(self._bay_img.shape) == 2:
            # reshape bayer image to 4 channels in third dimension
            self._bay_img = np.dstack((self._bay_img[0::2, 0::2], self._bay_img[0::2, 1::2],
                                       self._bay_img[1::2, 0::2], self._bay_img[1::2, 1::2]))

        elif len(self._bay_img.shape) == 3:
            if self._bay_img.shape[2] == 4:
                # reshape 4 channel bayer image to 2D bayer image
                arr, self._bay_img = self._bay_img, np.zeros(np.array(self._bay_img.shape[:2])*2)
                self._bay_img[0::2, 0::2] = arr[..., 0]
                self._bay_img[0::2, 1::2] = arr[..., 1]
                self._bay_img[1::2, 0::2] = arr[..., 2]
                self._bay_img[1::2, 1::2] = arr[..., 3]

        return True

    @property
    def rgb_img(self):
        return self._rgb_img.copy()

    @staticmethod
    def correct_gamma(img, gamma=None):
        ''' perform gamma correction on single image '''

        gamma = 1. if gamma is None else gamma

        return np.asarray(img, dtype='float64')**gamma

    @staticmethod
    def correct_awb(img_arr, bay_pattern=None, gains=None):
        ''' automatic white balance '''

        # skip process if gains not set
        if gains is None:
            return img_arr

        if len(img_arr.shape) == 3:

            img_arr[..., 2] *= gains[0]             # blue channel
            img_arr[..., 0] *= gains[1]             # red channel
            img_arr[..., 1] *= gains[2]*gains[3]    # green channel

        elif len(img_arr.shape) == 2 and bay_pattern == "GRBG":

            img_arr[1::2, 0::2] *= gains[0]         # blue channel
            img_arr[0::2, 1::2] *= gains[1]         # red channel
            img_arr[0::2, 0::2] *= gains[2]         # green-red channel
            img_arr[1::2, 1::2] *= gains[3]         # green-blue channel

        elif len(img_arr.shape) == 2 and bay_pattern == "BGGR":

            img_arr[0::2, 0::2] *= gains[0]         # blue channel
            img_arr[1::2, 1::2] *= gains[1]         # red channel
            img_arr[0::2, 1::2] *= gains[2]         # green-blue channel
            img_arr[1::2, 0::2] *= gains[3]         # green-red channel

        return img_arr

    @staticmethod
    def desaturate_clipped(img_arr, bay_pattern=None, gains=None):

        # skip process if gains not set
        if gains is not None:
            if len(img_arr.shape) == 3 and img_arr.shape[-1] == 4:
                if bay_pattern is "GRBG":
                    gains = np.array([gains[2], gains[1], gains[0], gains[3]])
                elif bay_pattern is "BGGR":
                    gains = np.array([gains[0], gains[2], gains[3], gains[1]])
                else:
                    return img_arr
            elif len(img_arr.shape) == 3 and img_arr.shape[-1] == 3:
                gains = np.array([gains[1], (gains[2]+gains[3])/2, gains[0]])
            else:
                return img_arr
        else:
            return img_arr

        # original channel intensities
        orig = img_arr / gains

        # identify clipped pixels
        beta = orig / np.amax(orig, axis=2)[..., np.newaxis]
        weights = beta * gains
        weights[weights < 1] = 1
        mask = np.zeros(orig.shape[:2])
        mask[np.amax(orig, axis=2) >= orig.max()] = 1

        # de-saturate clipped values
        img_arr[mask > 0] /= weights[mask > 0]

        return img_arr

    @staticmethod
    def correct_color(img, ccm_mat=np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]])):
        ''' color correction according to http://www.imatest.com/docs/colormatrix/ using Case 1 '''

        new = np.zeros_like(img)
        new[..., 2] = img[..., 0]
        new[..., 1] = img[..., 1]
        new[..., 0] = img[..., 2]

        # perform color correction
        img_ccm = np.dot(ccm_mat, np.vstack(new).T).T.reshape(img.shape)

        img[..., 2] = img_ccm[..., 0]
        img[..., 1] = img_ccm[..., 1]
        img[..., 0] = img_ccm[..., 2]

        return img

    def safe_bayer_awb(self):

        gains = np.asarray(self.cfg.lfpimg['awb'], dtype='float64')
        self._bay_img = self.correct_awb(self._bay_img, self.cfg.lfpimg['bay'], gains=gains)
        self._reshape_bayer()
        self._bay_img = self.desaturate_clipped(self._bay_img, self.cfg.lfpimg['bay'], gains=gains)
        self._reshape_bayer()
