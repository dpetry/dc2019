
#################################
#
# Utilities to facilitate multi-array and single dish data combination
#  developed for ngVLA SBA design evaluation
#  Only used thus far with continuum images (no cubes)
#
# Brian Mason (NRAO)  
#  v1 - Sept 2019
#
# NOTE: do not do this:
# import combo_utils as cu
#  it will generate a global namespace conflict in CASA
#  call it something sillier and more distinctive.
#
#################################

from taskinit import *
from imhead_cli import imhead_cli as imhead
from immath_cli import immath_cli as immath
from imregrid_cli import imregrid_cli as imregrid
from rmtables_cli import rmtables_cli as rmtables
from feather_cli import feather_cli as feather

import numpy as np

def fix_image_calib(sd_image,sd_img_fixed,cal_factor=1.0,beam_factor=1.0):
    """
    Rescale image brightness (cal_factor) and BMAJ,BMIN (beam_factor)
    in a CASA image sd_image (any CASA image). output file to 
    sd_img_fixed.
    """

    immath(imagename=[sd_image],expr='IM0*'+str(cal_factor),outfile=sd_img_fixed)
    hdr = imhead(imagename=sd_image,mode='summary')
    bmaj_str = str(hdr['restoringbeam']['major']['value'] * beam_factor)+hdr['restoringbeam']['major']['unit']
    bmin_str = str(hdr['restoringbeam']['minor']['value'] * beam_factor)+hdr['restoringbeam']['minor']['unit']
    # you have to do BMIN first
    imhead(sd_img_fixed,mode='put',hdkey='BMIN',hdvalue=bmin_str)
    imhead(sd_img_fixed,mode='put',hdkey='BMAJ',hdvalue=bmaj_str)

    return sd_img_fixed

def feather_one(sd_map,int_map,int_pb,tag=''):
    """ 
    Feather together a single dish map sd_map with an interferometric
    map int_map, with primary beams probably handled.

    returns the names of the pbcorrected and not pbcorrected images.
    """

    outfile=int_map+tag+'.feather'
    outfile_pbcord=outfile+'.pbcor'
    outfile_uncorr=outfile
    #rmtables(outfile_uncorr)
    #rmtables(outfile_pbcord)
    rmtables(sd_map+".TMP.intGrid.intPb")
    imregrid(imagename=sd_map,template=int_map,output=sd_map+".TMP.intGrid",overwrite=True)
    immath(imagename=[sd_map+".TMP.intGrid",int_pb],expr='IM0*IM1',outfile=sd_map+".TMP.intGrid.intPb")
    feather(imagename=outfile_uncorr,highres=int_map,lowres=sd_map+".TMP.intGrid.intPb")
    immath(imagename=[outfile_uncorr,int_pb],expr='IM0/IM1',outfile=outfile_pbcord)

    # clean up after self
    rmtables(sd_map+".TMP.intGrid.intPb")
    rmtables(sd_map+".TMP.intGrid")

    return [outfile_pbcord,outfile_uncorr]


def make_clnMod_fromImg(sd_map,int_map,tag='',clean_up=True):
    """ 

    Take sd_map and regrid it into pixel coordinates of int_map, converting from
      Jy/bm into Jy/pix.

    Both input images are CASA images presumed to have surface brightess
     units of Jy/bm

    tag is an optional string that will be included in the outpu file name

    Returns the name of the output file.

    Note: sd_map and int_map can be of any provenance as long as the SB units
    are Jy/bm. Results have only been validated for the case that the sd_map
    pixels are larger than the int_map pixels however.

    """

    regridded_sd_map = sd_map +'.TMP.regrid'
    out_sd_map = sd_map +tag+'.regrid.jyPix'

    imregrid(imagename=sd_map,template=int_map,output=regridded_sd_map,overwrite=True)
    sd_header = imhead(regridded_sd_map)
    int_header = imhead(int_map)

    rad_to_arcsec = 206264.81
    twopi_over_eightLnTwo = 1.133

    flux_conversion = (rad_to_arcsec*np.abs(sd_header['incr'][0]))*(rad_to_arcsec*np.abs(sd_header['incr'][1])) / (twopi_over_eightLnTwo * sd_header['restoringbeam']['major']['value'] * sd_header['restoringbeam']['minor']['value'])

    print "===================="
    print "THESE SHOULD BE ARCSEC:"+sd_header['restoringbeam']['major']['unit']+" "+sd_header['restoringbeam']['minor']['unit']
    print "THESE SHOULD BE RADIANS: "+sd_header['axisunits'][0]+" "+sd_header['axisunits'][1]
    print "if not the unit conversions were wrong...."
    print "===================="

    flux_string = "(IM0 * %f)" % flux_conversion

    rmtables(out_sd_map)
    immath(imagename=regridded_sd_map,expr=flux_string,outfile=out_sd_map,mode='evalexpr')
    new_unit = 'Jy/pixel'
    imhead(imagename=out_sd_map,mode='put',hdkey='BUNIT',hdvalue=new_unit)

    # clean up after self-
    rmtables(regridded_sd_map)

    return out_sd_map

def calc_fidelity(inimg,refimg,pbimg='',psfimg='',fudge_factor=1.0,scale_factor=1.0,pb_thresh=0.25,clean_up=True,outfile=''):
    """Calculate fidelity of inimg with reference to refimg. 

    Use Gaussian PSF with parameters described in inimg header, unless
    an explicit psfimg is provided.

    If a primary beam image (pbimg) is provided, use it to restrict
    the area over which the fidelity is calculated, using pb_thresh as
    the lower limit (relative to max(pbimg)).

    clean_up controls whether intermediate files created in the
    process are removed or not (all contain the string TMP). These can
    be useful for sanity checking, but proper behavior is not
    guaranteed if any are present already when the routine is called.

    outfile specifies the file-name root for a fidelity image and a fractional error
    image that will be created.
       --- ****a pbimg is required to creat the outfile
       
    inimg, refimg, [psfimg], and [pbimg] should be CASA images. outfile is a CASA image.
    All input images should have the same axes and axis order.

    ***pbimg, if provided, should furthermore have the same pixel coordinates as inimg
       (Cell size, npix, coordinate reference pixel, etc)***

    ***all input images should have the same number and ordering of axes!!!

    fudge_factor multiples the beamwidth obtained from the input image, before 
      convolving refimg for comparison
    scale_factor multiplies the inimg pixel values (i.e. it recalibrates them)
      --> use these reluctantly and only if you know what you are doing

    OUTPUTS:  a dictionary containing

      f1 = 1 - max(abs(inimg-refimg)) / max(refimg) - 'classic' definition

      f2 = 1 - sum( refimg .* abs(inimg-refimg) ) / sum( refimg .* inimg)
         --> this is a somewhat poorly behaved fidelity definition that was evaluated for ngVLA
              (appearing in the draft ngVLA science requirements, May 2019)
         --> it is equivalent to a weighted sum of fractional errors, with the fraction taken with
               respect to the formed image inimg and the weight being inimg*refimg

      f2b = 1 - sum( refimg .* abs(inimg-refimg) ) / sum( refimg .* refimg)
         --> this is the original (ngVLA science requirememts, Nov. 2017) and better-behaved 
               ngVLA fidelity definition, with the fraction taken with respect to the model (refimg),
               and the weight being refimg^2

      f3 = 1 - sum( beta .* abs(inimg-refimg) ) / sum( beta.^2 )
         --> this is the current ngVLA fidelity definition that has been adopted, where
                beta_i = max(abs(inimg_i,),abs(refimg_i))

      In all of the above "i" is a pixel index, .* and .^ are element- (pixel-) wise operations,
       and sums are over pixels

      Various ALMA-adopted fidelity measures are also reported, and the correlation coefficient


    HISTORY: 
      August/September 2019 - B. Mason (nrao) - original version

    """

    ia=iatool()

    ia.open(inimg)
    # average over the stokes axis to get it down to 3 axes which is what our other one has
    imvals=np.squeeze(ia.getchunk()) * scale_factor
    img_cs = ia.coordsys()
    # how to trim the freq axis--
    #img_shape = (ia.shape())[0:3]
    img_shape = ia.shape()
    ia.close()
    # get beam info
    hdr = imhead(imagename=inimg,mode='summary')
    bmaj_str = str(hdr['restoringbeam']['major']['value'] * fudge_factor)+hdr['restoringbeam']['major']['unit']
    bmin_str = str(hdr['restoringbeam']['minor']['value'] * fudge_factor)+hdr['restoringbeam']['minor']['unit']
    bpa_str =  str(hdr['restoringbeam']['positionangle']['value'])+hdr['restoringbeam']['positionangle']['unit']

    # i should probably also be setting the beam * fudge_factor in the *header* of the input image

    if len(pbimg) > 0:
        ia.open(pbimg)
        pbvals=np.squeeze(ia.getchunk())
        pbvals /= np.max(pbvals)
        pbvals = np.where( pbvals < pb_thresh, 0.0, pbvals)
        #good_pb_ind=np.where( pbvals >= pb_thresh)
        #bad_pb_ind=np.where( pbvals < pb_thresh)
        #pbvals[good_pb_ind] = 1.0
        #if bad_pb_ind[0]:
        #    pbvals[bad_pb_ind] = 0.0
    else:
        pbvals = imvals*0.0 + 1.0
        #good_pb_ind = np.where(pbvals)
        #bad_pb_ind = [np.array([])]

    ##

    ##############
    # open, smooth, and regrid reference image
    #

    smo_ref_img = refimg+'.TMP.smo'

    # if given a psf image, use that for the convolution. need to regrid onto input
    #   model coordinate system first. this is mostly relevant for the single dish
    #   if the beam isn't very gaussian (as is the case for alma sim tp)
    if len(psfimg) > 0:
        # consider testing and fixing the case the reference image isn't jy/pix
        ia.open(refimg)
        ref_cs=ia.coordsys()
        ref_shape=ia.shape()
        ia.close()
        ia.open(psfimg)
        psf_reg_im=ia.regrid(csys=ref_cs.torecord(),shape=ref_shape,outfile=psfimg+'.TMP.regrid',overwrite=True,axes=[0,1])
        psf_reg_im.done()
        ia.close()
        ia.open(refimg)
        # default of scale= -1.0 autoscales the PSF to have unit area, which preserves "flux" in units of the input map
        #  scale=1.0 sets the PSF to have unit *peak*, which results in flux per beam in the output 
        ref_convd_im=ia.convolve(outfile=smo_ref_img,kernel=psfimg+'.TMP.regrid',overwrite=True,scale=1.0)
        ref_convd_im.setbrightnessunit('Jy/beam')
        ref_convd_im.done()
        ia.close()
        if clean_up:
            rmtables(psfimg+'.TMP.regrid')
    else:
        # consider testing and fixing the case the reference image isn't jy/pix
        ia.open(refimg)    
        im2=ia.convolve2d(outfile=smo_ref_img,axes=[0,1],major=bmaj_str,minor=bmin_str,pa=bpa_str,overwrite=True)
        im2.done()
        ia.close()

    smo_ref_img_regridded = smo_ref_img+'.TMP.regrid'
    ia.open(smo_ref_img)
    im2=ia.regrid(csys=img_cs.torecord(),shape=img_shape,outfile=smo_ref_img_regridded,overwrite=True,axes=[0,1])
    refvals=np.squeeze(im2.getchunk())
    im2.done()
    ia.close()

    ia.open(smo_ref_img_regridded)
    refvals=np.squeeze(ia.getchunk())
    ia.close()

    # set all pixels to zero where the PB is low - to avoid NaN's
    imvals = np.where(pbvals,imvals,0.0)
    refvals = np.where(pbvals,refvals,0.0)
    #if len(bad_pb_ind) > 0:
        #imvals[bad_pb_ind] = 0.0
        #refvals[bad_pb_ind] = 0.0

    deltas=(imvals-refvals).flatten()
    # put both image and model values in one array to calculate Beta for F_3- 
    allvals = np.array( [np.abs(imvals.flatten()),np.abs(refvals.flatten())])
    # the max of (image_pix_i,model_pix_i), in one flat array of length nixels
    maxvals = allvals.max(axis=0)

    # carilli definition. rosero eq1
    f_eq1 = 1.0 - np.max(np.abs(deltas))/np.max(refvals)
    f_eq2 = 1.0 - (refvals.flatten() * np.abs(deltas)).sum() / (refvals * imvals).sum()
    f_eq2b = 1.0 - (refvals.flatten() * np.abs(deltas)).sum() / (refvals * refvals).sum()
    #f_eq3 = 1.0 - (maxvals[gi] * np.abs(deltas[gi])).sum() / (maxvals[gi] * maxvals[gi]).sum()
    f_eq3 = 1.0 - (pbvals.flatten() * maxvals * np.abs(deltas)).sum() / (pbvals.flatten() * maxvals * maxvals).sum()

    # if an output image was requested, and a pbimg was given; make one.
    if ((len(outfile)>0) & (len(pbimg)>0)):
        weightfile= 'mypbweight.TMP.im'
        rmtables(weightfile)
        immath(imagename=[pbimg],mode='evalexpr',expr='ceil(IM0/max(IM0) - '+str(pb_thresh)+')',outfile=weightfile)
        betafile = 'mybeta.TMP.im'
        rmtables(betafile)
        immath(imagename=[inimg,smo_ref_img_regridded],mode='evalexpr',expr='iif(abs(IM0) > abs(IM1),abs(IM0),abs(IM1))',outfile=betafile)
        # 19sep19 - change to the actual F_3 contrib ie put abs() back in
        rmtables(outfile)
        print " Writing fidelity error image: "+outfile
        immath(imagename=[inimg,smo_ref_img_regridded,weightfile,betafile],expr='IM3*IM2*abs(IM0-IM1)/sum(IM3*IM3*IM2)',outfile=outfile)
        # 19sep19 - add fractional error (rel to beta) to output
        rmtables(outfile+'.frac')
        print " Writing fractional error image: "+outfile+'.frac'
        immath(imagename=[inimg,smo_ref_img_regridded,weightfile,betafile],expr='IM2*(IM0-IM1)/IM3',outfile=outfile+'.frac')
        if clean_up:
            rmtables(weightfile)
            rmtables(betafile)

    # pearson correlation coefficient evaluated above beta = 1% peak reference image
    gi=np.where( np.abs(maxvals) > 0.01 * np.abs(refvals.max()) )
    ii = imvals.flatten()
    mm = refvals.flatten()
    mm -= mm.min()
    # (x-mean(x)) * (y-mean(y)) / sigma_x / sigma_y
    cc = (ii[gi] - ii[gi].mean()) * (mm[gi] - mm[gi].mean()) / (np.std(ii[gi]) * np.std(mm[gi]))
    #cc = (ii[gi] - ii[gi].mean()) * (mm[gi] - mm[gi].mean()) / (np.std(mm[gi]))**2
    corco = cc.sum() / cc.shape[0]

    fa = np.abs(mm) / np.abs(mm - ii)
    fa_0p1 = np.median( fa[ (np.abs(ii) > 1e-3 * mm.max()) | (np.abs(mm) > 1e-3 * mm.max())  ])
    fa_1 = np.median( fa[ (np.abs(ii) > 1e-2 * mm.max()) | (np.abs(mm) > 1e-2 * mm.max())  ])
    fa_3 = np.median( fa[ (np.abs(ii) > 3e-2 * mm.max()) | (np.abs(mm) > 3e-2 * mm.max())  ])
    fa_10 = np.median( fa[ (np.abs(ii) > 1e-1 * mm.max()) | (np.abs(mm) > 1e-1 * mm.max()) ] )

    #gi2 = (np.abs(ii) > 1e-3 * mm.max()) | (np.abs(mm) > 1e-3 * mm.max())  

    print "*************************************"
    print 'image: ',inimg,'reference image:',refimg
    print "Eq1  / Eq2  / Eq2b  / Eq3 / corrCoeff "
    print f_eq1, f_eq2, f_eq2b, f_eq3,corco
    print ' ALMA: ',fa_0p1,fa_1,fa_3,fa_10
    print "*************************************"

    fidelity_results = {'f1': f_eq1, 'f2': f_eq2, 'f2b': f_eq2b, 'f3': f_eq3, 'falma': [fa_0p1, fa_1, fa_3, fa_10]}

    if clean_up:
        rmtables(smo_ref_img)
        rmtables(smo_ref_img_regridded)

    return fidelity_results


# run as
#  casa -c comb_utils.py 
#   to run in standalone script mode
#
if __name__ == "__main__":

    image_list = ['joint_30dor.ngvla.revC_new.sdmod.autoDev4.image_plusTpFixed.pbcor']

    for inimg in image_list:
        calc_fidelity(inimg,'sba_30dor_new/sba_30dor_new.ngvla-sba-revC.skymodel',
                      pbimg='joint_30dor.ngvla.revC_newsdmod.autoDev5.pb',fudge_factor=1.0,scale_factor=1.0,
                      pb_thresh=0.25,clean_up=True)
        #,outfile=inimg+'.fiderr')

